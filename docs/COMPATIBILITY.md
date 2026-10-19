# 字符串 key/IV 入口

项目在严格字节接口之外提供两组中性命名的字符串参数策略，公开演示统一使用 `Hello Databend`。
**密文始终是二进制；key、IV 接受原始 UTF-8 字符串，绝不自动将看起来像 Hex 的 key 解码。**

## 函数名和类型

每种实现均提供以下函数；把 `_wasm` 换成 `_js` 或 `_python` 即可：

```sql
sm4_encrypt_default_iv_wasm(data, key_str, iv_str, mode)
sm4_decrypt_default_iv_wasm(data, key_str, iv_str, mode)
sm4_encrypt_explicit_iv_wasm(data, key_str, iv_str, mode)
sm4_decrypt_explicit_iv_wasm(data, key_str, iv_str, mode)
```

```text
(BINARY NULL, STRING NULL, STRING NULL, STRING NULL) -> BINARY NULL
```

字符串明文可直接传入，Databend 会将其转换为 BINARY；也可显式使用 `to_binary()`。
解密输入若是 Hex/Base64 文本，仍需 `unhex()` / `from_base64()`。
客户端将 BINARY 显示为 Hex 不等于又加密了一次，也不代表输出类型变成 STRING。

## 参数规则

| 规则 | `default_iv` | `explicit_iv` |
|---|---|---|
| key | UTF-8 原文字节，补零/循环 XOR 成 16 字节 | 相同 |
| 32 个 Hex 字符形式的 key | 按 32 个原文字节折叠，不 Hex 解码 | 相同 |
| 非 ECB 的 IV | 固定底串 `444F524953444F524953444F5249535F`（Hex），输入字节覆盖前最多 16 字节 | 输入至少 16 字节，超过部分截断 |
| ECB 的 IV | 忽略非 NULL IV | 相同 |
| mode 为空字符串 | ECB | NULL |
| 空 data | NULL | 按模式正常处理；ECB/CBC 加密产生 padding 块 |
| NULL / 非法参数 | NULL | NULL |

两个策略不仅 IV 规则不同，空 mode 和空 data 的历史兼容约定也不同；名字不是全部规则的替代。
不对 key/IV 做 trim；空 key 变成全零 16 字节。非 ASCII 参数按 UTF-8 字节处理，截断按字节进行。
固定默认 IV、空 key 都只是兼容行为，不代表安全的生产加密策略。

ECB/CBC 使用一次 PKCS#7，CFB128/OFB 不填充。mode 支持 `CBC`、`sm4-cbc`、`SM4_128_CBC` 等项目定义的别名。
密钥折叠的定义：`key16[i % 16] ^= key_utf8[i]`，初始 `key16` 全零。

## 安装

按 README 构建、上传**包含新函数导出的 WASM 工件**，或启动新版 Python Server，然后执行：

```bash
python3 scripts/generate_sql.py
bendsql --query="$(<sql/compat_wasm.sql)"
bendsql --query="$(<sql/compat_js.sql)"
bendsql --query="$(<sql/compat_python.sql)"
```

每个文件注册 4 个函数，共 12 个；原 `sql/js.sql` 等 6 个严格字节函数仍保持原规则。
建议将新 WASM 上传到独立版本路径，通过 `--wasm-path @stage/file.wasm` 生成 SQL。
旧工件没有新导出，不能只注册函数名而不上传新版；不要原地覆盖仍被其他函数引用的旧工件。

## 演示：显式 IV

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

## 演示：默认和短 IV

key 虽然看起来像 Hex，仍是原文字符串，不对它调用 `unhex()`：

```sql
SELECT to_base64(sm4_encrypt_default_iv_wasm(
  'Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '', 'SM4_128_CBC'
)) AS ciphertext_base64;
-- CIha6Y1QXx1CHWOwVa+iag==

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

可直接执行 `tests/compat_smoke.sql`：7 行 actual 都必须等于 expected。
内部仍保留既有固定向量，新增 `Hello Databend` 用例使用独立 OpenSSL 计算并锁定的预期密文。
仅改函数/场景名不会改变默认 IV 字节或已有密文结果。

## 边界与来源

- 这是一套明确的参数适配规则，不是完整仿真其他数据库的 SQL 行为或全版本认证。
- mode 始终显式传入，不读取会话变量，不模拟可选参数和历史版本问题。
- 非法参数统一 NULL，不能声称与外部数据库的错误语义完全一致。
- 不提供 CTR/GCM/CFB8；STRING/BINARY、字符编码和客户端显示需单独理解。
- `sm4_encrypt_wasm` 等严格接口仍要求实际 16 字节 key/IV，不自动使用本页规则。
- 没有连接实际外部数据库服务。测试参考包括公开文档的固定密文及独立 OpenSSL 输出；文章不得写成在线跨库认证。

## References

以下仅列出显式 IV 策略的公开参考资料；不表示其中的来源定义了本项目全部策略。
默认 IV 的完整行为和固定字节已在上文明确约定。函数名、测试标签和演示结果不使用来源产品名。

- [OceanBase SM4_ENCRYPT](https://www.oceanbase.com/docs/common-oceanbase-database-ai-1000000006781744)
- [OceanBase SM4_DECRYPT](https://www.oceanbase.com/docs/common-oceanbase-database-ai-1000000006781762)
