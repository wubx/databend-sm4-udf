// Scalar SM4 for Databend JS UDFs. No Node.js dependencies.
const SBOX = [
  0xd6,0x90,0xe9,0xfe,0xcc,0xe1,0x3d,0xb7,0x16,0xb6,0x14,0xc2,0x28,0xfb,0x2c,0x05,
  0x2b,0x67,0x9a,0x76,0x2a,0xbe,0x04,0xc3,0xaa,0x44,0x13,0x26,0x49,0x86,0x06,0x99,
  0x9c,0x42,0x50,0xf4,0x91,0xef,0x98,0x7a,0x33,0x54,0x0b,0x43,0xed,0xcf,0xac,0x62,
  0xe4,0xb3,0x1c,0xa9,0xc9,0x08,0xe8,0x95,0x80,0xdf,0x94,0xfa,0x75,0x8f,0x3f,0xa6,
  0x47,0x07,0xa7,0xfc,0xf3,0x73,0x17,0xba,0x83,0x59,0x3c,0x19,0xe6,0x85,0x4f,0xa8,
  0x68,0x6b,0x81,0xb2,0x71,0x64,0xda,0x8b,0xf8,0xeb,0x0f,0x4b,0x70,0x56,0x9d,0x35,
  0x1e,0x24,0x0e,0x5e,0x63,0x58,0xd1,0xa2,0x25,0x22,0x7c,0x3b,0x01,0x21,0x78,0x87,
  0xd4,0x00,0x46,0x57,0x9f,0xd3,0x27,0x52,0x4c,0x36,0x02,0xe7,0xa0,0xc4,0xc8,0x9e,
  0xea,0xbf,0x8a,0xd2,0x40,0xc7,0x38,0xb5,0xa3,0xf7,0xf2,0xce,0xf9,0x61,0x15,0xa1,
  0xe0,0xae,0x5d,0xa4,0x9b,0x34,0x1a,0x55,0xad,0x93,0x32,0x30,0xf5,0x8c,0xb1,0xe3,
  0x1d,0xf6,0xe2,0x2e,0x82,0x66,0xca,0x60,0xc0,0x29,0x23,0xab,0x0d,0x53,0x4e,0x6f,
  0xd5,0xdb,0x37,0x45,0xde,0xfd,0x8e,0x2f,0x03,0xff,0x6a,0x72,0x6d,0x6c,0x5b,0x51,
  0x8d,0x1b,0xaf,0x92,0xbb,0xdd,0xbc,0x7f,0x11,0xd9,0x5c,0x41,0x1f,0x10,0x5a,0xd8,
  0x0a,0xc1,0x31,0x88,0xa5,0xcd,0x7b,0xbd,0x2d,0x74,0xd0,0x12,0xb8,0xe5,0xb4,0xb0,
  0x89,0x69,0x97,0x4a,0x0c,0x96,0x77,0x7e,0x65,0xb9,0xf1,0x09,0xc5,0x6e,0xc6,0x84,
  0x18,0xf0,0x7d,0xec,0x3a,0xdc,0x4d,0x20,0x79,0xee,0x5f,0x3e,0xd7,0xcb,0x39,0x48
];
const FK = [0xa3b1bac6,0x56aa3350,0x677d9197,0xb27022dc];
const CK = Array.from({length:32}, (_, i) => {
  let v = 0;
  for (let j = 0; j < 4; j++) v = (v << 8) | (((4 * i + j) * 7) & 255);
  return v;
});
const rotl = (x, n) => (x << n) | (x >>> (32 - n));
const tau = x => (SBOX[x >>> 24] << 24) | (SBOX[(x >>> 16) & 255] << 16)
  | (SBOX[(x >>> 8) & 255] << 8) | SBOX[x & 255];
const word = (a, p) => (a[p] << 24) | (a[p+1] << 16) | (a[p+2] << 8) | a[p+3];

function roundKeys(keyBytes) {
  const key = keyBytes;
  const k = FK.map((f, i) => word(key, 4 * i) ^ f);
  const rk = [];
  for (let i = 0; i < 32; i++) {
    const t = tau(k[i+1] ^ k[i+2] ^ k[i+3] ^ CK[i]);
    k.push(k[i] ^ t ^ rotl(t, 13) ^ rotl(t, 23));
    rk.push(k[i+4]);
  }
  return rk;
}

function block(input, offset, rk) {
  const x = [word(input, offset),word(input, offset+4),word(input, offset+8),word(input, offset+12)];
  for (let i = 0; i < 32; i++) {
    const t = tau(x[i+1] ^ x[i+2] ^ x[i+3] ^ rk[i]);
    x.push(x[i] ^ t ^ rotl(t,2) ^ rotl(t,10) ^ rotl(t,18) ^ rotl(t,24));
  }
  const out = [];
  for (let i = 35; i >= 32; i--) {
    out.push(x[i] >>> 24, (x[i] >>> 16) & 255, (x[i] >>> 8) & 255, x[i] & 255);
  }
  return out;
}

