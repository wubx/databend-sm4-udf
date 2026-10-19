//! SM4 with explicit byte parameters; see docs/API.md for the shared contract.
use arrow_udf::function;

const SBOX: [u8; 256] = [
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
    0x18,0xf0,0x7d,0xec,0x3a,0xdc,0x4d,0x20,0x79,0xee,0x5f,0x3e,0xd7,0xcb,0x39,0x48,
];
const FK: [u32; 4] = [0xa3b1bac6,0x56aa3350,0x677d9197,0xb27022dc];

/// CK[i] bytes are (4i+j)*7 mod 256 (GB/T 32907).
const CK: [u32; 32] = {
    let mut ck = [0u32; 32];
    let mut i = 0;
    while i < 32 {
        let mut j = 0;
        while j < 4 { ck[i] = (ck[i] << 8) | (((4 * i + j) * 7) % 256) as u32; j += 1; }
        i += 1;
    }
    ck
};

const fn linear(b: u32) -> u32 {
    b ^ b.rotate_left(2) ^ b.rotate_left(10) ^ b.rotate_left(18) ^ b.rotate_left(24)
}

/// T tables merge the S-box and the round linear transform L: T[k][x] = L(SBOX[x] << (24 - 8k)).
/// Because L commutes with rotation, each table is the first one rotated right by 8k bits.
const T: [[u32; 256]; 4] = {
    let mut t = [[0u32; 256]; 4];
    let mut x = 0;
    while x < 256 {
        let v = linear((SBOX[x] as u32) << 24);
        t[0][x] = v;
        t[1][x] = v.rotate_right(8);
        t[2][x] = v.rotate_right(16);
        t[3][x] = v.rotate_right(24);
        x += 1;
    }
    t
};

/// One encryption round: L(tau(x)) using four table lookups.
#[inline(always)]
fn round(x: u32) -> u32 {
    T[0][(x >> 24) as u8 as usize] ^ T[1][(x >> 16) as u8 as usize]
        ^ T[2][(x >> 8) as u8 as usize] ^ T[3][x as u8 as usize]
}

/// Key-schedule substitution; runs once per row, so it keeps the plain S-box.
fn tau(x: u32) -> u32 {
    u32::from_be_bytes(x.to_be_bytes().map(|v| SBOX[v as usize]))
}

fn round_keys(key: &[u8; 16]) -> [u32; 32] {
    let mut k: [u32; 4] = std::array::from_fn(|i|
        u32::from_be_bytes(key[i*4..i*4+4].try_into().unwrap()) ^ FK[i]);
    std::array::from_fn(|i| {
        let t = tau(k[1] ^ k[2] ^ k[3] ^ CK[i]);
        let next = k[0] ^ t ^ t.rotate_left(13) ^ t.rotate_left(23);
        k = [k[1], k[2], k[3], next];
        next
    })
}

/// 32 rounds, unrolled by four so the state words never shift.
#[inline]
fn block(data: &[u8; 16], rk: &[u32; 32]) -> [u8; 16] {
    let word = |i: usize| u32::from_be_bytes([data[4*i], data[4*i+1], data[4*i+2], data[4*i+3]]);
    let (mut x0, mut x1, mut x2, mut x3) = (word(0), word(1), word(2), word(3));
    for r in rk.chunks_exact(4) {
        x0 ^= round(x1 ^ x2 ^ x3 ^ r[0]);
        x1 ^= round(x2 ^ x3 ^ x0 ^ r[1]);
        x2 ^= round(x3 ^ x0 ^ x1 ^ r[2]);
        x3 ^= round(x0 ^ x1 ^ x2 ^ r[3]);
    }
    let mut out = [0; 16];
    for (i, x) in [x3, x2, x1, x0].iter().enumerate() { out[i*4..i*4+4].copy_from_slice(&x.to_be_bytes()); }
    out
}

#[inline(always)]
fn xor(a: &mut [u8; 16], b: &[u8; 16]) {
    for i in 0..16 { a[i] ^= b[i]; }
}

#[derive(Clone, Copy, PartialEq)]
enum Mode { Ecb, Cbc, Cfb, Ofb }

