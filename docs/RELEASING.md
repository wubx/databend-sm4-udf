# 提交与发布清单

仓库根目录应是 **`databend-sm4-udf/` 本身**，不要将外层实验工作区作为 repo 根目录。

## 首次提交应包含

| 内容 | 路径 | 原因 |
|---|---|---|
| 项目说明和安全边界 | `README.md`, `SECURITY.md` | 使用、部署和风险说明 |
| 忽略规则与便捷命令 | `.gitignore`, `Makefile` | 防止提交生成物，统一构建入口 |
| JS 源码 | `javascript/sm4.mjs` | JavaScript 实现 |
| Rust 源码和锁文件 | `wasm/src/`, `wasm/Cargo.toml`, `wasm/Cargo.lock` | 构建 WASM，固定依赖 |
| Python 源码和依赖 | `python/sm4_udf/`, `python/pyproject.toml`, `python/requirements.lock` | UDF Server 与依赖复现 |
| 部署 SQL | `sql/js.sql`, `sql/wasm.sql`, `sql/python.sql`, `sql/compat_*.sql` | 六个严格接口和十二个中性命名的 IV 策略入口；生成器校验同步 |
| 测试及固定向量 | `tests/` | 共同 API 回归；`vectors.json` / `compat_vectors.json` 和 SQL smoke 用例是必要测试数据，应提交 |
| 工具 | `scripts/` | SQL 生成、上传、集成测试、基准、报告和图表生成脚本 |
| API 和使用文档 | `docs/` | 接口规则、部署、基准方法及发布清单；`docs/images/` 的 SVG 由 `scripts/render_charts.py` 生成 |
| 测试与性能报告 | `reports/` | 每个子目录含 `REPORT.md`、`results.csv`、`results.json`，是可提交的脱敏实测快照 |
| 原生/WASM 对照 | `benchmarks/native-vs-wasm/` | MD5 源码、独立 Cargo.lock 和复现脚本；报告位于 `reports/md5-native-vs-wasm/` |
| CI | `.github/workflows/test.yml` | 单元测试和 WASM 构建 |
| 许可证 | `LICENSE`, `python/LICENSE` | MIT 全文；Python 包副本用于打包，须与根目录一致 |

**`Cargo.lock`、`requirements.lock`、生成的 `sql/*.sql` 和 `tests/vectors.json` 都要提交。**
本项目保留生成的部署 SQL 和共享向量，方便使用者直接部署、无需现场生成测试参考；CI 会校验它们与源码一致。

## 不要提交

- `wasm/target/`、`.wasm` 二进制、Python `build/` / `dist/`。
- `.venv/`、`__pycache__/`、`*.egg-info/`、测试缓存。
- `results/`、运行日志、原始查询记录、数据库/Meta 状态。
- `.env`、真实 DSN/密码、证书私钥、真实密钥或业务数据。
- 外层工作区里的历史实验脚本、fixture、tmux 状态和报告。

需要分发 `.wasm` 时，优先通过 GitHub Actions artifact 或正式 GitHub Release，附 SHA256、构建版本及依赖授权说明；不要将编译缓存一起上传。

## 本地提交前检查

先按 README 安装依赖、激活环境并准备 Node/Rust 工具链，再运行：

```bash
make test
make wasm
python3 scripts/generate_sql.py --check
```

可选：在已获授权的专用 Databend 节点上执行 `scripts/integration.py --benchmark-smoke`，检查测试和清理结果。脚本会创建临时对象，不要未经审批在生产运行。

部署正式函数后，用 `SM4_URL=... .venv/bin/python scripts/check_deployment.py --impl all` 只读检查已注册版本；它验证 README 的固定密文及 mode 别名，不会被“临时集成测试通过、实际部署仍旧版”掩盖。若只部署 WASM，省略 `--impl all`。

## 初始化及检查暂存内容

以下仅为手动命令，本项目工具不会自动创建远端、提交或推送：

```bash
cd /path/to/databend-sm4-udf

git init -b main
git add .gitignore README.md SECURITY.md LICENSE Makefile .github docs \
  javascript python/pyproject.toml python/requirements.lock python/LICENSE python/sm4_udf \
  wasm/Cargo.toml wasm/Cargo.lock wasm/src sql scripts tests benchmarks

git status --short
git diff --cached --stat
git diff --cached --check

# 以下命令正常情况下不应有输出：
git ls-files | grep -E '(^|/)(target|__pycache__|results|\.venv)(/|$)|\.wasm$|\.egg-info/'

# 审阅内容、完成许可证/安全检查后，再自行 commit 和配置 GitHub remote。
```

`git diff --cached --check` 仅检查文本格式，**不等于凭证/安全扫描**。首次推送前仍需人工审阅暂存内容，并按团队要求运行 secret scanner。

## 正式开源发布前必须确认

- [x] 按所有者选择采用 MIT，添加 `LICENSE` 和 Python 包许可证副本，更新包元数据。
- [ ] 确认版权归属。当前版权行使用 `databend-sm4-udf contributors`；若为公司职务成果，发布前确认相应授权。
- [ ] 审查直接和传递依赖的真实许可证/NOTICE，不能只依赖包元数据。
      `arrow-udf` revision 已固定；`databend-udf` 元数据列 Apache-2.0、gmssl 列 BSD，仍需核实分发义务。
- [ ] 设置安全问题的私密报告渠道，更新 `SECURITY.md`。
- [ ] 确认目标 Databend 版本支持 JS、WASM/Arrow ABI 和 Python BINARY schema。
- [ ] 审阅部署地址、allowlist、TLS/网络、安全及资源限制；示例 loopback 地址不是远程生产配置。
- [ ] 在 GitHub 实际运行 CI；提供 workflow 不代表已经通过 GitHub Actions。
- [ ] 发布前审阅 `reports/` 下各报告及对应 JSON/CSV；已完成范围以报告列出的矩阵为准，不发布进行中的部分数据。源码有变更或需扩大测试范围时重新测量，不能复用其他接口的旧数字。
- [ ] 若发布 WASM artifact，附构建信息、校验值及所需第三方声明。

建议仓库名：`databend-sm4-udf`。当前 CI 仅上传构建 artifact，不创建 GitHub Release，也不发布到包仓库。
