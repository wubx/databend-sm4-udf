# MD5 对照实验：内置函数 vs WASM UDF

WASM 比 JS、Python 快，那和 Databend 的原生内置函数比呢？SM4 没有内置版本，所以这个实验改用 MD5：用同一个算法库、同样的输入输出，分别跑内置 `md5()` 和 WASM 版本，比较完整 SQL 的耗时。

实验是独立的 Cargo 工程，不影响主项目的 SM4 WASM。这里只放源码和工具，结果见：

- [1–5 万行报告](../../reports/md5-native-vs-wasm/rows-1-50k/REPORT.md)
- [10–100 万行报告](../../reports/md5-native-vs-wasm/rows-100k-1m/REPORT.md)

MD5 只是一个容易验证的计算样本，不要用于密码、签名等安全用途。

## 对比对象

| 名称 | 做什么 |
|---|---|
| `md5(data)` | Databend 内置函数 |
| `md5_wasm(data)` | `md-5 0.10.6` 编译为 WASI，同样返回 32 个字符的小写 Hex |
| SQL identity | 直接返回输入，不调用 UDF |
| `identity_wasm(data)` | 经过 WASM 但直接返回输入，不计算摘要 |

`md-5` 的版本参照 Databend 源码中的 `Cargo.lock` 选定，没有重新编译 Databend。两边仍有差异：内置函数按列写入结果，WASM 逐行返回 String，编译目标和调用接口也不同。

两个 identity 基线用来观察“经过 WASM 边界本身”的开销。报告用它们做近似的耗时拆分：按每增加一行的耗时，把 WASM MD5 分成“数据进出 WASM”和“MD5 计算”两部分。identity 的输出和输入一样长，而 MD5 输出固定 32 个字符，所以这个拆分只是估算。

## 构建

在项目根目录执行，需要 Rust 和 `wasm32-wasip1` 目标：

```bash
rustup target add wasm32-wasip1
cargo test --locked --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml
cargo build --locked --release --target wasm32-wasip1 \
  --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml
```

Python 客户端环境的安装见 [部署总览](../../docs/DEPLOYMENT.md)。实验不需要 Python UDF Server，Python 只用来发 SQL、计时和核对 MD5 结果。

## 运行

需要 Databend 的 UDF、stage 和 Memory 表权限，请在专用测试实例上运行：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python benchmarks/native-vs-wasm/benchmark.py
```

默认矩阵是 16/128/1,024 B × 1/100/1,000/10,000/30,000/50,000 行，四种执行路径，每组预热 1 次、正式 5 次，共 432 次计时查询。单线程，使用 Memory 表，关闭结果缓存。

脚本会上传 `.wasm`，创建带随机前缀的临时函数、表和 stage，结束时（包括出错时）尝试清理。如果进程被强制终止，请根据日志检查是否有残留。设置了 `CARGO_TARGET_DIR` 的话，加上 `--wasm-file /实际路径/databend_native_vs_wasm.wasm`。

### 扩大到 10–100 万行

同样跑四种执行路径，只是换成更大的行数：

```bash
.venv/bin/python benchmarks/native-vs-wasm/benchmark.py \
  --rows 100000,300000,1000000 --lengths 16,128,1024 --repeats 5 \
  --output results/native-vs-wasm-large.json \
  --report-dir reports/md5-native-vs-wasm/rows-100k-1m
```

共 216 次计时查询（36 次预热、180 次正式）。`--report-dir` 让结果写到独立目录，不覆盖默认矩阵的报告。只想比较两种 MD5 时加 `--md5-only`，跳过 identity 基线。

1,024 B × 100 万行光原文就约 0.95 GiB，identity 还会返回等长的结果，加上运行时和中间结果，需要预留足够内存。

多线程下的对比在另一个实验里：[max_threads 扩展](../max-threads/README.md)。

## 报告

报告统一发布在 [`reports/md5-native-vs-wasm/`](../../reports/README.md)：默认矩阵写入 `rows-1-50k/`，大行数矩阵写入 `rows-100k-1m/`。每个目录包含：

- `REPORT.md`：环境、耗时中位数、波动范围、基线和解读；
- `results.csv`：汇总数据；
- `results.json`：脱敏后的逐次计时，可以提交到仓库。

只有全部轮次完成、checksum 一致且清理成功，才会发布这些文件。包含 SQL 和 query_id 的原始记录保存在被忽略的 `results/` 下。

用已有的原始记录重新生成报告：

```bash
.venv/bin/python benchmarks/native-vs-wasm/report.py \
  --input results/native-vs-wasm.json
```

测试注册的函数名带随机前缀，测试结束后就被删除了。如果想手动调用，需要自己上传 `.wasm` 并注册对应导出。
