# max_threads 扩展实验

其他报告都在 `max_threads=1` 下测量。这个实验只改 `max_threads`（默认 1/2/4/8/16），看内置 MD5、WASM MD5、WASM SM4 和 JS SM4 能否随线程数并行加速，以及线程变多后内置函数与 WASM 的差距怎么变。结果见 [max_threads 扩展报告](../../reports/max-threads/REPORT.md)。

## 和单线程报告的区别

单线程报告从一张 Memory 大表里用 `LIMIT n` 截取不同行数。这里每个规模单独建一张 Fuse 表，按 `ROW_PER_BLOCK = 8192` 写成多个数据块，计时 SQL 不带 `LIMIT`：

```sql
SELECT count(*), sum(siphash64(<表达式>)) FROM <临时表>;
```

这样扫描和 UDF 才能分给多个线程处理。数据块数也会限制并行度：5 万行只有 7 个块，超过 7 个线程就没有更多工作可分。

| 规模 | 实现 |
|---|---|
| 1,024 B × 5 万行 | 内置 MD5、WASM MD5、WASM SM4、JS SM4 |
| 1,024 B × 100 万行 | 内置 MD5、WASM MD5、WASM SM4 |
| 16 B × 100 万行 | 内置 MD5、WASM MD5、WASM SM4 |

SM4 用 `explicit_iv` 字符串入口、CBC 解密。JS 只测 5 万行，单线程约 80 秒。

## 运行

先构建主项目的 SM4 WASM 和 [MD5 实验](../native-vs-wasm/README.md) 的 WASM，然后在专用测试实例上运行：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''
.venv/bin/python benchmarks/max-threads/benchmark.py --threads 1,2,4,8,16 --repeats 3
```

脚本创建带随机前缀的临时函数、表和 stage，结束时（包括出错时）尝试清理。工件不在默认路径时，用 `--sm4-wasm` 和 `--md5-wasm` 指定。1,024 B × 100 万行的表含原文和密文，约 2 GiB。

每个组合预热 1 次、正式 3 次，正式顺序用固定种子打乱。每次查询的 count 和 checksum 都要与预先算好的期望值一致；全部完成且清理成功后，才会把 `REPORT.md`、`results.csv`、`results.json` 发布到 `reports/max-threads/`。

用已有原始记录重新生成报告：

```bash
.venv/bin/python benchmarks/max-threads/report.py --input results/max-threads.json
```
