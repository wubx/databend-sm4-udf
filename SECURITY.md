# Security / maturity

This is an experimental interoperability/performance project, not an audited cryptographic product.
No production security assurance, regulatory compliance, constant-time behavior or secure memory
erasure is claimed. JS/Rust use scalar S-box lookup tables; Python uses gmssl's scalar block primitive.

- ECB/CBC/CFB128/OFB have no built-in authentication. Add an appropriate authenticated construction
  at the application/protocol layer or use an audited AEAD implementation when designing a new system.
  GCM/AEAD is not implemented here. Do not improvise a new scheme from these functions.
- ECB leaks equal plaintext blocks. Do not choose it for new confidential data simply because it needs no IV.
- Follow each mode's IV requirements; generate/manage appropriate per-message IVs outside the UDF.
  Fixed IVs in examples/benchmarks are for reproducibility only. Never reuse published test keys.
- Invalid input returns NULL deliberately. Check/count failures; SQL NULL is not an authentication signal.
- Do not put real secrets in Git, public SQL logs, benchmark results, workflow artifacts or query text
  unless your deployment's key handling and query logging controls are appropriate.
- Python server defaults to plaintext loopback. The pinned SDK does not expose a usable native TLS
  listener through this CLI. Remote operation requires an independently configured TLS gateway or
  protected network plus trust, Databend allowlists, firewalls and access control. Gateway behavior
  is not tested here. Do not expose this plaintext demo publicly or disable production checks.
- UDF runtime/network/resource failures can still fail queries. Resource limits and concurrency
  limits must be handled by the deployment. No unbounded key cache is maintained by these functions.
- Reporting/deployment tooling is experimental too. Live test scripts create temporary objects and
  attempt cleanup in finally; inspect the recorded cleanup errors after interruption/failure.

Before publication the repository owner must choose a vulnerability reporting contact/channel.
Do not open a public issue containing sensitive keys, plaintext or production credentials.
