# Native vs WASM：MD5 对照实验

目的：比较 Databend **原生内置函数**与 **WASM UDF** 的完整 SQL 执行成本。
独立于主 SM4 实现，使用单独的 Cargo 工程和工件，不向 SM4 WASM 添加无关的密码导出。
本目录只放实验源码和工具；已发布的结果见 [1–5 万行](../../reports/md5-native-vs-wasm/rows-1-50k/REPORT.md)
与 [10–100 万行](../../reports/md5-native-vs-wasm/rows-100k-1m/REPORT.md) 报告。

MD5 仅作易验证的性能样本，不推荐用于密码、签名或其他安全用途。

## 实现与基线

| 名称 | 计算 |
|---|---|
| `md5(data)` | 原生内置函数 |
| `md5_wasm(data)` | `md-5 0.10.6` 编译为 WASI，返回同样的 32 字符小写 Hex |
| SQL identity | 直接返回输入，无 UDF |
| `identity_wasm(data)` | WASM 直接返回输入，不计算摘要 |

库版本对齐参考本地 Databend 源码及 Cargo.lock，未重编译原生 Query。
Native 的列式结果 buffer、WASM 的 String 分配、target 和 ABI 仍不同。

Identity 基线可观察固定执行成本，但输出长度不同，不能直接相减就当作精确的 MD5 计算成本。
本实验不比较 JS/Python，不修改当前已部署的 SM4 函数，不声称能推导出原生 SM4 的性能。

## 准备与构建

从 Repo 根目录运行。需要 Rust/WASI、Python 客户端依赖、Databend UDF/stage/Memory 权限：

```bash
rustup target add wasm32-wasip1
cargo test --locked --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml
cargo build --locked --release --target wasm32-wasip1 \
  --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml
```

部署 Python 工具环境见 [部署总览](../../docs/DEPLOYMENT.md)。本实验不启动 Python UDF Server，
Python 仅用于发起 SQL、组织计时及独立核对 MD5 结果。

## 运行

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python benchmarks/native-vs-wasm/benchmark.py
```

设置了 CARGO_TARGET_DIR 时，另传 `--wasm-file /actual/path/databend_native_vs_wasm.wasm`。
默认矩阵：16/128/1,024 B × 1/100/1,000/10,000/30,000/50,000 行，四种执行路径，
每组预热一次、正式五次，共 432 次计时查询。单线程、Memory 数据、结果缓存关闭。

测试专用节点：脚本创建唯一前缀的临时函数/表/stage，会读取和上传工件、执行真实 SQL，正常及异常退出均尝试清理。
不要未经批准在生产执行；强制终止进程后，按原始日志确认是否有残留。

## 只比较 MD5，扩大到十万／百万行

**已完成**：[大行数报告](../../reports/md5-native-vs-wasm/rows-100k-1m/REPORT.md)。
本次全部规模原生仍更快，1,024 B × 100 万行：内置 1,471 ms、WASM 3,730 ms。
这与固定成本占比下降的预期相符，但不能精确分离模块加载和其他成本。

`--md5-only` 只注册并调用 WASM MD5，不运行 SQL/WASM identity。可以将行数提高到
100,000、300,000、1,000,000，保持相同字段长度和正式五次测量：

```bash
.venv/bin/python benchmarks/native-vs-wasm/benchmark.py --md5-only \
  --rows 100000,300000,1000000 --lengths 16,128,1024 --repeats 5 \
  --output results/native-vs-wasm-large.json \
  --report-dir reports/md5-native-vs-wasm/rows-100k-1m
```

这轮共 108 次计时查询（18 次预热、90 次正式测量）。
`--report-dir` 将已完成报告写入独立目录，保留此前小规模的四路径报告。
若用自定义构建目录，请照常补充 `--wasm-file`。

1,024 B × 100 万行仅原文就约 0.95 GiB，加上其他长度的输入表、运行时和中间结果，
需预留充足内存；表使用 Memory，引入更大数据时应先确认资源和测试实例授权。
固定加载成本占比可能随行数下降，但剩余差距仍包含逐行 ABI/结果分配、编译 target 及算法成本。
本轮不新增 identity 测量，更不能用两轮不同规模的耗时直接相减就认定纯内核时间。

## 结果与报告

报告不放在本目录，统一发布到 [`reports/md5-native-vs-wasm/`](../../reports/README.md)：
默认矩阵写入 `rows-1-50k/`，大行数矩阵通过 `--report-dir` 写入 `rows-100k-1m/`。每个目录包含：

- `REPORT.md`：环境、耗时中位数、min/max、identity 基线及解释边界。
- `results.csv`：汇总。
- `results.json`：脱敏快照和逐次计时，适合随 Repo 提交。

以上文件**只在全部轮次完成、checksum 一致且清理成功后发布**。
原始 SQL/query_id 等保存在忽略的 `results/native-vs-wasm.json`，不要把不完整结果当成结论。

再次生成报告：

```bash
.venv/bin/python benchmarks/native-vs-wasm/report.py \
  --input results/native-vs-wasm.json
```

注册的实际名字带随机前缀，不能直接复用脚本中的公开示意名。若要手动调用，需自行上传并注册对应导出。
