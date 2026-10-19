//! Micro-benchmark: current `wasm/src/lib.rs` vs. the frozen pre-optimization copy in `baseline.rs`.
//!
//! Calls the row function in a loop, the same way the Arrow UDF wrapper calls it once per row,
//! so each sample includes per-row key expansion, mode parsing and the returned `Vec` allocation.
//! It does not include Databend: no Arrow conversion, runtime creation or SQL execution.
//!
//! Native:  cargo bench --locked --manifest-path wasm/Cargo.toml --bench micro
//! WASM:    CARGO_TARGET_WASM32_WASIP1_RUNNER=wasmtime \
//!          cargo bench --locked --manifest-path wasm/Cargo.toml --bench micro --target wasm32-wasip1
//! Quick:   append `-- --quick` (fewer rows and samples, for smoke checks only).
#[path = "baseline.rs"]
mod baseline;

use databend_sm4_udf::{crypt, database_crypt};
use std::hint::black_box;
use std::time::Instant;

const KEY: [u8; 16] = *b"\x01\x23\x45\x67\x89\xab\xcd\xef\xfe\xdc\xba\x98\x76\x54\x32\x10";
const IV: [u8; 16] = *b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff";
// Same string key/IV as the published explicit_iv report.
const KEY_TEXT: &str = "12312313123";
const IV_TEXT: &str = "asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj";

#[derive(Clone, Copy)]
enum Api { Strict, ExplicitIv }

struct Workload { api: Api, mode: &'static str, decrypt: bool, length: usize }

type RowFn = fn(Api, &[u8], &str, bool) -> Option<Vec<u8>>;

fn optimized(api: Api, data: &[u8], mode: &str, decrypt: bool) -> Option<Vec<u8>> {
    match api {
        Api::Strict => crypt(data, &KEY, &IV, mode, decrypt),
        Api::ExplicitIv => database_crypt(data, KEY_TEXT, IV_TEXT, mode, decrypt, false),
    }
}

fn original(api: Api, data: &[u8], mode: &str, decrypt: bool) -> Option<Vec<u8>> {
    match api {
        Api::Strict => baseline::crypt(data, &KEY, &IV, mode, decrypt),
        Api::ExplicitIv => baseline::database_crypt(data, KEY_TEXT, IV_TEXT, mode, decrypt, false),
    }
}

/// Deterministic, distinct rows (xorshift), so every row differs like the SQL benchmark.
fn plaintexts(length: usize, rows: usize) -> Vec<Vec<u8>> {
    let mut state = 0x9e37_79b9_7f4a_7c15u64;
    (0..rows).map(|_| (0..length).map(|_| {
        state ^= state << 13; state ^= state >> 7; state ^= state << 17; state as u8
    }).collect()).collect()
}

/// Encryption inputs are plaintexts; decryption inputs are ciphertexts prepared untimed.
fn inputs(w: &Workload, rows: usize) -> Vec<Vec<u8>> {
    let plain = plaintexts(w.length, rows);
    if !w.decrypt { return plain; }
    plain.iter().map(|p| original(w.api, p, w.mode, false).unwrap()).collect()
}

/// Median nanoseconds per row over `samples` timed passes after one warm-up pass.
fn measure(f: RowFn, w: &Workload, rows: &[Vec<u8>], samples: usize) -> f64 {
    let pass = || {
        let start = Instant::now();
        let mut checksum = 0usize;
        for row in rows {
            checksum += black_box(f(w.api, black_box(row), w.mode, w.decrypt)).map_or(0, |v| v.len());
        }
        black_box(checksum);
        start.elapsed().as_nanos() as f64 / rows.len() as f64
    };
    pass();
    let mut times: Vec<f64> = (0..samples).map(|_| pass()).collect();
    times.sort_by(|a, b| a.partial_cmp(b).unwrap());
    times[samples / 2]
}

/// Byte-for-byte equivalence before anything is timed: both APIs, valid and invalid modes,
/// every length 0..=80 plus a few larger ones, encrypting random data and decrypting both
/// real ciphertexts and random bytes (mostly invalid padding).
fn check_equivalence() -> usize {
    let mut checked = 0;
    let modes = ["ECB", "CBC", "CFB128", "OFB", "sm4-cbc", "SM4_128_ofb", "cfb", "SM4_SM4_CBC", "SM4-CTR", "", "CBC "];
    let mut compare = |api: Api, data: &[u8], mode: &str, decrypt: bool| {
        assert_eq!(optimized(api, data, mode, decrypt), original(api, data, mode, decrypt),
            "mismatch: mode={mode:?} length={} decrypt={decrypt}", data.len());
        checked += 1;
    };
    for api in [Api::Strict, Api::ExplicitIv] {
        for mode in modes {
            for length in (0..=80).chain([255, 1024, 1025]) {
                for data in plaintexts(length, 3) {
                    compare(api, &data, mode, false);
                    compare(api, &data, mode, true);
                    if let Some(cipher) = original(api, &data, mode, false) { compare(api, &cipher, mode, true); }
                }
            }
        }
    }
    checked
}

fn main() {
    let quick = std::env::args().any(|a| a == "--quick");
    let samples = if quick { 3 } else { 9 };
    let budget = if quick { 1 << 20 } else { 16 << 20 }; // plaintext bytes per pass
    println!("Equivalence: {} comparisons identical to baseline", check_equivalence());
    println!("Target: {}  samples: {samples}  bytes/pass: ~{} MiB\n",
        if cfg!(target_family = "wasm") { "wasm32-wasip1" } else { std::env::consts::ARCH }, budget >> 20);

    let mut workloads: Vec<Workload> = [16, 128, 1024].into_iter()
        .map(|length| Workload { api: Api::ExplicitIv, mode: "CBC", decrypt: true, length }).collect();
    for (mode, decrypt) in [("ECB", false), ("ECB", true), ("CBC", false), ("CBC", true),
                            ("CFB128", false), ("CFB128", true), ("OFB", false)] {
        workloads.push(Workload { api: Api::Strict, mode, decrypt, length: 1024 });
    }

    println!("| API | mode | op | B/row | rows | baseline ns/row | optimized ns/row | baseline MiB/s | optimized MiB/s | speedup |");
    println!("|---|---|---|---:|---:|---:|---:|---:|---:|---:|");
    for w in &workloads {
        let count = (budget / w.length.max(64)).max(1000);
        let rows = inputs(w, count);
        let before = measure(original, w, &rows, samples);
        let after = measure(optimized, w, &rows, samples);
        let mib = |ns: f64| w.length as f64 / ns * 1e9 / (1 << 20) as f64;
        println!("| {} | {} | {} | {} | {} | {:.0} | {:.0} | {:.1} | {:.1} | {:.2}× |",
            match w.api { Api::Strict => "strict", Api::ExplicitIv => "explicit_iv" },
            w.mode, if w.decrypt { "decrypt" } else { "encrypt" }, w.length, count,
            before, after, mib(before), mib(after), before / after);
    }
}
