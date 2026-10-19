-- Read-only WASM deployment regression. All rows must equal the expected pair.
-- Expected ciphertext_hex: DA12F33F321D4D551A76D8800F5AE244
-- Expected plaintext_hex:  48656C6C6F204461746162656E64
-- NULL is a failure, not a valid encryption result for these inputs.

SELECT
  upper(hex(sm4_encrypt_wasm(to_binary('Hello Databend'), unhex('0123456789abcdeffedcba9876543210'), unhex('00112233445566778899aabbccddeeff'), 'CBC'))) AS ciphertext_hex,
  upper(hex(sm4_decrypt_wasm(unhex('DA12F33F321D4D551A76D8800F5AE244'), unhex('0123456789abcdeffedcba9876543210'), unhex('00112233445566778899aabbccddeeff'), 'CBC'))) AS plaintext_hex;

SELECT
  upper(hex(sm4_encrypt_wasm(to_binary('Hello Databend'), unhex('0123456789abcdeffedcba9876543210'), unhex('00112233445566778899aabbccddeeff'), 'sm4-cbc'))) AS ciphertext_hex,
  upper(hex(sm4_decrypt_wasm(unhex('DA12F33F321D4D551A76D8800F5AE244'), unhex('0123456789abcdeffedcba9876543210'), unhex('00112233445566778899aabbccddeeff'), 'sm4-cbc'))) AS plaintext_hex;

SELECT
  upper(hex(sm4_encrypt_wasm(to_binary('Hello Databend'), unhex('0123456789abcdeffedcba9876543210'), unhex('00112233445566778899aabbccddeeff'), 'SM4_128_CBC'))) AS ciphertext_hex,
  upper(hex(sm4_decrypt_wasm(unhex('DA12F33F321D4D551A76D8800F5AE244'), unhex('0123456789abcdeffedcba9876543210'), unhex('00112233445566778899aabbccddeeff'), 'SM4_128_CBC'))) AS plaintext_hex;
