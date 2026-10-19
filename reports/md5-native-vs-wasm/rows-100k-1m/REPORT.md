# 内置 MD5 与 WASM MD5：10–100 万行

**状态：完整测试已结束，所有结果校验一致。** MD5 仅作为计算样本，不用于安全用途。1–5 万行见 [小规模报告](../rows-1-50k/REPORT.md)，两轮独立测量；多线程见 [max_threads 扩展](../../max-threads/REPORT.md)；其他报告见 [报告索引](../../README.md)。

## 1. 对比什么

- 内置：`md5(data)`，Query 原生 Rust 表达式内执行。
- WASM：`md5_wasm(data)`，`md-5 = 0.10.6`、同一算法库，输出相同的小写 32 字符 Hex STRING。
- SQL 基线：直接返回 `data`，无 UDF、无 MD5。
- WASM identity：`identity_wasm(data)`，不计算 MD5，仅按相同 STRING ABI 返回输入。
- 实际测试注册唯一前缀的临时名字，不替换内置函数或当前 SM4 函数。输入均 STRING，NULL 向下传播。

库版本对齐依据本地 Databend 源码和 Cargo.lock，未重编译原生 Query。Native 与 WASM 的 target/编译配置、内存/结果构建路径不同：原生按列写入结果 buffer，WASM 标量返回 String。

## 2. 环境与方法

| 项目 | 值 |
| --- | --- |
| Databend | Databend Query v1.2.947-nightly-f3733a6b32(rust-1.100.0-nightly-2026-09-21T02:16:50.512714833Z) |
| CPU | AMD Ryzen 9 5950X 16-Core Processor |
| 逻辑 CPU | 32 |
| Query max_threads | 1 |
| max_block_size | 8192 |
| 表引擎 | Memory |
| 结果缓存 | 关闭 |
| Rust | rustc 1.97.1 (8bab26f4f 2026-07-14) |
| 开始 UTC | 2026-10-19T15:04:10.054676+00:00 |
| 结束 UTC | 2026-10-19T15:05:44.379062+00:00 |

- 输入长度 `[16, 128, 1024]` B，行数 `[100000, 300000, 1000000]`；由带行号的 `Hello Databend` 模式生成，截断/重复到目标字节数。
- 每组预热 1 次，正式 5 次；正式顺序用固定种子打乱，取服务端 SQL 中位数。
- 准备数据、上传/注册不计时；每次 SQL 的 WASM 初始化/编译、Arrow 转换、扫描/hash 聚合都计时。
- `count(*)` 和 `sum(siphash64(result))` 消费结果，避免表达式被裁剪，且不返回大结果集到客户端。
- MD5 两端每次 checksum 与原生预计算值一致；identity 两端每次与原文 checksum 一致。
- 27 个空值/空串/标准文本/中文/emoji/零字节/长度边界用例，对照 Python hashlib 独立期望。
- 每种长度另抽查最多 257 行逐行结果；计时中校验完整数据的 count/hash。
- 共 216 次计时查询；原始记录在忽略的 results/ 下，脱敏快照为 results.json。

## 3. 完整 SQL 耗时中位数（毫秒）

| 输入 B/行 | 行数 | 内置 md5 | WASM md5 | WASM/内置耗时 |
| --- | --- | --- | --- | --- |
| 16 | 100,000 | 21 | 170 | 8.1× |
| 16 | 300,000 | 47 | 243 | 5.2× |
| 16 | 1,000,000 | 147 | 466 | 3.2× |
| 128 | 100,000 | 38 | 204 | 5.4× |
| 128 | 300,000 | 97 | 342 | 3.5× |
| 128 | 1,000,000 | 316 | 812 | 2.6× |
| 1024 | 100,000 | 156 | 511 | 3.3× |
| 1024 | 300,000 | 446 | 1218 | 2.7× |
| 1024 | 1,000,000 | 1463 | 3676 | 2.5× |

最后一列越大表示 WASM 相对耗时越高；极小查询受毫秒计时精度、调度和固定成本影响较大。

## 4. 无 MD5 计算的基线（毫秒）

