# Benchmark methodology

Run `scripts/benchmark.py` after deploying all six functions for the selected profile and starting the Python server.
The tool requires an explicit `SM4_URL`, creates a uniquely named Memory table, and drops it
on exit. It does not change server security settings, register functions or start a Databend node.

## Reproduce

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python scripts/benchmark.py --lengths 16,128,1024 \
  --rows 10000,30000,50000 --modes CBC --operations decrypt --repeats 3
```

Large Python runs may take tens of minutes; use tmux or an equivalent durable session.
Check that the URL targets an authorized test instance and that its resources are available.

For article-ready string-key conventions, deploy the corresponding adapter functions from
`sql/compat_*.sql` and add `--profile explicit_iv` or `--profile default_iv`. All backends then receive identical
original key/IV strings and perform the same normalization inside the timed UDF. No manual
pre-folding is performed. The default `--profile raw` retains the strict byte API.

## Measurement contract

- Same interface, key, IV and mode in all backends: `(BINARY,BINARY,BINARY,STRING)->BINARY` for raw;
  `(BINARY,STRING,STRING,STRING)->BINARY` for the selected database profile.
- No key schedule caching or asymmetric caller-side encoding shortcuts.
- Fixed settings: `max_threads` from the flag, `max_block_size=8192`, query result cache off.
- Per-row plaintexts vary. Dataset creation and encryption happen before timed queries.
  Preparation uses `sm4_encrypt_wasm`; independent algorithm validation is provided separately
  by the shared OpenSSL/document vectors, not by this preparation step alone.
- One warmup per workload, then formal rounds in deterministic randomized order, run sequentially.
- Count/hash consumes returned bytes, preventing unused-UDF elimination and full-result transfer.
- Every repetition must match the plaintext/ciphertext baseline checksums.
- Server time includes scan/hash, runtime creation/compilation, Arrow conversion and Python RPC.
- Data preparation and Python Server process startup are not included in timed queries.
- Results describe single-query latency, not concurrent QPS or pure SM4 kernel time.

## Output and completeness

The default `results/benchmark.json` is generated locally and ignored by Git. It contains:

- engine/environment settings and source SHA256 values;
- SQL, query_id, server/wall time and checksum per run;
- median, minimum, maximum and sample count per workload.

Formal sample counts must reach `--repeats`. `complete=true` is written only on success.
Do not publish a partial run as a completed benchmark. Review/redact results before attaching them
to an issue or release; use public test keys and synthetic data, not production data.

## Validation status

The benchmark runner has passed a 10-row CBC encrypt/decrypt smoke test across all three backends
for the raw, default_iv and explicit_iv profiles. This smoke test verifies runner behavior only.

The published performance snapshot covers **explicit_iv / CBC decryption / 16,128,1024 B**,
with one warmup and three formal repetitions per workload. The completed row counts are listed in
[REPORT.md](../reports/sm4-backends/REPORT.md), [results.csv](../reports/sm4-backends/results.csv) and
[results.json](../reports/sm4-backends/results.json). These files describe the same fully completed run and include
environment, source fingerprints and sanitized samples; they are not measurements of all modes/profiles.
All published reports are indexed in [reports/README.md](../reports/README.md).

To run the expanded 1k/10k/30k/50k report matrix on a dedicated test instance:

```bash
.venv/bin/python scripts/integration.py --benchmark-smoke --benchmark-report \
  --benchmark-report-rows 1000,10000,30000,50000
```

The expanded matrix has 144 timed queries (36 warmups and 108 formal repetitions) and can take tens
of minutes, mostly in the 1,024-byte Python cases. Run it in tmux. Partial records stay in ignored
`results/`; publish the report/CSV/JSON only after all repetitions and correctness checks finish.

Numbers from other interfaces, implementations or versions must not be re-labeled as this API's
results. Hardware, network, warehouse, block layout, engine/SDK version and concurrency may all
change the outcome. WASM initialization can dominate tiny queries; no backend is universally faster.
