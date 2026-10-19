# Databend SM4 UDF

为 Databend 提供 SM4 加密/解密：**JavaScript、Rust/WASM、Python UDF Server**。提供严格字节接口，以及支持 **默认 IV／显式 IV 两种策略**的原文 key/IV 入口。

本项目采用 [MIT License](LICENSE)。这是可独立发布的项目草稿，不是 Databend 官方内置函数，也没有经过密码学安全审计。发布前事项见 [RELEASING](docs/RELEASING.md)。

## 文档导航

- [JS、WASM、Python 三种 UDF 怎么选（含性能对比图）](docs/ARCHITECTURE.md)
- [部署总览：连接、权限、接口选择与备份](docs/DEPLOYMENT.md)
- 详细部署：[JavaScript](docs/DEPLOY_JS.md) · [WASM](docs/DEPLOY_WASM.md) · [Python Server](docs/DEPLOY_PYTHON.md)
- [测试与性能报告索引](reports/README.md)：[SM4 三端](reports/sm4-backends/REPORT.md) · [MD5 内置 vs WASM](reports/md5-native-vs-wasm/rows-1-50k/REPORT.md) · [测试方法](docs/BENCHMARKS.md)
- [API](docs/API.md) · [字符串 key/IV 策略](docs/COMPATIBILITY.md)

## 在 ELT / Data Pipeline 中如何选择

**WASM UDF 同样适合 ELT 的 T（Transform）：在 Databend 内完成批量、计算密集且不依赖外部服务的自定义转换。**
它不仅用于交互查询，也可作为 SQL 转换作业的一部分；无需仅为这段计算把数据送到独立 Python UDF Server。

```text
数据加载到 Databend → SQL 过滤 / 关联 / 聚合与 UDF 转换 → 写入目标表
```

| 方式 | 在 ELT / Data Pipeline 中的定位 |
|---|---|
| 内置 SQL / 函数 | 已有所需语义时优先使用，完成现成的转换、关联与聚合 |
| WASM UDF | 补充内置函数未覆盖的批量计算，如加解密、编码转换、解析和自定义计算；需符合宿主 ABI/能力限制 |
| JS UDF | 轻量转换、快速迭代，或固定开销更重要的小批量计算 |
| Python Remote UDF | 需要 Python 生态、模型/外部依赖或独立服务治理的处理环节；需验证 RPC、SDK 和服务资源成本 |

生产前还需验证读取、转换、写入的端到端吞吐、内存/并发、失败恢复与结果正确性；幂等和 exactly-once 需由作业层保证。
更多架构和选型见 [ARCHITECTURE](docs/ARCHITECTURE.md)。

## 字符串 key/IV 示例（推荐文章演示使用）

先按 [兼容入口部署说明](docs/COMPATIBILITY.md) 注册 `sql/compat_wasm.sql` 中的函数。

```sql
-- 显式 IV 策略：原文 key/IV，无需手工补零、折叠或截断。
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

-- 默认 IV 策略：允许短 IV；key 看起来像 Hex，但这里不能 unhex(key)。
SELECT to_base64(sm4_encrypt_default_iv_wasm(
    'Hello Databend', 'F3229A0B371ED2D9441B830D21A390C3', '0123456789', 'SM4_128_CBC'
)) AS ciphertext_base64;
-- rEY+tZnG98ar/CGWKTwk2Q==
```

三个后端都有同名适配入口，将 `_wasm` 换为 `_js` / `_python` 即可。签名为
`(BINARY, STRING, STRING, STRING) -> BINARY`，key/IV 按原始 UTF-8 字符串字节处理。

mode 需显式传入，不读取会话变量；非法参数统一 NULL。默认 IV 不是随机 IV，
只是固定兼容策略。密文仍需显式 Hex/Base64 编解码；不自动猜测字符串。
完整规则和固定参考样例见 [COMPATIBILITY](docs/COMPATIBILITY.md)。

## 严格字节接口（保留原用法）

```sql
sm4_encrypt_js(data, key, iv, mode)
sm4_decrypt_js(data, key, iv, mode)
sm4_encrypt_wasm(data, key, iv, mode)
sm4_decrypt_wasm(data, key, iv, mode)
sm4_encrypt_python(data, key, iv, mode)
sm4_decrypt_python(data, key, iv, mode)
```

本节六个严格接口函数：

```text
(BINARY NULL, BINARY NULL, BINARY NULL, STRING NULL) -> BINARY NULL
```

| 模式 | 规范 mode | Padding | IV |
|---|---|---|---|
| ECB | `ECB` | PKCS#7 | 忽略非 NULL IV；建议传 `to_binary('')` |
| CBC | `CBC` | PKCS#7 | 恰好 16 字节 |
| CFB128 | `CFB128` | 无 | 恰好 16 字节 |
| OFB | `OFB` | 无 | 恰好 16 字节 |

