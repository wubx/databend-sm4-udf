# JavaScript UDF 部署

## 1. 架构和依赖

```text
SQL → Databend Query → 内嵌 JS 运行时 → SM4 → BINARY 结果
```

不启动外部 Server，不在 Query 节点安装 Node.js/npm。
源码无 Node.js 依赖，通过 CREATE FUNCTION 的 `AS $$...$$` 内联加载。
项目验证环境使用 QuickJS；不要套用 Node.js/V8 的性能假设，也不保证所有 Databend 版本的运行时相同。

准备 bendsql 和支持 JavaScript UDF 的目标实例。生成 SQL 仅需要客户端 Python 3.10+ 的标准库。

## 2. 构建和注册

无需 JS bundler；仓库已提供生成 SQL：

```bash
# 项目根目录；检查提交的 SQL 与源码同步
python3 scripts/generate_sql.py --check

# 需要从修改过的源码重新生成时
python3 scripts/generate_sql.py

# 注册严格字节接口（2 个函数）
bendsql --query="$(<sql/js.sql)"

# 可选：注册两种字符串 key/IV 策略（4 个函数）
bendsql --query="$(<sql/compat_js.sql)"
```

`$(<file)` 是 Bash 写法。不要把 SQL 文件当作 JS 直接执行。
命令会替换对应同名函数；权限、备份和选择接口先看 [共同部署约定](DEPLOYMENT.md)。

## 3. 验证严格接口

```sql
SELECT upper(hex(sm4_encrypt_js(
    to_binary('Hello Databend'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
))) AS ciphertext_hex;
-- DA12F33F321D4D551A76D8800F5AE244

SELECT to_string(sm4_decrypt_js(
    unhex('DA12F33F321D4D551A76D8800F5AE244'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
)) AS plaintext;
-- Hello Databend
```

装好客户端依赖并配置 SM4_URL 后，运行只读检查：

```bash
.venv/bin/python scripts/check_deployment.py --impl js
```

## 4. 验证字符串入口

```sql
SELECT upper(hex(sm4_encrypt_explicit_iv_js(
    'Hello Databend', '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'CBC'
))) AS ciphertext_hex;
-- 80ECC1CD2C248143DC470A7D5318EF15

SELECT to_string(sm4_decrypt_explicit_iv_js(
    unhex('80ECC1CD2C248143DC470A7D5318EF15'), '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'CBC'
)) AS plaintext;
-- Hello Databend
```

默认 IV 策略使用 `sm4_encrypt_default_iv_js` / `sm4_decrypt_default_iv_js`，参数见 [策略说明](COMPATIBILITY.md)。

## 5. 升级与回滚

1. 在专用实例跑共享向量：`node tests/test_js.mjs`、`node tests/test_compat.mjs`；本地测试需要 Node/OpenSSL 支持 SM4。
2. 重新生成 SQL，审阅 diff，保存将要部署的 `js.sql` / `compat_js.sql`。
3. 在目标实例执行所需文件，再执行上述只读检查和业务样本验证。
4. 失败时重新执行**上次部署的旧 SQL**，不要用当前已变化的源码重新生成所谓旧版本。

Node 只是本地测试工具，不是线上运行依赖。不要在并发性能测试时顺便替换线上函数。

## 6. 常见问题

| 现象 | 检查方向 |
|---|---|
| 不识别 `LANGUAGE javascript` | 目标版本/构建能力；确认不是旧实例或错连 endpoint |
| 查询 NULL | key/IV 的字节长度、模式和密文 padding；确认没混用严格/字符串接口 |
| `CBC` NULL、带前缀模式正常 | 已部署旧实现；用只读部署检查定位后重新执行新版 SQL |
| UTF-8 转换报错 | 密文用 `hex()`/`to_base64()` 展示，不用 `to_string()` |
| 本地测试快、Query 慢 | 运行时不同；实际 SQL 含逐行转换、分配和运行时创建，需测目标环境 |
| 函数创建/替换失败 | 权限、函数命名冲突、SQL 是否完整、AS 的 `$$` 是否被 shell 展开 |

## 7. 适用场景

无额外服务、快速部署、定制轻量逻辑，以及本项目测量中初始化开销占主导的小规模查询。
JS 也可用于 ELT / Data Pipeline 的轻量转换和快速迭代。
已有内置能力时优先复用；批量 CPU 密集逻辑评估 WASM，需要 Python 生态/外部依赖时评估 Remote UDF。
大批量 SM4 计算是否换 WASM，以目标实例的实测为准；验收时把读取、转换、写入和失败恢复一并纳入。
