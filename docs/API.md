# API contract (v0.1 draft)

The six STRICT byte API functions share `(BINARY NULL, BINARY NULL, BINARY NULL, STRING NULL) -> BINARY NULL`.
The function suffix (`js`, `wasm`, `python`) selects execution backend, not cipher semantics.

| Argument | Contract |
|---|---|
| `data` | Plaintext for encrypt, raw ciphertext for decrypt. Arbitrary bytes, not limited to UTF-8. |
| `key` | Exactly 16 bytes. No password KDF, folding, zero-fill or automatic hex decoding. |
| `iv` | Exactly 16 bytes for CBC/CFB128/OFB; any non-NULL length is accepted and ignored for ECB. |
| `mode` | Required ASCII identifier; no implicit default/session lookup. |

Canonical modes: `ECB`, `CBC`, `CFB128`, `OFB`.
Aliases: prepend `SM4_` or `SM4_128_`, substitute hyphens for underscores, use ASCII lower/upper case;
`CFB` is an alias of `CFB128`. Whitespace is not stripped. CTR, GCM and CFB8 are NOT implemented.
No mode should be inferred from data or IV length.

## Padding / length

- ECB/CBC encryption always appends PKCS#7 once. For length `n`, output length is `16 * (floor(n / 16) + 1)`.
- ECB/CBC decryption requires nonempty, 16-byte-aligned ciphertext and validates EVERY padding byte.
  It removes padding once. A correctly encrypted original plaintext ending with `01` or `02 02` is preserved.
- CFB128/OFB are unpadded, accept partial final blocks and have output length equal to input length.
- This is one-shot processing per SQL row: IV/feedback is reset for every row. It is not a cross-row stream.
- Empty plaintext encrypts to a full padding block in ECB/CBC and empty BINARY in CFB128/OFB.
- A valid padded ciphertext can decrypt to empty BINARY. Empty ciphertext is invalid for ECB/CBC.

## NULL and invalid input policy

All three backends return SQL NULL for:

1. any NULL argument (even the unused IV in ECB);
2. unsupported mode;
3. invalid key or required IV length;
4. invalid ECB/CBC ciphertext length or PKCS#7 padding.

This is an explicit **try-style contract despite the short `sm4_*` names**. It is not an implementation
of the error/NULL distinctions of every existing database. Count failures explicitly; do not silently
filter them away in ETL. Valid empty BINARY is not NULL.

The WASM export uses `Option<Vec<u8>>`, not a `Result` side error column. The contract does not rely
on a particular Databend host's business-error propagation. Runtime traps, resource exhaustion,
server/network failures, SQL conversion failures etc. may still fail the whole query; they are not
caught and turned into NULL. No panic is deliberately used as argument validation.

**A non-NULL result is not proof of key correctness or data authenticity**: CBC/ECB padding can
accidentally validate with a wrong key, and CFB/OFB have no padding to check.

## Explicit representations

| Source | SQL expression |
|---|---|
| UTF-8 text | `to_binary(text)` |
| Hex | `unhex(hex_text)` |
| Base64 | `from_base64(base64_text)` |
| Ciphertext display | `hex(binary_result)` / `to_base64(binary_result)` |
| Known UTF-8 plaintext display | `to_string(binary_result)` |

Conversion errors occur before calling the UDF and follow the SQL conversion function's behavior.
There is no `.strip()`, Base64/Hex guessing, implicit UTF-8 decoding or empty-string default key/IV.

## Database-style compatibility adapters

Separate names `sm4_encrypt_{default_iv,explicit_iv}_{js,wasm,python}` / `sm4_decrypt_{default_iv,explicit_iv}_{js,wasm,python}`
use `(BINARY,STRING,STRING,STRING)->BINARY`. Original UTF-8 key strings are zero-filled/XOR-folded;
IV rules are profile-specific. These are NOT the strict functions documented above.
Mode is explicit, output stays binary, and invalid inputs use the project's NULL policy rather than
emulating every original database error. See [COMPATIBILITY](COMPATIBILITY.md) for examples and limits.
No existing strict function is silently changed or replaced by deploying `compat_*.sql`.

## Deployment names

Public SQL names are `sm4_encrypt_js`, `sm4_decrypt_js`, `sm4_encrypt_wasm`, `sm4_decrypt_wasm`,
`sm4_encrypt_python`, `sm4_decrypt_python`. All handlers use the same respective names.
Suffixes avoid accidental name collisions and make benchmarking clear. A project owner may deploy
one backend under a preferred SQL name by changing only the CREATE FUNCTION name, not HANDLER.

Generated SQL uses `CREATE OR REPLACE`; review before deployment. This repository does NOT execute
DROP for old experimental names or replace functions on any instance unless you explicitly deploy.
