# 性能测试方法

本文说明如何复现 SM4 三端性能测试，以及测试遵循的规则。已发布的结果见 [报告索引](../reports/README.md)。

## 运行

前提：所选接口的三端函数都已部署，Python Server 已启动。脚本需要显式指定 `SM4_URL`，会创建一张唯一命名的 Memory 表，退出时删除。它不会注册函数、修改实例安全设置或启动 Databend。

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python scripts/benchmark.py --lengths 16,128,1024 \
  --rows 10000,30000,50000 --modes CBC --operations decrypt --repeats 3
```

`--profile` 选择被测接口：

| profile | 被测函数 | 部署文件 |
|---|---|---|
| `raw`（默认） | 严格字节接口 | `sql/<后端>.sql` |
| `default_iv` | `sm4_*_default_iv_<后端>` | `sql/compat_<后端>.sql` |
| `explicit_iv` | `sm4_*_explicit_iv_<后端>` | `sql/compat_<后端>.sql` |

字符串参数 profile 下，三端收到完全相同的原文 key/IV，并在计时范围内各自完成折叠，调用方不做预处理。不同 profile 的结果不要混在一起比较。

数据量大时 Python 会跑几十分钟，建议在 tmux 里运行，并确认目标是有授权的测试实例。

## 测试规则

- 三端使用相同的接口、key、IV 和 mode，不缓存密钥扩展结果，调用方也不对某一端做特殊编码。
- 固定设置：`max_threads` 由参数指定，`max_block_size=8192`，关闭查询结果缓存。
- 每行明文不同。建表和加密准备在计时前完成，准备阶段用 `sm4_encrypt_wasm`；算法正确性另由 OpenSSL 和公开文档向量独立验证。
- 每个 workload 先预热 1 次，正式轮次按确定的随机顺序依次执行，不并发。
- 用 count/hash 聚合消费返回结果，既防止 UDF 被优化掉，也避免把全部结果传回客户端。
- 每一轮的 checksum 都必须与明文/密文基线一致。
- 计时取服务端时间，包含扫描、hash、运行时创建和编译、Arrow 转换以及 Python RPC；不包含数据准备和 Python Server 启动。
- 结果是单查询延迟，不是并发 QPS，也不是纯 SM4 计算时间。

## 输出

结果默认写到 `results/benchmark.json`，该目录被 Git 忽略。文件包含：

- 引擎和环境设置、源码 SHA256；
- 每一轮的 SQL、query_id、服务端时间、客户端时间和 checksum；
- 每个 workload 的中位数、最小值、最大值和样本数。

只有所有正式轮次都完成，才会写入 `complete=true`。未完成的结果不要当作正式数据发布。附到 issue 或 release 前请检查并脱敏，只使用公开测试 key 和合成数据。

## 生成正式报告

在专用测试实例上运行完整报告矩阵（1,000/10,000/30,000/50,000 行）：

```bash
.venv/bin/python scripts/integration.py --benchmark-smoke --benchmark-report \
  --benchmark-report-rows 1000,10000,30000,50000
```

共 144 次计时查询（36 次预热、108 次正式），主要时间花在 1,024 B 的 Python 用例上，需要几十分钟。其中 `--benchmark-smoke` 会先对三端、三种 profile 跑一个 10 行的 CBC 加解密冒烟测试，确认测试脚本本身工作正常。

原始记录保存在被忽略的 `results/` 里。全部完成后，用 `scripts/report_results.py` 汇总生成 `reports/sm4-backends/` 下的 `REPORT.md`、`results.csv` 和 `results.json`。它会校验完成标志、重复次数、checksum 和源码指纹，任何一项不满足都不会生成报告；加 `--update-readme` 可同时刷新 README 中的摘要。最后运行 `python3 scripts/render_charts.py`，更新 [选型文章](ARCHITECTURE.md) 中的图表。

## WASM 微基准

`wasm/benches/micro.rs` 只测 Rust 实现本身，把当前 `wasm/src/lib.rs` 和冻结的优化前副本 `wasm/benches/baseline.rs` 放在同一进程里对比。它按 UDF 的方式逐行调用函数，所以包含每行的密钥扩展、mode 解析和返回值分配，但不包含 Databend 的运行时创建、Arrow 转换和 SQL 执行。

```bash
# 本机原生
cargo bench --locked --manifest-path wasm/Cargo.toml --bench micro
# 在 wasmtime 中以 wasm32-wasip1 运行，更接近 Databend 的执行环境
CARGO_TARGET_WASM32_WASIP1_RUNNER=wasmtime \
  cargo bench --locked --manifest-path wasm/Cargo.toml --bench micro --target wasm32-wasip1
```

计时前会先逐字节比对两版实现的输出（两类接口、合法与非法 mode、0–80 及更长的输入、合法密文与随机字节），有任何差异就直接失败。加 `-- --quick` 可减少数据量，只用于冒烟检查。微基准的数字说明算法层面的变化，SQL 端到端的效果仍需在测试实例上测量。

## 解读结果

硬件、网络、warehouse、数据块布局、引擎和 SDK 版本、并发度都会影响结果。WASM 的初始化成本在小查询中占比很高，所以没有哪种实现在所有规模下都最快。其他接口、实现或版本测出的数字，不要套用到本接口上。