/// ASCII case-insensitive prefix match where '-' equals '_'; `pattern` is upper case with '_'.
fn starts_with_mode(name: &[u8], pattern: &[u8]) -> bool {
    name.len() >= pattern.len() && name.iter().zip(pattern).all(|(&c, &p)|
        (if c == b'-' { b'_' } else { c.to_ascii_uppercase() }) == p)
}

/// Same rules as before (optional SM4_ / SM4_128_ prefix), without allocating per row.
fn parse_mode(name: &str) -> Option<Mode> {
    if !name.is_ascii() { return None; }
    let name = name.as_bytes();
    let suffix = if starts_with_mode(name, b"SM4_128_") { &name[8..] }
        else if starts_with_mode(name, b"SM4_") { &name[4..] } else { name };
    let is = |pattern: &[u8]| suffix.len() == pattern.len() && starts_with_mode(suffix, pattern);
    if is(b"ECB") { Some(Mode::Ecb) } else if is(b"CBC") { Some(Mode::Cbc) }
    else if is(b"CFB") || is(b"CFB128") { Some(Mode::Cfb) } else if is(b"OFB") { Some(Mode::Ofb) }
    else { None }
}

/// Strict byte interface. Public only so `benches/micro.rs` can call it natively.
#[doc(hidden)]
pub fn crypt(data: &[u8], key: &[u8], iv: &[u8], name: &str, decrypt: bool) -> Option<Vec<u8>> {
    let mode = parse_mode(name)?;
    let key: &[u8; 16] = key.try_into().ok()?;
    let mut feedback = [0u8; 16];
    if mode != Mode::Ecb { feedback = iv.try_into().ok()?; }
    let mut rk = round_keys(key);
    match mode {
        Mode::Ecb | Mode::Cbc if decrypt => {
            if data.is_empty() || data.len() % 16 != 0 { return None; }
            rk.reverse();
            let mut out = Vec::with_capacity(data.len());
            for chunk in data.chunks_exact(16) {
                let current: [u8; 16] = chunk.try_into().unwrap();
                let mut result = block(&current, &rk);
                if mode == Mode::Cbc { xor(&mut result, &feedback); feedback = current; }
                out.extend_from_slice(&result);
            }
            let p = *out.last()? as usize;
            if !(1..=16).contains(&p) || !out[out.len()-p..].iter().all(|&b| b as usize == p) { return None; }
            out.truncate(out.len() - p);
            Some(out)
        }
        Mode::Ecb | Mode::Cbc => {
            // Pad only the final block instead of copying the whole input.
            let full = data.len() / 16 * 16;
            let mut last = [(16 - data.len() % 16) as u8; 16];
            last[..data.len() - full].copy_from_slice(&data[full..]);
            let mut out = Vec::with_capacity(full + 16);
            for chunk in data[..full].chunks_exact(16).chain(std::iter::once(&last[..])) {
                let mut current: [u8; 16] = chunk.try_into().unwrap();
                if mode == Mode::Cbc { xor(&mut current, &feedback); }
                let result = block(&current, &rk);
                if mode == Mode::Cbc { feedback = result; }
                out.extend_from_slice(&result);
            }
            Some(out)
        }
        Mode::Cfb | Mode::Ofb => {
            let mut out = Vec::with_capacity(data.len());
            for chunk in data.chunks(16) {
                let stream = block(&feedback, &rk);
                let mut result = [0u8; 16];
                for i in 0..chunk.len() { result[i] = chunk[i] ^ stream[i]; }
                out.extend_from_slice(&result[..chunk.len()]);
                feedback = if mode == Mode::Ofb { stream } else if decrypt {
                    let mut next = [0; 16]; next[..chunk.len()].copy_from_slice(chunk); next
                } else { result };
            }
            Some(out)
        }
    }
}

