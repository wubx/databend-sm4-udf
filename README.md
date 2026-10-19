# Databend SM4 UDF

在 Databend 的 SQL 里直接做国密 SM4 加解密。同一套算法提供三种实现，按场景任选：

| 实现 | 运行位置 | 适合 |
|---|---|---|
| **WASM**（Rust） | Databend Query 内 | 批量加解密，数据量越大优势越明显 |
| **JavaScript** | Databend Query 内 | 小批量、快速上手，一条 SQL 就能部署 |
| **Python Server** | 独立服务，经 Arrow Flight 调用 | 需要和 Python 生态或外部系统集成 |

三端结果完全一致，支持 ECB、CBC、CFB128、OFB 四种模式。项目采用 [MIT License](LICENSE)，不是 Databend 官方内置函数，也未经密码学安全审计，使用前请先读 [安全说明](SECURITY.md)。

## 快速体验

以 WASM 为例，部署方法见下文。注册字符串参数入口后，key 和 IV 直接传原文即可：

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

把函数名后缀 `_wasm` 换成 `_js` 或 `_python`，就能调用另外两种实现。

## 两类接口

| 接口 | 函数名 | key / IV | 详细说明 |
|---|---|---|---|
| 严格字节接口 | `sm4_encrypt_<后端>` / `sm4_decrypt_<后端>` | BINARY，必须恰好 16 字节 | [API](docs/API.md) |
| 字符串参数入口 | `sm4_{encrypt,decrypt}_{default_iv,explicit_iv}_<后端>` | 原文字符串，自动折叠成 16 字节 | [COMPATIBILITY](docs/COMPATIBILITY.md) |

`<后端>` 是 `js`、`wasm` 或 `python`。两类接口对 key、IV 的处理规则不同，同一份数据加解密时不要混用。

严格接口要求调用方自己把 key、IV 转成字节，项目不猜测编码：

```sql
SELECT upper(hex(sm4_encrypt_wasm(
    to_binary('Hello Databend'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'),
    'CBC'
)));
-- DA12F33F321D4D551A76D8800F5AE244
```

几个共同约定：

- mode 必须显式传入，大小写不敏感，也接受 `sm4-cbc`、`SM4_128_CBC` 等写法。
- 参数为 NULL 或不合法（key 长度、mode、padding 等）时返回 NULL，不报错。
- 返回值是 BINARY。展示密文用 `hex()` / `to_base64()`，确认是文本的明文才用 `to_string()`。
- 文中的 key 和 IV 都是公开示例，不要用于真实数据。

## 部署

所有命令在项目根目录执行。生成的 SQL 使用 `CREATE OR REPLACE FUNCTION`，会替换目标实例上的同名函数，建议先在测试实例验证。完整步骤、权限、备份和回滚见 [部署总览](docs/DEPLOYMENT.md)。

先准备 Python 客户端工具（WASM 上传、部署检查、测试都会用到）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.lock
.venv/bin/python -m pip install --no-deps -e python
```

### JavaScript

代码直接内联在 SQL 里，Databend 节点上不需要装 Node.js。[详细指南](docs/DEPLOY_JS.md)

```bash
bendsql --query="$(<sql/js.sql)"          # 严格接口
bendsql --query="$(<sql/compat_js.sql)"   # 字符串参数入口
```

### WASM

需要 Rust 和 `wasm32-wasip1` 目标，以及支持 `LANGUAGE wasm` 的 Databend。[详细指南](docs/DEPLOY_WASM.md)

```bash
rustup target add wasm32-wasip1
cargo build --locked --release --target wasm32-wasip1 --manifest-path wasm/Cargo.toml

export SM4_URL=http://127.0.0.1:8000 SM4_USER=root SM4_PASSWORD=''
.venv/bin/python scripts/upload_wasm.py --stage sm4_udf
bendsql --query="$(<sql/wasm.sql)"
bendsql --query="$(<sql/compat_wasm.sql)"
```

`SM4_URL` 等变量要和 bendsql 指向同一个实例。上传脚本只负责把 `.wasm` 放进 stage，注册函数靠后面两条 SQL。

### Python Server

先启动服务，再注册函数。[详细指南](docs/DEPLOY_PYTHON.md)

```bash
.venv/bin/python -m sm4_udf.server --bind 127.0.0.1:8815

