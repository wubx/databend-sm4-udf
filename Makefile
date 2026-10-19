PYTHON ?= python3

.PHONY: sql vectors test wasm
sql:
	$(PYTHON) scripts/generate_sql.py
vectors:
	node tests/generate_vectors.mjs
	node tests/generate_compat_vectors.mjs
test:
	PYTHONPATH=python $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
	node tests/test_js.mjs
	node tests/test_compat.mjs
	cargo test --locked --manifest-path wasm/Cargo.toml
wasm:
	cargo build --locked --release --target wasm32-wasip1 --manifest-path wasm/Cargo.toml