| 输入 B/行 | 行数 | SQL 原文基线 | WASM identity |
| --- | --- | --- | --- |
| 16 | 100,000 | 8 | 141 |
| 16 | 300,000 | 10 | 156 |
| 16 | 1,000,000 | 19 | 205 |
| 128 | 100,000 | 10 | 159 |
| 128 | 300,000 | 15 | 188 |
| 128 | 1,000,000 | 38 | 300 |
| 1024 | 100,000 | 25 | 323 |
| 1024 | 300,000 | 66 | 611 |
| 1024 | 1,000,000 | 199 | 1588 |

Identity 用于观察执行边界开销。MD5 输出固定 32 字符，identity 输出与输入等长，两者输出量和内存分配不同。

## 5. 耗时拆分（每增加一行的微秒数）

取 100,000 → 1,000,000 行的中位数差除以增加的行数，固定开销在相减时抵消。数据进出 WASM ≈ WASM identity − SQL 基线；WASM MD5 计算 ≈ WASM MD5 − WASM identity；内置 MD5 计算 ≈ 内置 MD5 − SQL 基线。

| 输入 B/行 | 内置 MD5 | WASM MD5 | 其中：数据进出 WASM | 其中：WASM MD5 计算 | 内置 MD5 计算 |
| --- | --- | --- | --- | --- | --- |
| 16 | 0.14 | 0.33 | 0.06 | 0.26 | 0.13 |
| 128 | 0.31 | 0.68 | 0.13 | 0.52 | 0.28 |
| 1024 | 1.45 | 3.52 | 1.21 | 2.11 | 1.26 |

这是近似拆分：identity 返回与输入等长的结果，MD5 只返回 32 字符，两者的输出拷贝量不同，短输入时差值可能偏小甚至为负。

## 6. 正式测量 min–max（毫秒）

| 输入 B/行 | 行数 | 内置 md5 范围 | WASM md5 范围 |
| --- | --- | --- | --- |
| 16 | 100,000 | 19–22 | 163–176 |
| 16 | 300,000 | 45–49 | 233–251 |
| 16 | 1,000,000 | 142–151 | 459–474 |
| 128 | 100,000 | 38–40 | 202–220 |
| 128 | 300,000 | 94–100 | 340–347 |
| 128 | 1,000,000 | 310–322 | 804–840 |
| 1024 | 100,000 | 151–157 | 494–670 |
| 1024 | 300,000 | 441–453 | 1210–1248 |
| 1024 | 1,000,000 | 1427–1485 | 3560–3755 |

## 7. 如何解读

- 原生内置函数没有 WASM 边界，能直接使用 Query 的列式执行和结果 buffer；已有语义满足需求时应优先使用内置函数。
- WASM 比当前纯 Python/JS SM4 快，但比原生函数慢。
- 小规模由 WASM 固定成本主导；更大输入会摊薄固定成本，逐行 ABI、分配和编译 target 的差异仍然存在。
- 计时为完整 SQL；未测并发 QPS、冷进程启动或纯计算占比。多线程结果见 [max_threads 扩展](../../max-threads/REPORT.md)。
- 单机共享开发环境、单线程设置、没有绑核；硬件/版本/数据变化后需重新测量。

## 8. 复现

```bash
# 项目根目录；不改变主 SM4 工件
rustup target add wasm32-wasip1
cargo test --locked --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml
cargo build --locked --release --target wasm32-wasip1 \
  --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python benchmarks/native-vs-wasm/benchmark.py \
  --rows 100000,300000,1000000 --lengths 16,128,1024 --repeats 5 \
  --output results/native-vs-wasm-large.json \
  --report-dir reports/md5-native-vs-wasm/rows-100k-1m
```

需要管理员批准的专用测试节点、UDF/stage/Memory 表权限；脚本不会改安全配置。设置了 CARGO_TARGET_DIR 时，通过 `--wasm-file` 指定真实工件路径。结束时清理临时函数/表/stage；失败或强制 kill 后需按日志确认残留。1,024 B × 100 万行仅原文就约 0.95 GiB，identity 还会返回等长结果，应预留足够内存。不要未经批准在生产执行。

使用已完成的原始数据重新生成：

```bash
.venv/bin/python benchmarks/native-vs-wasm/report.py \
  --input results/native-vs-wasm-large.json \
  --report-dir reports/md5-native-vs-wasm/rows-100k-1m
```

WASM SHA256：`0d90342bf4926265357099ddf0762b78b0df5025f83eea0080552bd9bebac552`。源码、Cargo.lock、工具链指纹和逐次计时见 [results.json](results.json)。