function parseMode(value) {
  // ASCII mode names only, no trimming, aliases explicitly documented.
  if (!/^[\x00-\x7f]*$/.test(value)) return null;
  const name = value.toUpperCase().replace(/-/g, '_');
  const match = /^(?:SM4_(?:128_)?)?(ECB|CBC|CFB|CFB128|OFB)$/.exec(name);
  return match ? (match[1] === 'CFB' ? 'CFB128' : match[1]) : null;
}

function crypt(data, key, iv, modeName, decrypt) {
  if (data == null || key == null || iv == null || modeName == null) return null;
  const mode = parseMode(modeName);
  if (!mode || key.length !== 16 || (mode !== 'ECB' && iv.length !== 16)) return null;
  const rk = roundKeys(key);
  const src = Array.from(data);
  let feedback = Array.from(iv);
  const out = [];
  if (mode === 'ECB' || mode === 'CBC') {
    if (decrypt) {
      if (src.length === 0 || src.length % 16 !== 0) return null;
      rk.reverse();
    } else {
      const p = 16 - src.length % 16;
      for (let i = 0; i < p; i++) src.push(p);
    }
    for (let offset = 0; offset < src.length; offset += 16) {
      let current = src.slice(offset, offset + 16);
      if (mode === 'CBC' && !decrypt) current = current.map((b, i) => b ^ feedback[i]);
      const result = block(current, 0, rk);
      if (mode === 'CBC') {
        if (decrypt) {
          for (let i = 0; i < 16; i++) result[i] ^= feedback[i];
          feedback = current;
        } else feedback = result;
      }
      for (const b of result) out.push(b);
    }
    if (decrypt) {
      const p = out[out.length - 1];
      if (p < 1 || p > 16) return null;
      for (let i = out.length - p; i < out.length; i++) if (out[i] !== p) return null;
      out.length -= p;
    }
  } else {
    // CFB128 and OFB use forward round keys in BOTH directions, with no padding.
    for (let offset = 0; offset < src.length; offset += 16) {
      const stream = block(feedback, 0, rk);
      const n = Math.min(16, src.length - offset);
      const result = [];
      for (let i = 0; i < n; i++) result.push(src[offset + i] ^ stream[i]);
      for (const b of result) out.push(b);
      feedback = mode === 'OFB' ? stream : (decrypt ? src.slice(offset, offset + 16) : result);
    }
  }
  return out;
}

export function sm4_encrypt_js(data, key, iv, mode) {
  return crypt(data, key, iv, mode, false);
}
export function sm4_decrypt_js(data, key, iv, mode) {
  return crypt(data, key, iv, mode, true);
}

// Database adapters: key/IV are original UTF-8 strings, NEVER auto-decoded Hex.
function utf8(value) {
  const out = [];
  for (const ch of value) {
    const p = ch.codePointAt(0);
    if (p < 0x80) out.push(p);
    else if (p < 0x800) out.push(0xc0 | (p >> 6), 0x80 | (p & 63));
    else if (p < 0x10000) out.push(0xe0 | (p >> 12), 0x80 | ((p >> 6) & 63), 0x80 | (p & 63));
    else out.push(0xf0 | (p >> 18), 0x80 | ((p >> 12) & 63), 0x80 | ((p >> 6) & 63), 0x80 | (p & 63));
  }
  return out;
}
function databaseCrypt(data, keyText, ivText, modeName, decrypt, defaultIV) {
  if (data == null || keyText == null || ivText == null || modeName == null) return null;
  const mode = parseMode(defaultIV && modeName === '' ? 'ECB' : modeName);
  if (!mode || (defaultIV && data.length === 0)) return null;
  const key = new Array(16).fill(0);
  const bytes = utf8(keyText);
  for (let i = 0; i < bytes.length; i++) key[i % 16] ^= bytes[i];
  let iv = [];
  if (mode !== 'ECB') {
    const raw = utf8(ivText);
    if (!defaultIV && raw.length < 16) return null;
    // Fixed default bytes; renaming the profile must not change ciphertexts.
    iv = defaultIV ? [68,79,82,73,83,68,79,82,73,83,68,79,82,73,83,95] : new Array(16).fill(0);
    for (let i = 0; i < Math.min(raw.length, 16); i++) iv[i] = raw[i];
  }
  return crypt(data, key, iv, mode, decrypt);
}
export function sm4_encrypt_default_iv_js(data, key, iv, mode) {
  return databaseCrypt(data, key, iv, mode, false, true);
}
export function sm4_decrypt_default_iv_js(data, key, iv, mode) {
  return databaseCrypt(data, key, iv, mode, true, true);
}
export function sm4_encrypt_explicit_iv_js(data, key, iv, mode) {
  return databaseCrypt(data, key, iv, mode, false, false);
}
export function sm4_decrypt_explicit_iv_js(data, key, iv, mode) {
  return databaseCrypt(data, key, iv, mode, true, false);
}
