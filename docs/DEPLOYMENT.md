# 部署总览

本文介绍三种实现共用的部署步骤：确认权限、选接口、备份、注册后检查。各实现的具体命令见：

| 实现 | 运行位置 | 需要额外部署 | 指南 |
|---|---|---|---|
| JavaScript | Databend Query 内的 JS 运行时 | 无 | [DEPLOY_JS](DEPLOY_JS.md) |
| WASM | Databend Query 内的 WASM 运行时 | 上传 `.wasm` 文件到 stage | [DEPLOY_WASM](DEPLOY_WASM.md) |
| Python | 独立的 Python UDF Server | 运行服务进程 | [DEPLOY_PYTHON](DEPLOY_PYTHON.md) |

不确定选哪种，先看 [三种 UDF 怎么选](ARCHITECTURE.md)。所有命令都在项目根目录执行，建议先在测试实例上走一遍。

## 1. 确认实例和权限

需要的权限：

- 所有实现：创建和替换函数。
- WASM：创建 stage、上传和读取文件。
- Python：管理员预先允许 Query 访问 UDF 服务地址。不同版本和平台的配置方式不同。

先确认 bendsql 连的是目标实例：

```bash
bendsql --query='SELECT version(), current_database();'
```

项目的上传、检查和测试脚本通过 HTTP 访问 Databend，使用独立的环境变量，**不会读取 bendsql 的配置**：

```bash
export SM4_URL=http://127.0.0.1:8000
export SM4_USER=root
export SM4_PASSWORD=''   # 本地示例；真实密码请用组织批准的方式注入
```

确保这些变量和 bendsql 指向同一个实例和租户。云上或远程实例使用实际的 HTTPS 地址和账号。不要把密码写进 Git、截图或公开日志。

安装客户端工具依赖（仅本地脚本需要，Databend 节点上不用装）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.lock
.venv/bin/python -m pip install --no-deps -e python
```

## 2. 选择接口

每种实现都提供两类接口，`<后端>` 是 `js`、`wasm` 或 `python`：

| 接口 | 参数类型 | key / IV 规则 | 部署文件 |
|---|---|---|---|
| `sm4_encrypt_<后端>` / `sm4_decrypt_<后端>` | `BINARY,BINARY,BINARY,STRING` | key 必须 16 字节；除 ECB 外 IV 必须 16 字节 | `sql/<后端>.sql`（2 个函数） |
| `sm4_{encrypt,decrypt}_default_iv_<后端>` | `BINARY,STRING,STRING,STRING` | 原文 key 折叠；IV 可省略或较短 | `sql/compat_<后端>.sql`（4 个函数） |
| `sm4_{encrypt,decrypt}_explicit_iv_<后端>` | 同上 | 原文 key 折叠；IV 至少 16 字节，超出部分截断 | 同上 |

规则细节见 [API](API.md) 和 [COMPATIBILITY](COMPATIBILITY.md)。

只执行需要的文件即可，例如只用 WASM 就不必注册 Python。如果想换一个 SQL 函数名，只改 `CREATE FUNCTION` 后的名字，`HANDLER` 要保持不变，它对应实现里导出的函数。

## 3. 部署前备份

生成的 SQL 使用 `CREATE OR REPLACE FUNCTION`，会覆盖同名函数。先保存现有定义：

```sql
SELECT name, definition
FROM system.user_functions
WHERE name LIKE 'sm4%';
```

回滚时最可靠的是**上一次实际执行过的完整 SQL**，请和查询结果一起保存。`definition` 列不一定能直接当 `CREATE` 语句执行。

另外还要保留运行环境：WASM 保留旧的 stage 文件，Python 保留旧服务版本和路由。只备份源码不够。本地的发布 SQL 和验证输出可以放在 `results/`（已被 Git 忽略）。

## 4. 注册后检查

```bash
.venv/bin/python scripts/check_deployment.py --impl js
.venv/bin/python scripts/check_deployment.py --impl wasm
.venv/bin/python scripts/check_deployment.py --impl python
```

只检查已注册的实现；`--impl all` 要求三端都已部署且 Python 服务可达。这个检查是只读的，用固定输入 `Hello Databend` 验证 CBC 密文和 mode 别名，结果不对时以非零状态退出。期望的严格接口 CBC 密文是：

```text
DA12F33F321D4D551A76D8800F5AE244
```

字符串参数入口可以用各指南里的加解密示例验证，WASM 还可以执行 `tests/compat_smoke.sql`（7 个用例）。

函数返回 BINARY，客户端可能以 Hex 显示。把显示出来的 Hex 复制回来解密时要先 `unhex()`；如果密文本来就存在 BINARY 列里，直接传列即可。

## 5. 自定义 stage 路径和服务地址

`sql/` 下的文件由生成器产生。WASM 文件放在别的 stage 路径，或 Python 服务有其他地址时，重新生成：

```bash
python3 scripts/generate_sql.py \
  --wasm-path @my_stage/my_version.wasm \
  --python-address https://my-gateway.example:443
```

生成器只写本地文件，不访问实例，但**每次都会重写全部六个 SQL 文件**。如果两项都有自定义值，要一起传入，否则没传的那项会被恢复成默认值。执行前请审阅生成的 SQL，并保存这次发布的副本。

提交代码前，把仓库里的 SQL 恢复成默认值，避免把个人地址或私有 stage 提交上去：

```bash
python3 scripts/generate_sql.py
python3 scripts/generate_sql.py --check
```

这只改本地文件，不影响已部署的函数。

## 6. 运维提示

- 非法输入返回 NULL，建议在业务里统计 NULL 数量，及时发现 key、IV 或数据问题。
- 关注 Query 节点的 CPU 和内存，以及 Python RPC 的超时。
- 升级时保留回滚路径，不要马上删除可能仍被引用的旧 WASM 文件或旧服务。
- 示例 key、IV 和默认固定 IV 只用于演示，生产中的 IV 应由业务按模式要求生成。更多安全注意事项见 [SECURITY](../SECURITY.md)。
