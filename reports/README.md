# 测试与性能报告

所有已发布报告集中在本目录。每份报告由**完整运行记录**生成，并配有汇总 CSV 与脱敏 JSON（含环境、源码/工件指纹和逐次计时）；部分或失败的运行不会发布。

| 报告 | 回答的问题 | 测试矩阵 | 关键结果 |
|---|---|---|---|
| [SM4 三端](sm4-backends/REPORT.md)<br>[CSV](sm4-backends/results.csv) · [JSON](sm4-backends/results.json) | 三端是否结果一致？SM4 用哪种后端更快？ | 正确性：1,410 条共享向量断言<br>性能：`explicit_iv` CBC 解密，16/128/1,024 B × 1,000–50,000 行，144 次计时查询 | 三端全部通过。1 万行起 WASM 在所有长度最快；1,024 B × 5 万行 WASM 0.871 s、JS 79.5 s、Python 167.7 s。16 B × 1,000 行时 JS 更快 |
| [MD5 内置 vs WASM：1–5 万行](md5-native-vs-wasm/rows-1-50k/REPORT.md)<br>[CSV](md5-native-vs-wasm/rows-1-50k/results.csv) · [JSON](md5-native-vs-wasm/rows-1-50k/results.json) | 已有内置函数时，WASM 慢多少？ | 内置 / WASM MD5 + 两种 identity 基线，16/128/1,024 B × 1–50,000 行，432 次计时查询 | 所有规模内置更快；1,024 B × 5 万行内置 81 ms、WASM 330 ms |
| [MD5 内置 vs WASM：10–100 万行](md5-native-vs-wasm/rows-100k-1m/REPORT.md)<br>[CSV](md5-native-vs-wasm/rows-100k-1m/results.csv) · [JSON](md5-native-vs-wasm/rows-100k-1m/results.json) | 行数增大后，WASM 固定成本是否被摊薄？ | 仅内置 / WASM MD5，16/128/1,024 B × 10 万/30 万/100 万行，108 次计时查询 | 内置仍更快；1,024 B × 100 万行内置 1,471 ms、WASM 3,730 ms，耗时比降到约 2.54× |

**结论：自定义计算场景下，WASM 是当前三种 SM4 后端里批量最快的；已有语义合适的内置函数时，应优先使用内置函数。**

## 共同口径

- 环境：AMD Ryzen 9 5950X 单机，Databend Query v1.2.947-nightly，2026-10-19（UTC）测量。
- 设置：`max_threads=1`、`max_block_size=8192`、Memory 表、结果缓存关闭；每组预热 1 次，正式 3 次（SM4）或 5 次（MD5），取中位数。
- 计时：完整服务端 SQL 耗时，包含扫描、运行时创建/编译、Arrow 转换及 Python RPC；数据准备不计时。
- 未覆盖：并发 QPS、峰值内存、跨机网络/TLS、多线程扩展、纯内核计算时间。

详细方法见 [BENCHMARKS](../docs/BENCHMARKS.md)。

## 生成与更新

| 报告目录 | 生成工具 | 原始记录（Git 忽略） |
|---|---|---|
| `sm4-backends/` | `scripts/report_results.py`（`--update-readme` 同步 README 摘要） | `results/` |
| `md5-native-vs-wasm/rows-1-50k/` | `benchmarks/native-vs-wasm/report.py`（默认目录） | `results/native-vs-wasm.json` |
| `md5-native-vs-wasm/rows-100k-1m/` | `benchmarks/native-vs-wasm/report.py --report-dir reports/md5-native-vs-wasm/rows-100k-1m` | `results/native-vs-wasm-large.json` |

`REPORT.md` 由同目录 `results.json` 渲染，单元测试会校验两者一致，不要手工编辑。源码变化或测试范围扩大后应重新测量，并用新目录发布不同矩阵，而不是覆盖或拼接旧结果。测试工具和 MD5 实验源码分别在 [`scripts/`](../scripts/) 与 [`benchmarks/native-vs-wasm/`](../benchmarks/native-vs-wasm/README.md)。
