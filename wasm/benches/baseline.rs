//! Frozen copy of wasm/src/lib.rs before the T-table optimization (commit f8d79b0).
//! Used only as the baseline in benches/micro.rs; do not modify.
#![allow(dead_code)]

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

#[inline]
fn tau(x: u32) -> u32 {
    u32::from_be_bytes(x.to_be_bytes().map(|v| SBOX[v as usize]))
}

fn round_keys(bytes: &[u8]) -> [u32; 32] {
    let key = bytes;
    let mut k: [u32; 4] = std::array::from_fn(|i|
        u32::from_be_bytes(key[i*4..i*4+4].try_into().unwrap()) ^ FK[i]);
    std::array::from_fn(|i| {
        let ck = u32::from_be_bytes(std::array::from_fn(|j| ((4*i+j)*7) as u8));
        let t = tau(k[1] ^ k[2] ^ k[3] ^ ck);
        let next = k[0] ^ t ^ t.rotate_left(13) ^ t.rotate_left(23);
        k = [k[1], k[2], k[3], next];
        next
    })
}

#[inline]
fn block(data: &[u8; 16], rk: &[u32; 32]) -> [u8; 16] {
    let mut x: [u32; 4] = std::array::from_fn(|i|
        u32::from_be_bytes(data[i*4..i*4+4].try_into().unwrap()));
    for &r in rk {
        let t = tau(x[1] ^ x[2] ^ x[3] ^ r);
        let next = x[0] ^ t ^ t.rotate_left(2) ^ t.rotate_left(10)
            ^ t.rotate_left(18) ^ t.rotate_left(24);
        x = [x[1], x[2], x[3], next];
    }
    let mut out = [0; 16];
    for i in 0..4 { out[i*4..i*4+4].copy_from_slice(&x[3-i].to_be_bytes()); }
    out
}

#[derive(Clone, Copy, PartialEq)]
enum Mode { Ecb, Cbc, Cfb, Ofb }
fn parse_mode(name: &str) -> Option<Mode> {
    if !name.is_ascii() { return None; }
    let normalized = name.to_ascii_uppercase().replace('-', "_");
    let suffix = normalized.strip_prefix("SM4_128_")
        .or_else(|| normalized.strip_prefix("SM4_")).unwrap_or(&normalized);
    match suffix {
        "ECB" => Some(Mode::Ecb), "CBC" => Some(Mode::Cbc),
        "CFB" | "CFB128" => Some(Mode::Cfb), "OFB" => Some(Mode::Ofb), _ => None,
    }
}

pub fn crypt(data: &[u8], key: &[u8], iv: &[u8], name: &str, decrypt: bool) -> Option<Vec<u8>> {
    let mode = parse_mode(name)?;
    if key.len() != 16 || (mode != Mode::Ecb && iv.len() != 16) { return None; }
    let mut rk = round_keys(key);
    let mut feedback = [0u8; 16];
    if mode != Mode::Ecb { feedback.copy_from_slice(iv); }
    let mut out = Vec::with_capacity(data.len() + 16);
    if mode == Mode::Ecb || mode == Mode::Cbc {
        let mut src = data.to_vec();
        if decrypt {
            if src.is_empty() || src.len() % 16 != 0 { return None; }
            rk.reverse();
        } else {
            let p = 16 - src.len() % 16;
            src.resize(src.len() + p, p as u8);
        }
        for chunk in src.chunks_exact(16) {
            let mut current: [u8; 16] = chunk.try_into().unwrap();
            if mode == Mode::Cbc && !decrypt {
                for i in 0..16 { current[i] ^= feedback[i]; }
            }
            let mut result = block(&current, &rk);
            if mode == Mode::Cbc {
                if decrypt {
                    for i in 0..16 { result[i] ^= feedback[i]; }
                    feedback = current;
                } else { feedback = result; }
            }
            out.extend_from_slice(&result);
        }
        if decrypt {
            let p = *out.last()? as usize;
            if !(1..=16).contains(&p) || !out[out.len()-p..].iter().all(|&b| b as usize == p) { return None; }
            out.truncate(out.len()-p);
        }
    } else {
        for chunk in data.chunks(16) {
            let stream = block(&feedback, &rk);
            let mut result = [0u8; 16];
            for i in 0..chunk.len() { result[i] = chunk[i] ^ stream[i]; }
            out.extend_from_slice(&result[..chunk.len()]);
            feedback = if mode == Mode::Ofb { stream } else if decrypt {
                let mut next = [0;16]; next[..chunk.len()].copy_from_slice(chunk); next
            } else { result };
        }
    }
    Some(out)
}


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
