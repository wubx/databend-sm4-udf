# 测试与性能报告

所有已发布报告集中在本目录。每份报告由**完整运行记录**生成，并配有汇总 CSV 与脱敏 JSON（含环境、源码/工件指纹和逐次计时）；部分或失败的运行不会发布。

| 报告 | 回答的问题 | 测试矩阵 | 关键结果 |
|---|---|---|---|
| [SM4 三端](sm4-backends/REPORT.md)<br>[CSV](sm4-backends/results.csv) · [JSON](sm4-backends/results.json) | 三端是否结果一致？SM4 用哪种后端更快？ | 正确性：1,410 条共享向量断言<br>性能：`explicit_iv` CBC 解密，16/128/1,024 B × 1,000–50,000 行，144 次计时查询 | 三端全部通过。1 万行起 WASM 在所有长度最快；1,024 B × 5 万行 WASM 0.611 s、JS 80.3 s、Python 169.0 s。16 B × 1,000 行时 JS 更快 |
| [MD5 内置 vs WASM：1–5 万行](md5-native-vs-wasm/rows-1-50k/REPORT.md)<br>[CSV](md5-native-vs-wasm/rows-1-50k/results.csv) · [JSON](md5-native-vs-wasm/rows-1-50k/results.json) | 已有内置函数时，WASM 慢多少？ | 内置 / WASM MD5 + 两种 identity 基线，16/128/1,024 B × 1–50,000 行，432 次计时查询 | 所有规模内置更快；1,024 B × 5 万行内置 80 ms、WASM 340 ms |
| [MD5 内置 vs WASM：10–100 万行](md5-native-vs-wasm/rows-100k-1m/REPORT.md)<br>[CSV](md5-native-vs-wasm/rows-100k-1m/results.csv) · [JSON](md5-native-vs-wasm/rows-100k-1m/results.json) | 行数增大后，WASM 固定成本是否被摊薄？差距花在哪？ | 内置 / WASM MD5 + 两种 identity 基线，16/128/1,024 B × 10 万/30 万/100 万行，216 次计时查询 | 内置仍更快；1,024 B × 100 万行内置 1,463 ms、WASM 3,676 ms，耗时比约 2.5×。每行 1 KB 时，WASM 每多一行约 3.5 µs，其中数据进出 WASM 约 1.2 µs、MD5 计算约 2.1 µs |
| [max_threads 扩展](max-threads/REPORT.md)<br>[CSV](max-threads/results.csv) · [JSON](max-threads/results.json) | 调大 `max_threads` 有没有提升？ | 内置 / WASM MD5、WASM / JS SM4，1–16 线程，1,024 B × 5 万 / 100 万行与 16 B × 100 万行，Fuse 多块表，200 次计时查询 | 数据量大时提升明显：1,024 B × 100 万行 16 线程下内置 MD5 快 10.6×、WASM SM4 6.3×、WASM MD5 4.8×；5 万行只有 7 个数据块，WASM 最多约 2×。线程越多，内置与 WASM 的差距越大 |

**结论：自定义计算场景下，WASM 是三种 SM4 实现里批量最快的；有语义合适的内置函数时，优先用内置函数。** 图表版的对比和解读见 [三种 UDF 怎么选](../docs/ARCHITECTURE.md)。

## 共同口径

- 环境：AMD Ryzen 9 5950X 单机，Databend Query v1.2.947-nightly，2026-10-19（UTC）测量。
- 设置：`max_threads=1`、`max_block_size=8192`、Memory 表、结果缓存关闭；每组预热 1 次，正式 3 次（SM4）或 5 次（MD5），取中位数。max_threads 报告例外：线程数 1–16，使用多数据块的 Fuse 表，正式 3 次。
- 计时：完整服务端 SQL 耗时，包含扫描、运行时创建/编译、Arrow 转换及 Python RPC；数据准备不计时。
- 未覆盖：并发 QPS、峰值内存、跨机网络/TLS、纯内核计算时间。

详细方法见 [BENCHMARKS](../docs/BENCHMARKS.md)。

## 生成与更新

| 报告目录 | 生成工具 | 原始记录（Git 忽略） |
|---|---|---|
| `sm4-backends/` | `scripts/report_results.py`（`--update-readme` 同步 README 摘要） | `results/` |
| `md5-native-vs-wasm/rows-1-50k/` | `benchmarks/native-vs-wasm/report.py`（默认目录） | `results/native-vs-wasm.json` |
| `md5-native-vs-wasm/rows-100k-1m/` | `benchmarks/native-vs-wasm/report.py --report-dir reports/md5-native-vs-wasm/rows-100k-1m` | `results/native-vs-wasm-large.json` |
| `max-threads/` | `benchmarks/max-threads/report.py` | `results/max-threads.json` |

`REPORT.md` 由同目录的 `results.json` 渲染，单元测试会校验两者一致，请不要手工编辑。重新测量后，运行 `python3 scripts/render_charts.py` 更新文章里的图表。测试矩阵不同时发布到新目录，不要覆盖或拼接旧结果。测试工具和实验源码分别在 [`scripts/`](../scripts/)、[`benchmarks/native-vs-wasm/`](../benchmarks/native-vs-wasm/README.md) 与 [`benchmarks/max-threads/`](../benchmarks/max-threads/README.md)。