# 另开一个终端
python3 scripts/generate_sql.py --python-address http://127.0.0.1:8815
bendsql --query="$(<sql/python.sql)"
bendsql --query="$(<sql/compat_python.sql)"
```

这里的地址是 **Databend 服务端** 访问 Python 服务用的，示例只适合同机测试。服务使用明文 gRPC，跨机或生产环境需要在前面加 TLS 网关或放在受保护网络里，详见部署指南。

### 部署后检查

```bash
.venv/bin/python scripts/check_deployment.py              # 检查 WASM
.venv/bin/python scripts/check_deployment.py --impl all   # 三端都部署后
```

这是只读检查，用固定输入核对实例里实际注册的函数，能发现“源码更新了、实例里还是旧版本”的情况。

## 选哪种实现

**批量加解密用 WASM，小查询用 JS，需要 Python 生态再用 Python Server；有合适的内置函数时优先用内置函数。**

[三种 UDF 怎么选](docs/ARCHITECTURE.md) 这篇文章用图表对比了三者的原理和实测性能，也介绍了放进 ELT 流程时的用法。

## 测试与性能报告

<!-- TEST_REPORT_SUMMARY_START -->
**[SM4 三端](reports/sm4-backends/REPORT.md)**（[CSV](reports/sm4-backends/results.csv) · [JSON](reports/sm4-backends/results.json)）

- 正确性：严格接口 226 + 字符串 key/IV 244 个向量 × 三端，共 **1,410 条断言通过**。
- 性能：`explicit_iv`、CBC 解密，16/128/1,024 B × 1,000–50,000 行，144 次计时查询。1,024 B × 50,000 行中位耗时 WASM **0.871 s**、JS 79.525 s、Python 167.686 s。
<!-- TEST_REPORT_SUMMARY_END -->

**MD5 内置函数 vs WASM**：用来回答“有内置函数时还需要 WASM 吗”。

- [1–5 万行](reports/md5-native-vs-wasm/rows-1-50k/REPORT.md)：所有规模内置更快；1,024 B × 5 万行内置 **81 ms**、WASM **330 ms**。
- [10–100 万行](reports/md5-native-vs-wasm/rows-100k-1m/REPORT.md)：1,024 B × 100 万行内置 **1,471 ms**、WASM **3,730 ms**，差距缩小到约 2.5 倍。

所有数字都是单机、单线程下的完整 SQL 耗时。测试环境和方法见 [报告索引](reports/README.md) 与 [BENCHMARKS](docs/BENCHMARKS.md)。

## 开发与测试

本地单元测试不需要运行中的 Databend：

```bash
PYTHONPATH=python .venv/bin/python -m unittest discover -s tests -v
node tests/test_js.mjs
node tests/test_compat.mjs
cargo test --locked --manifest-path wasm/Cargo.toml
python3 scripts/generate_sql.py --check   # 检查 sql/ 与源码同步
```

三端共用 `tests/vectors.json` 和 `tests/compat_vectors.json` 里的固定向量，覆盖四种模式、0–4096 字节、块边界、中文和二进制数据、NULL、非法参数和非法 padding。参考密文由 OpenSSL 独立生成。

在专用的 Databend 测试实例上，可以跑一遍完整集成测试。脚本会临时创建 18 个函数、一张 Memory 表和一个 stage，结束后自动清理：

```bash
export SM4_URL=http://127.0.0.1:8000 SM4_USER=root SM4_PASSWORD=''
.venv/bin/python scripts/integration.py --benchmark-smoke
```

要求测试进程和 Query 在同一台机器、8815 端口空闲，且实例允许访问该 UDF 地址。不要在生产实例上运行。

性能测试的命令和口径见 [BENCHMARKS](docs/BENCHMARKS.md)。CI 只跑单元测试和 WASM 构建，不连接数据库。

## 目录结构

```text
javascript/   JS 实现，无外部依赖
wasm/         Rust 实现，编译为 WASI + Arrow UDF
python/       Python UDF Server，基于 gmssl 分组原语
sql/          生成好的部署 SQL
scripts/      SQL 生成、上传、部署检查、集成测试、基准测试、报告和图表
tests/        三端共享测试向量与测试
docs/         接口、部署、选型文章、测试方法、发布清单
reports/      已发布的测试与性能报告
benchmarks/   独立对照实验（内置 MD5 vs WASM）
```

## 安全

ECB、CBC、CFB128、OFB 都**不提供完整性校验**，解密结果非 NULL 不能说明密文没被篡改或密钥正确；ECB 还会暴露重复的明文分组。实现是标量查表算法，没有做常数时间保证和密钥内存擦除。详见 [SECURITY](SECURITY.md)，发布相关事项见 [RELEASING](docs/RELEASING.md)。
