//! MD5 solely for a native-vs-WASM execution-path benchmark, not security use.
use arrow_udf::function;
use md5::{Digest, Md5};

#[function("md5_wasm(string)->string")]
fn md5_wasm(value: &str) -> String {
    let digest = Md5::digest(value.as_bytes());
    // The native function also emits lowercase hexadecimal. Avoid format! overhead.
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = [0u8; 32];
    for (i, b) in digest.iter().enumerate() {
        out[2 * i] = HEX[(b >> 4) as usize];
        out[2 * i + 1] = HEX[(b & 15) as usize];
    }
    String::from_utf8(out.to_vec()).unwrap()
}

#[function("identity_wasm(string)->string")]
fn identity_wasm(value: &str) -> &str { value }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn published_md5_vectors() {
        for (data, expected) in [
            ("", "d41d8cd98f00b204e9800998ecf8427e"),
            ("a", "0cc175b9c0f1b6a831c399e269772661"),
            ("abc", "900150983cd24fb0d6963f7d28e17f72"),
            ("message digest", "f96b697d7cb7938d525a2f31aaf161d0"),
        ] { assert_eq!(md5_wasm(data), expected); }
    }
    #[test]
    fn identity_preserves_unicode_and_null_byte() {
        assert_eq!(identity_wasm("Hello Databend 中文🙂\0"), "Hello Databend 中文🙂\0");
    }
}