- key 必须恰好 **16 字节**。不自动识别 Hex、不补零、不折叠 key、不填补或截断 IV。
- mode 不区分 ASCII 大小写，也接受 `sm4-cbc`、`SM4_128_CBC`、`CFB` 等明确别名。
- 任意参数为 NULL、模式非法、key/IV 长度非法、ECB/CBC 密文长度或 padding 非法，均返回 **NULL**。
- 返回任意二进制数据，不尝试 UTF-8 解码；合法的空结果 `BINARY ''` 和 NULL 不同。
- 所有后端遵循相同的字节接口，不自动采用其他数据库的参数处理约定。

本节规则只适用于严格接口，完整约定见 [API](docs/API.md)。兼容入口的 key 折叠和 IV 默认规则不同，不要混用两种接口。

## 严格字节接口 SQL 示例

先按下文部署对应实现，然后执行：

```sql
-- key 看起来像 Hex 时，调用方明确选择 unhex()，而不是自动猜测。
SELECT upper(hex(sm4_encrypt_wasm(
    to_binary('Hello Databend'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'),
    'CBC'
)));

-- 加密再解密；换成 _js 或 _python 即可测试另一实现。
SELECT to_string(sm4_decrypt_wasm(
    sm4_encrypt_wasm(
        to_binary('Hello Databend'),
        unhex('0123456789abcdeffedcba9876543210'),
        unhex('00112233445566778899aabbccddeeff'), 'CBC'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
));

-- 无需 IV 的 ECB
SELECT to_base64(sm4_encrypt_js(
    to_binary('Hello Databend'), to_binary('0123456789abcdef'), to_binary(''), 'ECB'
));
```

**示例 key/IV 都是公开固定值，只用于演示和测试，不可当作生产密钥或 IV 策略。**

## 部署

下面是快速开始；完整依赖、验证、升级/回滚和常见问题见 [部署总览](docs/DEPLOYMENT.md) 以及各后端详细指南。

从项目根目录执行；SQL 中使用 `CREATE OR REPLACE FUNCTION`，部署会替换目标实例的同名函数。

### JavaScript

[详细部署指南](docs/DEPLOY_JS.md)

无需 Node.js 或 npm 包在 Databend 中运行。完整 JS 源码内联在生成的 SQL 中：

```bash
python3 scripts/generate_sql.py
bendsql --query="$(<sql/js.sql)"  # Bash，使用你已配置的 bendsql 连接
```

### WASM

[详细部署指南](docs/DEPLOY_WASM.md)

需要 Rust、WASI 目标，以及支持 `LANGUAGE wasm` 的 Databend 版本。

```bash
rustup target add wasm32-wasip1
cargo build --locked --release --target wasm32-wasip1 --manifest-path wasm/Cargo.toml
```

先安装下文 Python 工具依赖，再配置 **与 bendsql 相同的目标实例**并上传工件：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python scripts/upload_wasm.py --stage sm4_udf
bendsql --query="$(<sql/wasm.sql)"
```

上传脚本创建指定 stage（不存在时），并可能替换同名文件。它不注册函数；若更改 stage/文件名，先用 `generate_sql.py --wasm-path @stage/file.wasm` 更新部署定义。

该工件采用 Arrow UDF ABI，不是可直接用任意 WASM 函数替代的格式；SDK git revision 和 Cargo.lock 都已固定。目标实例的 ABI/WASI 支持需要实际验证。

### Python UDF Server

[详细部署指南](docs/DEPLOY_PYTHON.md)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.lock
.venv/bin/python -m pip install --no-deps -e python
.venv/bin/python -m sm4_udf.server --bind 127.0.0.1:8815
```

另一个终端中生成 SQL 并注册：

```bash
python3 scripts/generate_sql.py --python-address http://127.0.0.1:8815
bendsql --query="$(<sql/python.sql)"
```

`127.0.0.1` 是 **Databend 服务端看到的地址**，不是 SQL 客户端的地址。默认配置只适合同机本地测试，且 Databend 必须允许该 UDF 地址及相应传输方式。

当前固定的 `databend-udf==0.2.20` 会建立明文 gRPC 监听，本项目不提供未经验证的原生 TLS 开关。生产/跨机部署需要自行配置合适的 TLS 终止网关或受保护网络，并验证 Databend 的信任证书、allowlist 和访问控制；生成器可使用实际的 `https://...` 网关地址。本项目不会自动搭建网关或修改实例安全设置。不要将明文示例直接暴露到公网，也不要为跑示例而关闭生产安全校验。

## 测试与性能报告

<!-- TEST_REPORT_SUMMARY_START -->
**[SM4 三端](reports/sm4-backends/REPORT.md)**（[CSV](reports/sm4-backends/results.csv) · [JSON](reports/sm4-backends/results.json)）

- 正确性：严格接口 226 + 字符串 key/IV 244 个向量 × 三端，共 **1,410 条断言通过**。
- 性能：`explicit_iv`、CBC 解密，16/128/1,024 B × 1,000–50,000 行，144 次计时查询。1,024 B × 50,000 行中位耗时 WASM **0.871 s**、JS 79.525 s、Python 167.686 s。
<!-- TEST_REPORT_SUMMARY_END -->

**MD5 内置 vs WASM**：回答“已有内置函数时还需要 WASM 吗”，与 SM4 测量相互独立。

