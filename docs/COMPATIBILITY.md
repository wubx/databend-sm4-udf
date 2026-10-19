# 字符串参数入口

严格字节接口要求 key、IV 都是恰好 16 字节的 BINARY，调用方得自己处理编码。很多场景里 key 和 IV 本来就是普通字符串，为此项目另外提供了两组接受字符串参数的入口，规则参考了其他数据库常见的 SM4 函数行为。

**密文始终是 BINARY；key 和 IV 按原始 UTF-8 字节处理，看起来像 Hex 的 key 也不会被自动解码。**

## 函数与类型

每种实现都有下面四个函数，把 `_wasm` 换成 `_js` 或 `_python` 即可：

```sql
sm4_encrypt_default_iv_wasm(data, key_str, iv_str, mode)
sm4_decrypt_default_iv_wasm(data, key_str, iv_str, mode)
sm4_encrypt_explicit_iv_wasm(data, key_str, iv_str, mode)
sm4_decrypt_explicit_iv_wasm(data, key_str, iv_str, mode)
```

```text
(BINARY NULL, STRING NULL, STRING NULL, STRING NULL) -> BINARY NULL
```

明文可以直接传字符串，Databend 会自动转成 BINARY，也可以显式写 `to_binary()`。解密时如果手里的密文是 Hex 或 Base64 文本，先用 `unhex()` / `from_base64()` 转回来。

## 两种策略的区别

| 规则 | `default_iv` | `explicit_iv` |
|---|---|---|
| key | 取 UTF-8 字节，补零并循环 XOR 折叠成 16 字节 | 相同 |
| 32 个字符的 Hex 形式 key | 按 32 个字符的原文字节折叠，不做 Hex 解码 | 相同 |
| IV（ECB 以外） | 以固定值 `444F524953444F524953444F5249535F`（Hex）为底，用输入的前最多 16 字节覆盖；可以为空或较短 | 至少 16 字节，超出部分截断 |
| IV（ECB） | 忽略（但不能为 NULL） | 相同 |
| mode 为空字符串 | 按 ECB 处理 | 返回 NULL |
| data 为空 | 返回 NULL | 正常处理；ECB/CBC 加密得到一个 padding 块 |
| NULL 或非法参数 | 返回 NULL | 返回 NULL |

key 折叠的算法：`key16` 初始为 16 个零字节，对 key 的每个字节执行 `key16[i % 16] ^= key_utf8[i]`。

其他细节：

- key、IV 不做 trim；空 key 折叠后是 16 个零字节。非 ASCII 字符按 UTF-8 字节计算，截断也按字节进行。
- ECB/CBC 使用 PKCS#7 填充，CFB128/OFB 不填充。
- mode 接受 `CBC`、`sm4-cbc`、`SM4_128_CBC` 等写法，必须显式传入，不读取会话变量。
- 固定的默认 IV 和空 key 只是为了兼容，生产环境中的 IV 应按模式要求由业务生成。

## 安装

字符串参数入口需要包含新导出的 WASM 文件，或新版 Python Server。按各部署指南构建、上传或启动后执行：

```bash
python3 scripts/generate_sql.py
bendsql --query="$(<sql/compat_wasm.sql)"
bendsql --query="$(<sql/compat_js.sql)"
bendsql --query="$(<sql/compat_python.sql)"
```

每个文件注册 4 个函数，三端共 12 个。它们和严格接口互不影响，`sql/js.sql` 等文件里的 6 个严格函数规则不变。WASM 建议上传到新的版本化路径，再用 `--wasm-path @stage/file.wasm` 生成 SQL，具体见 [DEPLOY_WASM](DEPLOY_WASM.md)。

## 示例：显式 IV

```sql
SELECT upper(hex(sm4_encrypt_explicit_iv_wasm(
  'Hello Databend', '12312313123',
  'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'sm4-cbc'
))) AS ciphertext_hex;
-- 80ECC1CD2C248143DC470A7D5318EF15

SELECT to_string(sm4_decrypt_explicit_iv_wasm(
  unhex('80ECC1CD2C248143DC470A7D5318EF15'), '12312313123',
  'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'sm4-cbc'
)) AS plaintext;
-- Hello Databend
```

## 示例：默认 IV 和短 IV

这里的 key 虽然长得像 Hex，但它就是原文字符串，不要对它调用 `unhex()`：

```sql
-- 空 IV，使用默认值
SELECT to_base64(sm4_encrypt_default_iv_wasm(
  'Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '', 'SM4_128_CBC'
)) AS ciphertext_base64;
-- CIha6Y1QXx1CHWOwVa+iag==

-- 短 IV，覆盖默认值的前 10 字节
SELECT to_base64(sm4_encrypt_default_iv_wasm(
  'Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '0123456789', 'SM4_128_CBC'
)) AS ciphertext_base64;
-- rEY+tZnG98ar/CGWKTwk2Q==

SELECT to_string(sm4_decrypt_default_iv_wasm(
  from_base64('rEY+tZnG98ar/CGWKTwk2Q=='),
  'F3229A0B371ED2D9441B830D21A390C3', '0123456789', 'SM4_128_CBC'
)) AS plaintext;
-- Hello Databend
```

`tests/compat_smoke.sql` 包含 7 个类似用例，可以直接执行，每行的 `actual` 都应等于 `expected`。预期密文由 OpenSSL 独立计算。

## 与其他数据库的差异

- 非法参数统一返回 NULL，不模拟其他数据库的报错行为。
- 不支持可选参数和会话变量，也不模拟历史版本的特殊行为。
- 不支持 CTR、GCM、CFB8。
- 测试使用公开文档中的固定密文和 OpenSSL 输出比对，没有在其他数据库上实际运行。

## 参考资料

显式 IV 策略参考了以下公开文档；默认 IV 的规则和固定字节以上文为准。

- [OceanBase SM4_ENCRYPT](https://www.oceanbase.com/docs/common-oceanbase-database-ai-1000000006781744)
- [OceanBase SM4_DECRYPT](https://www.oceanbase.com/docs/common-oceanbase-database-ai-1000000006781762)
