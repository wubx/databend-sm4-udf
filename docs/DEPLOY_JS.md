# 部署 JavaScript UDF

```text
SQL → Databend Query → 内置 JS 运行时（QuickJS）→ SM4 → BINARY 结果
```

JS 代码通过 `CREATE FUNCTION ... AS $$...$$` 直接内联在 SQL 里，不需要起额外服务，Databend 节点上也不用装 Node.js。源码没有任何 npm 依赖。

需要准备：bendsql，以及支持 JavaScript UDF 的 Databend。权限、备份和接口选择先看 [部署总览](DEPLOYMENT.md)。

## 1. 注册函数

仓库里已经有生成好的 SQL，可以直接执行：

```bash
bendsql --query="$(<sql/js.sql)"          # 严格接口，2 个函数
bendsql --query="$(<sql/compat_js.sql)"   # 字符串参数入口，4 个函数（可选）
```

`$(<file)` 是 Bash 语法，作用是读入文件内容。

如果修改了 `javascript/sm4.mjs`，先重新生成 SQL：

```bash
python3 scripts/generate_sql.py           # 重新生成
python3 scripts/generate_sql.py --check   # 检查 SQL 与源码一致
```

## 2. 验证严格接口

```sql
SELECT upper(hex(sm4_encrypt_js(
    to_binary('Hello Databend'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
))) AS ciphertext_hex;
-- DA12F33F321D4D551A76D8800F5AE244

SELECT to_string(sm4_decrypt_js(
    unhex('DA12F33F321D4D551A76D8800F5AE244'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
)) AS plaintext;
-- Hello Databend
```

也可以运行只读检查（需先配置 `SM4_URL` 等变量）：

```bash
.venv/bin/python scripts/check_deployment.py --impl js
```

## 3. 验证字符串参数入口

```sql
SELECT upper(hex(sm4_encrypt_explicit_iv_js(
    'Hello Databend', '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'CBC'
))) AS ciphertext_hex;
-- 80ECC1CD2C248143DC470A7D5318EF15

SELECT to_string(sm4_decrypt_explicit_iv_js(
    unhex('80ECC1CD2C248143DC470A7D5318EF15'), '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'CBC'
)) AS plaintext;
-- Hello Databend
```

默认 IV 策略使用 `sm4_encrypt_default_iv_js` / `sm4_decrypt_default_iv_js`，规则见 [COMPATIBILITY](COMPATIBILITY.md)。

## 4. 升级与回滚

1. 本地跑测试：`node tests/test_js.mjs`、`node tests/test_compat.mjs`。需要支持 SM4 的 Node/OpenSSL，它们只用于测试。
2. 重新生成 SQL，审阅改动，保存本次要执行的 `js.sql` / `compat_js.sql`。
3. 在目标实例执行，然后做只读检查，并用业务样本验证。
4. 出问题时，重新执行**上一次部署时保存的 SQL**。不要用已经改过的源码重新生成“旧版本”。

## 5. 常见问题

| 现象 | 排查方向 |
|---|---|
| 不识别 `LANGUAGE javascript` | 目标 Databend 版本是否支持 JS UDF；是否连错了实例 |
| 结果为 NULL | key/IV 字节长度、mode、密文 padding；是否混用了严格接口和字符串入口 |
| `CBC` 返回 NULL，`sm4-cbc` 正常 | 实例里是旧版本函数，运行只读检查确认后重新执行新 SQL |
| `to_string()` 报 UTF-8 错误 | 密文不是文本，用 `hex()` 或 `to_base64()` 展示 |
| 本地 Node 很快，Databend 里很慢 | QuickJS 是解释执行，没有 V8 的 JIT；以目标环境实测为准 |
| 创建函数失败 | 权限、函数名冲突、SQL 是否完整、`$$` 是否被 shell 展开 |

## 6. 适合的场景

不想额外部署、逻辑轻量、需要快速迭代，或者每次处理的数据量不大（几百到几千行）。数据量大、计算密集时，WASM 通常快得多，对比数据见 [三种 UDF 怎么选](ARCHITECTURE.md)。