- [1–5 万行](reports/md5-native-vs-wasm/rows-1-50k/REPORT.md)：所有规模内置更快；1,024 B × 5 万行内置 **81 ms**、WASM **330 ms**。
- [10–100 万行](reports/md5-native-vs-wasm/rows-100k-1m/REPORT.md)：1,024 B × 100 万行内置 **1,471 ms**、WASM **3,730 ms**，耗时比降到约 2.54×。

**已有语义合适的内置函数时优先使用；WASM 主要补充自定义计算。** 所有数字为单机、单线程的完整服务端 SQL 耗时，范围、口径和更新方式见 **[报告索引](reports/README.md)**。

## 运行测试

```bash
# 依赖安装见上文；不需要正在运行的 Databend
PYTHONPATH=python .venv/bin/python -m unittest discover -s tests -v
node tests/test_js.mjs
node tests/test_compat.mjs
cargo test --locked --manifest-path wasm/Cargo.toml
python3 scripts/generate_sql.py --check
```

`tests/vectors.json` 是三端共用的确定性向量，涵盖四种模式、加解密、0–4096 B、块边界、二进制/中文、NULL、非法参数、非法 padding 及 5 个固定参考样例。另有公开示例 `Hello Databend` 的回归向量，严格接口固定期望密文为 `DA12F33F321D4D551A76D8800F5AE244`，并保留历史小写输入的独立回归向量，覆盖 `CBC`、`sm4-cbc`、`SM4_128_CBC` 的加密和解密。Node/OpenSSL 仅用作测试参考，不是运行依赖。

部署后还应单独检查**实例中实际注册的版本**，避免源码已更新但仍调用旧工件：

```bash
export SM4_URL=http://127.0.0.1:8000
.venv/bin/python scripts/check_deployment.py            # 仅检查 WASM
.venv/bin/python scripts/check_deployment.py --impl all # 三端均已部署时
```

这是只读检查；返回 NULL、错误密文、别名行为不一致或函数调用失败时，以非零状态退出，不会替换任何函数。也可直接执行 [tests/deployment_smoke.sql](tests/deployment_smoke.sql)，三条查询都必须得到文件顶部列出的密文和明文 Hex。若只有 `sm4-cbc` 成功而 `CBC` 返回 NULL，应检查 `system.user_functions` 中的 `definition` 和 WASM 工件版本。

`tests/compat_vectors.json` 另覆盖原文 key 折叠、短/长/默认 IV、四种模式、UTF-8/空值和边界数据；`tests/compat_smoke.sql` 可直接验证原始字符串参数及预期密文。

手动在专用 Databend 测试节点运行严格接口和兼容入口的集成测试（共 18 个临时函数）：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python scripts/integration.py --benchmark-smoke
```

此命令要求 Query 与测试进程同机、8815 空闲且该 UDF 地址已被允许；会启动临时 Python Server，创建唯一前缀的函数、Memory 表和 stage，验证后清理。不创建或更改 Databend 实例安全配置。不要在生产上未经授权执行。

CI 运行无服务器单元测试和 WASM 构建，不会连接任意数据库。

## 运行性能测试

六个严格接口函数均部署、Python Server 已启动后（默认 `--profile raw`）：

```bash
export SM4_URL=http://127.0.0.1:8000
.venv/bin/python scripts/benchmark.py \
  --lengths 16,128,1024 --rows 10000,30000,50000 \
  --modes CBC --operations decrypt --repeats 3
```

比较字符串 key/IV 入口时，三端部署相同 profile 后加 `--profile default_iv` 或 `--profile explicit_iv`；不要混合不同接口的结果。耗时包含运行时、转换和 RPC，不是纯密码内核时间；大规模 Python 测试较慢，建议在 tmux 中运行。测量口径、完整性要求和报告发布流程见 [BENCHMARKS](docs/BENCHMARKS.md)。

## 目录

```text
javascript/       无外部依赖的 JS SM4
wasm/             Rust/WASI + Arrow UDF 导出
python/           gmssl 原始分组原语 + 统一模式/padding + Flight Server
sql/              严格接口及两种 IV 策略入口的部署定义
scripts/          SQL 生成、可选集成测试、基准与报告生成工具
tests/            三端共享向量与测试
docs/             接口、兼容性、部署、测试方法及发布清单
reports/          已发布的测试与性能报告（REPORT.md + CSV + 脱敏 JSON）
benchmarks/       独立对照实验源码（内置 MD5 vs WASM）
```

## 安全与发布状态

这些 ECB/CBC/CFB128/OFB 模式**不提供完整性认证**；不要把非 NULL 解密结果当作密文未被篡改的证明。ECB 会泄露重复分组，CBC padding 检查也不能验证密钥是否正确。本实现是标量查表算法，未保证常数时间，没有密钥自动擦除或安全审计。

详见 [SECURITY](SECURITY.md)。项目已选择 MIT；正式发布前仍需核查依赖发布要求，并设置安全问题报告渠道。提交内容和检查步骤见 [RELEASING](docs/RELEASING.md)。