// Use Option, not Result's side error column: invalid arguments explicitly return NULL.
// Arrow SDK skips NULL input rows for these non-Option parameter signatures.
#[function("sm4_encrypt_wasm(largebinary,largebinary,largebinary,string)->largebinary")]
fn sm4_encrypt_wasm(data: &[u8], key: &[u8], iv: &[u8], mode: &str) -> Option<Vec<u8>> {
    crypt(data, key, iv, mode, false)
}
#[function("sm4_decrypt_wasm(largebinary,largebinary,largebinary,string)->largebinary")]
fn sm4_decrypt_wasm(data: &[u8], key: &[u8], iv: &[u8], mode: &str) -> Option<Vec<u8>> {
    crypt(data, key, iv, mode, true)
}

/// String-parameter interface (see docs/COMPATIBILITY.md). Public only for `benches/micro.rs`.
#[doc(hidden)]
pub fn database_crypt(data: &[u8], key: &str, iv: &str, name: &str, decrypt: bool, default_iv: bool) -> Option<Vec<u8>> {
    let name = if default_iv && name.is_empty() { "ECB" } else { name };
    let mode = parse_mode(name)?;
    if default_iv && data.is_empty() { return None; }
    let mut folded = [0u8; 16];
    for (i, b) in key.as_bytes().iter().enumerate() { folded[i % 16] ^= b; }
    let mut vector = [68,79,82,73,83,68,79,82,73,83,68,79,82,73,83,95];
    if mode != Mode::Ecb {
        if !default_iv && iv.len() < 16 { return None; }
        let n = iv.len().min(16);
        vector[..n].copy_from_slice(&iv.as_bytes()[..n]);
    }
    crypt(data, &folded, if mode == Mode::Ecb { &[] } else { &vector }, name, decrypt)
}

#[function("sm4_encrypt_default_iv_wasm(largebinary,string,string,string)->largebinary")]
fn sm4_encrypt_default_iv_wasm(data: &[u8], key: &str, iv: &str, mode: &str) -> Option<Vec<u8>> {
    database_crypt(data, key, iv, mode, false, true)
}
#[function("sm4_decrypt_default_iv_wasm(largebinary,string,string,string)->largebinary")]
fn sm4_decrypt_default_iv_wasm(data: &[u8], key: &str, iv: &str, mode: &str) -> Option<Vec<u8>> {
    database_crypt(data, key, iv, mode, true, true)
}
#[function("sm4_encrypt_explicit_iv_wasm(largebinary,string,string,string)->largebinary")]
fn sm4_encrypt_explicit_iv_wasm(data: &[u8], key: &str, iv: &str, mode: &str) -> Option<Vec<u8>> {
    database_crypt(data, key, iv, mode, false, false)
}
#[function("sm4_decrypt_explicit_iv_wasm(largebinary,string,string,string)->largebinary")]
fn sm4_decrypt_explicit_iv_wasm(data: &[u8], key: &str, iv: &str, mode: &str) -> Option<Vec<u8>> {
    database_crypt(data, key, iv, mode, true, false)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn bytes(v: &serde_json::Value) -> Option<Vec<u8>> {
        v.as_str().map(|s| (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i+2],16).unwrap()).collect())
    }
    #[test]
    fn database_vectors() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!("../../tests/compat_vectors.json")).unwrap();
        for v in fixture["cases"].as_array().unwrap() {
            let actual = match (bytes(&v["data"]),v["key"].as_str(),v["iv"].as_str(),v["mode"].as_str()) {
                (Some(d),Some(k),Some(i),Some(m)) => database_crypt(&d,k,i,m,v["operation"]=="decrypt",v["profile"]=="default_iv"),
                _ => None,
            };
            assert_eq!(actual, bytes(&v["expected"]), "{}", v["id"]);
        }
    }
    #[test]
    fn shared_vectors() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!("../../tests/vectors.json")).unwrap();
        for v in fixture["cases"].as_array().unwrap() {
            let data = bytes(&v["data"]); let key = bytes(&v["key"]); let iv = bytes(&v["iv"]);
            let actual = match (data, key, iv, v["mode"].as_str()) {
                (Some(d),Some(k),Some(i),Some(m)) => crypt(&d,&k,&i,m,v["operation"]=="decrypt"),
                _ => None,
            };
            assert_eq!(actual, bytes(&v["expected"]), "{}", v["id"]);
        }
    }
}
