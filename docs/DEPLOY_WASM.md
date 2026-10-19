# 部署 WASM UDF

```text
构建：Rust 源码 → 编译为 wasm32-wasip1 → .wasm 文件 → 上传到 Databend stage
调用：SQL → Query 内的 WASM 运行时 → Arrow UDF 接口 → SM4 → BINARY 结果
```

Databend 节点上不需要 Rust，也不需要额外服务。需要准备：

- 构建机：Rust/Cargo，首次构建需要联网下载依赖。
- Databend：支持 `LANGUAGE wasm`，并有 stage 和 UDF 权限。

`.wasm` 文件要按 Arrow UDF 接口导出函数，Databend 才能识别，项目已固定 SDK 版本和 `Cargo.lock`。权限、备份和接口选择先看 [部署总览](DEPLOYMENT.md)。

## 1. 测试与构建

```bash
rustup target add wasm32-wasip1
cargo test --locked --manifest-path wasm/Cargo.toml
cargo build --locked --release --target wasm32-wasip1 --manifest-path wasm/Cargo.toml
```

产物位置：

```text
wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm
```

设置了 `CARGO_TARGET_DIR` 的话，产物在对应目录下，后续命令的路径也要跟着改。

## 2. 用内容哈希命名发布文件

每次发布用新文件名，旧函数仍指向旧文件，回滚时只需切回去。用 SHA256 命名最方便（Linux 示例，macOS 可用 `shasum -a 256`）：

```bash
mkdir -p results/releases
ARTIFACT=wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm
SHA=$(sha256sum "$ARTIFACT" | awk '{print $1}')
RELEASE_FILE="sm4_${SHA}.wasm"
cp "$ARTIFACT" "results/releases/$RELEASE_FILE"
printf 'SHA256=%s\n' "$SHA"
```

**不要原地覆盖仍被函数引用的 `.wasm` 文件。**

## 3. 上传并注册

先配置连接，确保和 bendsql 指向同一个实例：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
```

上传文件、生成 SQL、保存发布记录，然后注册：

```bash
.venv/bin/python scripts/upload_wasm.py \
  --stage sm4_udf --file "results/releases/$RELEASE_FILE"

python3 scripts/generate_sql.py --wasm-path "@sm4_udf/$RELEASE_FILE"

# 保存本次实际执行的 SQL，回滚时用
cp sql/wasm.sql "results/releases/${SHA}_wasm.sql"
cp sql/compat_wasm.sql "results/releases/${SHA}_compat_wasm.sql"

bendsql --query="$(<sql/wasm.sql)"          # 严格接口
bendsql --query="$(<sql/compat_wasm.sql)"   # 字符串参数入口
```

上传脚本会在 stage 不存在时创建它，只负责上传，不注册函数。如果 stage 里有同名文件会被替换，所以用哈希文件名。生成器每次会重写全部六个 SQL 文件，如果 Python 地址也有自定义值，要同时传 `--python-address`。

## 4. 验证实例加载的版本

先确认函数定义指向了新文件：

```sql
SELECT name, definition
FROM system.user_functions
WHERE name IN ('sm4_encrypt_wasm', 'sm4_decrypt_wasm',
  'sm4_encrypt_explicit_iv_wasm', 'sm4_decrypt_explicit_iv_wasm');
```

再运行检查：

```bash
.venv/bin/python scripts/check_deployment.py --impl wasm
bendsql --query="$(<tests/compat_smoke.sql)"   # 需要已注册字符串参数入口
```

`compat_smoke.sql` 每一行的 `actual` 都必须等于 `expected`，出现 NULL 也算失败。

手动验证严格接口：

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

## 5. 升级与回滚

1. 记录旧函数定义、旧发布 SQL、stage 路径和 SHA256，保留旧文件。
2. 新版本用新文件名上传，先在测试环境验证，再注册到目标实例。
3. 检查固定示例、各种模式、业务样本和资源占用。
4. 出问题时重新执行旧的发布 SQL，函数就会指回旧文件，不需要重新编译。
5. 确认没有查询再用旧文件后，再按组织策略清理。

提交代码前运行 `python3 scripts/generate_sql.py`，把 `sql/` 恢复为默认路径。`.wasm` 文件通过 CI artifact 或 Release 分发，`wasm/target/`、`results/` 不进入 Git。

## 6. 常见问题

| 现象 | 排查方向 |
|---|---|
| 不支持 `LANGUAGE wasm` | 目标 Databend 版本或构建是否支持 WASM UDF |
| stage 文件不存在或无权限 | 上传和 bendsql 是否是同一个实例；文件名、路径是否完全一致；Query 是否有读权限 |
| 找不到 HANDLER | 上传了旧版或其他工程的 `.wasm`；字符串参数入口需要包含新导出的版本 |
| `CBC` 返回 NULL | 用只读检查区分是旧版本还是参数非法；改了源码不会自动更新已部署的模块 |
| 升级后结果没变 | 核对函数 `definition` 里的路径和实例；用新文件名重新注册 |
| 单行查询比 JS 慢 | 每次查询有约一百多毫秒的运行时初始化和编译，量小时这部分占主导 |
| 大查询 CPU 或内存吃紧 | 检查块大小、并发，以及 Query 节点的资源限制 |

## 7. 适合的场景

批量、计算密集、不依赖外部服务的自定义转换，例如 ELT 中的批量加解密、编码转换和解析。计算在 Query 内完成，不用维护额外服务，但会占用 Query 节点的 CPU 和内存。有合适的内置函数时优先用内置函数。选型对比和实测数据见 [三种 UDF 怎么选](ARCHITECTURE.md)。
