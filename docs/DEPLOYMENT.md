# 部署指南：入口与共同约定

从项目根目录运行本文及各实现指南中的命令。先在测试实例验证，不要直接替换生产函数。

| 实现 | 执行位置 | 独立服务 | 详细指南 |
|---|---|---|---|
| JavaScript | Databend Query 内的 JS 运行时 | 无 | [部署 JavaScript](DEPLOY_JS.md) |
| Rust/WASM | Databend Query 内的 WASM 运行时 | 无；需要上传工件 | [部署 WASM](DEPLOY_WASM.md) |
| Python | 外部 Python UDF Server | 有，Arrow Flight RPC | [部署 Python Server](DEPLOY_PYTHON.md) |

架构和选型见 [ARCHITECTURE.md](ARCHITECTURE.md)。

### ELT / Data Pipeline 的选型

三种 UDF 都可以被 SQL 转换作业调用。
已有内置函数满足需求时优先使用；批量 CPU 密集且不依赖外部服务的自定义 T 优先评估 WASM，
轻量转换/快速迭代评估 JS；依赖 Python 生态或独立服务治理时评估 Python Remote UDF。

上线前在目标环境测量源表读取、转换、目标表写入/提交的总耗时，
并验证峰值内存、并发、失败/重试、结果校验及 SLA；调度和 exactly-once 需由作业层提供。

## 1. 确认目标和权限

需要目标版本支持相应 UDF、创建/替换函数的权限；WASM 另需 stage 创建/上传/读取权限。
Python 另需管理员预先配置网络和外部 UDF 安全策略。权限名称和配置入口取决于版本/平台。

```bash
bendsql --query='SELECT version(), current_database();'
```

HTTP 工具使用独立环境变量；**不会自动读取 bendsql 的连接配置**：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''  # 仅本地示例；真实密码使用组织批准的注入方式
```

确认这些变量与 bendsql 指向同一实例、租户和目标上下文。Cloud/远程服务使用真实的 HTTPS 地址和授权身份。
不要把凭证写到 Git、截图、命令历史或公开日志。本文的 loopback/root 示例不用于公网。

Python 工具依赖安装（JS 源码在 Query 中运行不需要这些包；这是客户端工具环境）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.lock
.venv/bin/python -m pip install --no-deps -e python
```

不要在本文尚未运行完的共享测试环境里另起同端口的服务。

## 2. 选择接口，不要混用

| 入口 | 参数 | 规则 |
|---|---|---|
| `sm4_encrypt_<backend>` / `sm4_decrypt_<backend>` | `BINARY,BINARY,BINARY,STRING` | 实际 key 必须 16 B；非 ECB 的 IV 必须 16 B |
| `sm4_encrypt_default_iv_<backend>` / 对应 decrypt | `BINARY,STRING,STRING,STRING` | 原文 key 折叠，支持默认/短 IV |
| `sm4_encrypt_explicit_iv_<backend>` / 对应 decrypt | `BINARY,STRING,STRING,STRING` | 原文 key 折叠，非 ECB IV 至少 16 B，超出截断 |

`<backend>` 为 `js`、`wasm`、`python`。mode 必须显式传入；支持 ECB、CBC、CFB128、OFB。
严格接口见 [API](API.md)，字符串策略及空输入差异见 [COMPATIBILITY](COMPATIBILITY.md)。

生成的 SQL 使用 `CREATE OR REPLACE FUNCTION`：

| 文件 | 替换范围 |
|---|---|
| `sql/js.sql`, `sql/wasm.sql`, `sql/python.sql` | 各 2 个严格接口函数 |
| `sql/compat_js.sql`, `sql/compat_wasm.sql`, `sql/compat_python.sql` | 各 4 个字符串策略函数 |

只执行需要的文件，不必为了用 WASM 而注册 Python。HANDLER 指向实现导出，不能随意改名；
若自定义 SQL 公开名，只改 CREATE FUNCTION 的名字并维护自己的部署文件。

## 3. 部署前备份

```sql
SELECT name, definition
FROM system.user_functions
WHERE name LIKE 'sm4%';
```

把输出及**上一次真正执行过的完整 CREATE FUNCTION SQL**安全保存。
`definition` 列并不一定是一条可直接执行的 CREATE 语句，不要不检查就当回滚脚本运行。
WASM 还需保留旧 stage 工件，Python 需保留旧服务版本及路由；源代码备份不能替代运行环境备份。

本地发布 SQL、验证输出等建议放在被忽略的 `results/`，需要留存的回滚材料另行安全归档。

## 4. 注册后检查

```bash
.venv/bin/python scripts/check_deployment.py --impl js
.venv/bin/python scripts/check_deployment.py --impl wasm
.venv/bin/python scripts/check_deployment.py --impl python
```

只检查已经注册的后端。`--impl all` 要求三端严格函数都存在且 Python Server 可达。
检查器**不创建、不上传、不替换函数**，发现 NULL、错误密文或模式别名不一致时非零退出。

固定的严格接口输入 `Hello Databend`，CBC 期望密文：

```text
DA12F33F321D4D551A76D8800F5AE244
```

字符串入口还需运行各指南提供的 round-trip SQL。WASM 可执行 `tests/compat_smoke.sql` 验证 7 个示例。

检查函数返回类型为 BINARY；客户端可能用 Hex 显示它。复制 Hex 文本回来解密时用 `unhex()`；
如果密文已是 BINARY 列，就直接传列。不要对任意密文调用 `to_string()`。

## 5. 生成器与源码提交

```bash
python3 scripts/generate_sql.py \
  --wasm-path @my_stage/my_version.wasm \
  --python-address https://my-gateway.example:443
```

此命令只生成文件，不访问实例；**每次会重写全部六个 `sql/*.sql`**。按需同时传入两个自定义参数，
避免把另一实现的本地路径/地址意外重置。执行前审阅 SQL，并保存每次发布的版本化副本。

提交源码时不要带个人服务地址、凭证或不可访问的私有 stage。仓库标准文件应恢复为默认生成结果：

```bash
python3 scripts/generate_sql.py
python3 scripts/generate_sql.py --check
```

这只恢复本地文件，不会更改已部署函数。自定义发布 SQL 应留在自己的安全发布记录中。

## 6. 使用和运维边界

- 示例 key/IV 是公开测试数据，不用于真实信息；默认固定 IV 不是推荐的生产 IV 策略。
- 非法输入统一 NULL，业务应统计失败；NULL 不是密文认证或访问控制。
- 关注 Query CPU/内存、运行时限制和 Python RPC 超时；不要依赖本文默认值适配所有工作负载。
- 对混合升级保留回滚路径；不要立即删掉可能仍被查询引用的旧工件/服务。
- 项目采用 MIT，但没有经过密码学安全审计；更多边界见 [SECURITY](../SECURITY.md)。
