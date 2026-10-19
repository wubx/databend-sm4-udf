# 严格字节接口

六个严格接口函数签名相同，后缀只表示执行后端（`js`、`wasm`、`python`），加解密语义完全一致：

```text
sm4_encrypt_js / sm4_decrypt_js
sm4_encrypt_wasm / sm4_decrypt_wasm
sm4_encrypt_python / sm4_decrypt_python

(data BINARY NULL, key BINARY NULL, iv BINARY NULL, mode STRING NULL) -> BINARY NULL
```

如果 key、IV 是普通字符串，用 [字符串参数入口](COMPATIBILITY.md) 更方便。

## 参数

| 参数 | 要求 |
|---|---|
| `data` | 加密时是明文，解密时是原始密文；可以是任意字节，不限于 UTF-8 |
| `key` | 恰好 16 字节。不做密码派生、折叠、补零或 Hex 自动解码 |
| `iv` | CBC/CFB128/OFB 需要恰好 16 字节；ECB 忽略 IV，但不能为 NULL，建议传 `to_binary('')` |
| `mode` | 必须传入，没有默认值，也不读取会话变量 |

## 模式

| 模式 | 可用写法 | 填充 | 输出长度 |
|---|---|---|---|
| ECB | `ECB`、`sm4-ecb`、`SM4_128_ECB` 等 | PKCS#7 | 16 的整数倍 |
| CBC | `CBC`、`sm4-cbc`、`SM4_128_CBC` 等 | PKCS#7 | 16 的整数倍 |
| CFB128 | `CFB128`、`CFB`、`sm4-cfb128` 等 | 无 | 与输入相同 |
| OFB | `OFB`、`sm4-ofb` 等 | 无 | 与输入相同 |

写法规则：可以加 `SM4_` 或 `SM4_128_` 前缀，`-` 和 `_` 等价，ASCII 大小写不敏感；不去除空格。不支持 CTR、GCM、CFB8。

## 填充与长度

- ECB/CBC 加密总是追加一次 PKCS#7 填充，长度为 `n` 的输入得到 `16 × (floor(n / 16) + 1)` 字节。空明文会得到一整块填充。
- ECB/CBC 解密要求密文非空且长度是 16 的倍数，并校验每一个填充字节，只去除一次填充。原始明文以 `01` 或 `02 02` 结尾时也能正确还原。
- CFB128/OFB 不填充，允许最后一块不满 16 字节，空输入得到空 BINARY。
- 每一行独立加解密，IV 和反馈状态在每行重新开始，不会跨行串联。

## NULL 规则

以下情况三端都返回 NULL：

1. 任意参数为 NULL（包括 ECB 用不到的 IV）；
2. mode 不支持；
3. key 或 IV 长度不对；
4. ECB/CBC 密文长度不对或填充非法。

函数名虽然没有 `try_` 前缀，行为上相当于 try 函数：遇到非法输入返回 NULL，而不是报错。ETL 中建议显式统计 NULL 数量，不要静默过滤。合法的空结果是空 BINARY，和 NULL 不同。

运行时故障，比如 WASM trap、资源耗尽、Python 服务或网络故障、SQL 类型转换失败，仍可能让整条查询失败，不会被转换成 NULL。

**结果非 NULL 不能说明 key 正确或数据未被篡改**：用错误的 key 解密 ECB/CBC 时，填充有可能碰巧合法；CFB/OFB 根本没有填充可以校验。

## 编码转换

函数只处理字节，编码由调用方在 SQL 里显式转换：

| 需求 | SQL |
|---|---|
| UTF-8 文本转字节 | `to_binary(text)` |
| Hex 文本转字节 | `unhex(hex_text)` |
| Base64 文本转字节 | `from_base64(base64_text)` |
| 展示密文 | `hex(result)` / `to_base64(result)` |
| 展示确定是 UTF-8 的明文 | `to_string(result)` |

转换失败发生在调用 UDF 之前，按对应 SQL 函数的规则处理。函数内部不做 trim，不猜测 Hex/Base64，不自动解码 UTF-8，也没有空字符串默认 key/IV。

## 函数名

SQL 函数名和实现里的 HANDLER 同名。后缀可以避免与其他函数重名，也便于性能对比。如果只部署一种实现并想换个名字，只改 `CREATE FUNCTION` 后的函数名，不要改 HANDLER。

生成的 SQL 使用 `CREATE OR REPLACE FUNCTION`，执行前请审阅。项目不会自动删除或替换任何实例上的函数。
