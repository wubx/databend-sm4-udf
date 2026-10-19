# 发布清单

仓库已托管在 GitHub。本文列出哪些文件需要提交、哪些不要提交、提交前的检查，以及正式开源发布前还要确认的事项。

## 需要提交的内容

| 内容 | 路径 | 说明 |
|---|---|---|
| 项目说明与安全说明 | `README.md`, `SECURITY.md` | |
| 忽略规则与构建入口 | `.gitignore`, `Makefile` | |
| JS 实现 | `javascript/sm4.mjs` | |
| Rust 实现 | `wasm/src/`, `wasm/Cargo.toml`, `wasm/Cargo.lock` | |
| Python 实现 | `python/sm4_udf/`, `python/pyproject.toml`, `python/requirements.lock` | |
| 部署 SQL | `sql/*.sql` | 6 个严格接口函数和 12 个字符串参数入口，由生成器产生 |
| 测试与固定向量 | `tests/` | 包括 `vectors.json`、`compat_vectors.json` 和 SQL 冒烟用例 |
| 工具脚本 | `scripts/` | SQL 生成、上传、部署检查、集成测试、基准测试、报告和图表 |
| 文档 | `docs/` | `docs/images/` 中的 SVG 由 `scripts/render_charts.py` 生成 |
| 测试报告 | `reports/` | 每个子目录含 `REPORT.md`、`results.csv`、`results.json` |
| MD5 对照实验 | `benchmarks/native-vs-wasm/` | 独立 Cargo 工程和测试脚本 |
| CI | `.github/workflows/test.yml` | 单元测试和 WASM 构建 |
| 许可证 | `LICENSE`, `python/LICENSE` | MIT；两份内容必须一致 |

**`Cargo.lock`、`requirements.lock`、生成的 `sql/*.sql` 和测试向量都要提交**，使用者可以直接部署，不用现场生成。CI 会检查它们和源码一致。

## 不要提交

- 构建产物：`wasm/target/`、`.wasm` 文件、Python 的 `build/`、`dist/`。
- 本地环境：`.venv/`、`__pycache__/`、`*.egg-info/`、测试缓存。
- 运行记录：`results/`、日志、原始查询记录、数据库状态。
- 敏感信息：`.env`、真实连接串和密码、证书私钥、真实密钥、业务数据。
- 个人部署参数：自定义 stage 路径、服务地址。提交前运行 `python3 scripts/generate_sql.py` 恢复默认值。

需要分发 `.wasm` 时，通过 GitHub Actions artifact 或 GitHub Release 发布，并附上 SHA256、构建版本和依赖许可证说明。

## 提交前检查

```bash
make test
make wasm
python3 scripts/generate_sql.py --check
git diff --cached --check
```

确认没有误加不该提交的文件，下面的命令应该没有输出：

```bash
git ls-files | grep -E '(^|/)(target|__pycache__|results|\.venv)(/|$)|\.wasm$|\.egg-info/'
```

`git diff --cached --check` 只检查空白格式，不能代替凭证扫描。推送前请人工审阅改动，并按团队要求运行 secret scanner。

可选：在有授权的专用测试实例上运行 `scripts/integration.py --benchmark-smoke`。部署正式函数后，用 `scripts/check_deployment.py --impl all` 做只读检查，确认实例里注册的确实是新版本。

## 正式开源发布前

- [x] 选择 MIT 许可证，添加 `LICENSE` 和 Python 包副本，更新包元数据。
- [ ] 确认版权归属。当前写的是 `databend-sm4-udf contributors`，如果是公司职务成果，需要确认授权。
- [ ] 核查直接和间接依赖的许可证和 NOTICE 要求，不能只看包元数据。`databend-udf` 元数据标注 Apache-2.0，gmssl 标注 BSD，`arrow-udf` 已固定版本。
- [ ] 设置私密的安全问题报告渠道，并更新 `SECURITY.md`。
- [ ] 确认目标 Databend 版本支持 JS UDF、WASM（Arrow UDF 接口）和 Python UDF 的 BINARY 类型。
- [ ] 审阅部署地址、允许列表、TLS 和网络、资源限制。示例中的本机地址不适用于远程生产环境。
- [ ] 在 GitHub 上确认 CI 实际运行通过。
- [ ] 审阅 `reports/` 下的报告和数据。源码变更或扩大测试范围后要重新测量，不要沿用旧数字。
- [ ] 如果发布 WASM 文件，附上构建信息、SHA256 和第三方声明。

当前 CI 只上传构建 artifact，不创建 GitHub Release，也不发布到包仓库。
