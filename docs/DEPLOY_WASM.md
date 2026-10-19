# WASM UDF 部署

## 1. 架构与前置条件

```text
Rust 源码 → wasm32-wasip1 编译 → .wasm → Databend stage
SQL → Query 的 WASM 运行时 → Arrow UDF ABI → SM4 → BINARY
```

需要支持 `LANGUAGE wasm` 和本项目 Arrow ABI/WASI 能力的 Databend，以及 stage/UDF 权限。
不是任意 `.wasm` 都能直接当 Databend UDF；项目固定 SDK git revision、Cargo.lock 和函数签名。
运行节点不需要 Rust，也不需要外部 UDF Server。构建环境需要 Rust/Cargo 和网络获取依赖（或已有缓存）。

## 2. 测试与构建

```bash
rustup target add wasm32-wasip1
cargo test --locked --manifest-path wasm/Cargo.toml
cargo build --locked --release --target wasm32-wasip1 --manifest-path wasm/Cargo.toml
```

默认工件：

```text
wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm
```

如果设置 `CARGO_TARGET_DIR`，工件会在该目录下，应同步修改下面的文件路径。
不要用宿主架构的 `.so` / 可执行文件，也不要把其他 ABI 的 WASM 改名后上传。

## 3. 用内容校验值准备版本化工件

以下是 Linux/Bash 示例，从项目根目录执行；macOS 可以用相应 SHA256 工具：

```bash
mkdir -p results/releases
ARTIFACT=wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm
SHA=$(sha256sum "$ARTIFACT" | awk '{print $1}')
RELEASE_FILE="sm4_${SHA}.wasm"
cp "$ARTIFACT" "results/releases/$RELEASE_FILE"
printf 'SHA256=%s\n' "$SHA"
```

示例和旧工件路径不同，便于回滚。**不要原地覆盖仍被现有函数引用的 WASM。**

## 4. 上传并生成部署 SQL

按 [共同部署约定](DEPLOYMENT.md) 安装 Python 工具依赖，配置 HTTP 工具与 bendsql 为同一实例。

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''

.venv/bin/python scripts/upload_wasm.py \
  --stage sm4_udf --file "results/releases/$RELEASE_FILE"

python3 scripts/generate_sql.py --wasm-path "@sm4_udf/$RELEASE_FILE"

# 存档本次实际执行的 SQL，不提交私人部署地址/路径
cp sql/wasm.sql "results/releases/${SHA}_wasm.sql"
cp sql/compat_wasm.sql "results/releases/${SHA}_compat_wasm.sql"

# 严格字节接口；可按需只部署其中一种接口
bendsql --query="$(<sql/wasm.sql)"
bendsql --query="$(<sql/compat_wasm.sql)"
```

上传脚本只上传，不注册函数；注册 SQL 只绑定路径，不会帮你构建或上传。
脚本可能替换 stage 内同名文件，因此使用内容哈希文件名并复核发布记录，不依赖覆盖实现版本切换。
生成器会重写六个部署文件；自定义过 Python 地址时也应传入 `--python-address`，见 [共同约定](DEPLOYMENT.md)。

## 5. 验证实例实际加载的版本

```sql
SELECT name, definition
FROM system.user_functions
WHERE name IN ('sm4_encrypt_wasm', 'sm4_decrypt_wasm',
  'sm4_encrypt_explicit_iv_wasm', 'sm4_decrypt_explicit_iv_wasm');
```

确认 definition 中的新 stage 路径和 HANDLER，再执行：

```bash
.venv/bin/python scripts/check_deployment.py --impl wasm
bendsql --query="$(<tests/compat_smoke.sql)"  # 要求已注册字符串策略函数
```

严格接口示例：

```sql
SELECT upper(hex(sm4_encrypt_wasm(
    to_binary('Hello Databend'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
))) AS ciphertext_hex;
-- DA12F33F321D4D551A76D8800F5AE244

SELECT to_string(sm4_decrypt_wasm(
    unhex('DA12F33F321D4D551A76D8800F5AE244'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
)) AS plaintext;
-- Hello Databend
```

`tests/compat_smoke.sql` 的每行 actual 必须等于 expected。它不是只要 SQL 成功就通过；NULL 也应视为失败。

## 6. 升级和回滚

1. 记录旧函数定义、旧发布 SQL、stage 路径与 SHA256；保留旧工件。
2. 新版本使用新文件名/路径，先在测试环境验证，再执行对应 SQL。
3. 检查常量示例、各模式、业务样本和资源开销。
4. 出现问题时重新执行旧发布 SQL，使函数指回旧工件；无需重新编译旧源代码。
5. 确认没有旧查询/函数需要旧路径后，再按组织策略回收旧工件，不立刻删除。

准备提交源码时恢复标准 SQL：`python3 scripts/generate_sql.py`；这不改变已部署函数。
工件通过 CI artifact/Release 分发，`wasm/target/`、`.wasm`、`results/` 不进入源码提交。

## 7. 常见问题

| 现象 | 检查方向 |
|---|---|
| `LANGUAGE wasm` 不支持 | 目标 Databend 版本/构建能力，不能仅凭本地编译成功判断 |
| stage 文件不存在/无权限 | 上传目标是否与 bendsql 相同，文件名和路径是否精确，Query 是否可读 |
| 找不到 HANDLER | 上传了旧工件或错误 ABI；新字符串策略导出需匹配新版工件 |
| `CBC` 返回 NULL | 用只读检查区别旧版本问题与非法参数；源码修改不会自动升级已部署模块 |
| 新版仍旧结果 | 复核实际函数 definition 的路径和所用实例；用唯一文件名重注册，别原地覆盖 |
| 单行比 JS 慢 | 完整 SQL 包含初始化/编译和 Arrow 转换；当前实现不是常驻零开销函数调用 |
| 大查询耗尽 CPU/内存 | 检查块大小、并发和宿主资源限制；不要把沙箱理解为自动消除资源风险 |

## 8. 适用场景

**WASM UDF 可用于 ELT 的 T（Transform），不局限于交互查询。** 数据先加载进 Databend，再通过 SQL
调用 WASM 执行批量、CPU 密集且不依赖外部服务的自定义计算，最后写入目标表。
典型候选包括批量加解密、编码转换、解析和自定义计算；本项目实测覆盖 SM4 和 MD5，不代表其他逻辑也已完成验证。

已有内置函数满足需求时优先使用；缺少的批量计算可评估 WASM，无需仅为该函数维护 Python UDF Server。
需要 Python 库/模型/外部依赖时，Remote UDF 仍有独立价值，不应简单按“Pipeline/查询”划分。
是否采用需要同时考虑固定启动成本、ABI/版本支持、Query CPU/内存、构建与工件管理，不是“WASM 总比其他方式快”。

当前结果是函数级 SQL 表现，不是生产 ELT 压测。上线前需要验证源表读取、JOIN/聚合、转换、写入/提交的完整链路，
包括并发和峰值资源、超时、重试幂等及失败恢复；UDF 不替代这些作业级能力。
