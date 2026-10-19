-- Public examples use Hello Databend. All actual values must equal expected.
-- Run after deploying sql/compat_wasm.sql with the NEW adapter-enabled artifact.
SELECT 'Explicit IV / ECB' AS case_id,
  upper(hex(sm4_encrypt_explicit_iv_wasm('Hello Databend', '12312313123', '', 'sm4-ecb'))) AS actual,
  '742FDCD4D976A043AC7F7F451B62B50F' AS expected
UNION ALL
SELECT 'Explicit IV / CBC',
  upper(hex(sm4_encrypt_explicit_iv_wasm('Hello Databend', '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'sm4-cbc'))),
  '80ECC1CD2C248143DC470A7D5318EF15'
UNION ALL
SELECT 'Default IV / ECB',
  to_base64(sm4_encrypt_default_iv_wasm('Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '', 'SM4_128_ECB')),
  'XiHtWgw4l+/CdeiIsWBffQ=='
UNION ALL
SELECT 'Default IV / CBC / empty IV',
  to_base64(sm4_encrypt_default_iv_wasm('Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '', 'SM4_128_CBC')),
  'CIha6Y1QXx1CHWOwVa+iag=='
UNION ALL
SELECT 'Default IV / CBC / short IV',
  to_base64(sm4_encrypt_default_iv_wasm('Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '0123456789', 'SM4_128_CBC')),
  'rEY+tZnG98ar/CGWKTwk2Q=='
UNION ALL
SELECT 'Explicit IV / decrypt Hex',
  to_string(sm4_decrypt_explicit_iv_wasm(unhex('80ECC1CD2C248143DC470A7D5318EF15'), '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'sm4-cbc')),
  'Hello Databend'
UNION ALL
SELECT 'Default IV / decrypt Base64',
  to_string(sm4_decrypt_default_iv_wasm(from_base64('rEY+tZnG98ar/CGWKTwk2Q=='),
    'F3229A0B371ED2D9441B830D21A390C3', '0123456789', 'SM4_128_CBC')),
  'Hello Databend';
