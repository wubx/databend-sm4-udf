# Python UDF Server 部署

## 1. 架构与前置条件

```text
SQL → Databend Query → Arrow Flight RPC → Python UDF Server → gmssl → RPC 结果
```

与内嵌 JS/WASM 不同，Python 代码不在 Query 的 WASM/JS 沙箱里执行。
需要独立进程的发布、网络、访问控制和监控；Query 的线程数也不等于 Python 计算并行度。
本项目使用 gmssl 的原始 SM4 分组原语，在项目代码中统一实现模式和 padding，不调用库的自动二次去填充路径。

准备 Python 3.10+、虚拟环境工具、支持外部 UDF 的 Databend，以及管理员批准的 UDF 地址策略。
本指南分为本机开发示例和生产运行建议；**固定 SDK 默认明文 gRPC，不能把示例直接暴露到公网**。

## 2. 安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.lock
.venv/bin/python -m pip install --no-deps -e python

# 查看命令帮助及依赖
.venv/bin/python -m sm4_udf.server --help
.venv/bin/python -m pip show databend-udf gmssl pyarrow
```

按锁文件复现经过验证的版本；不要在生产原地随意升级 PyArrow、SDK 或密码库。

## 3. 本机测试启动

确认 8815 没有被其他进程占用，然后在 Query 所在机器启动：

```bash
.venv/bin/python -m sm4_udf.server --bind 127.0.0.1:8815
```

另一个终端检查监听（Linux）：

```bash
ss -ltnp | grep ':8815'
```

监听端口只证明进程起来，不证明 Flight schema、网络策略或 SM4 正确；还需要后续注册和 SQL 验证。
`127.0.0.1` 是 **每个发起调用的 Query 节点看到的本机地址**。
如果 Query 在容器、不同机器或多节点 warehouse 中，loopback 通常不是你想连接的服务。

## 4. Databend 网络与安全配置

注册前由管理员确认：

- 目标版本已启用外部 UDF 能力；服务 URL 在允许范围内。
- 每个可能执行查询的 Query 节点都能通过选定地址调用服务。
- URI scheme、TLS 信任链、DNS、网关 HTTP/2/gRPC 转发和防火墙规则匹配。
- 明文仅限批准的隔离本机开发环境；若实例禁止明文，应保留该限制并采用受批准的 TLS/网络方案。

当前 `databend-udf==0.2.20` 的此 CLI 没有原生 TLS 监听选项。
跨机示例中的 `https://...` 代表你**另行配置并验证**的 TLS 终止网关，不是给本 Server 加一个参数就自动有 TLS。
网关的可用性、超时和权限不属于本项目已验证保证。
不要为了跑 demo 全局关闭生产校验。不同平台配置项可能不同，应以所用 Databend 版本/托管平台为准。

## 5. 注册函数

同机、获准明文测试时：

```bash
python3 scripts/generate_sql.py --python-address http://127.0.0.1:8815
bendsql --query="$(<sql/python.sql)"        # 严格接口，2 个函数
bendsql --query="$(<sql/compat_python.sql)" # 字符串策略，4 个函数
```

使用已配置的远端网关时，地址示意：

```bash
python3 scripts/generate_sql.py --python-address https://sm4-gateway.example:443
# 审阅生成文件、确认网关 schema/RPC 可用，再执行上述注册命令。
```

生成器会重写六个 SQL 文件；若本地还有自定义 WASM 路径，需同时传 `--wasm-path`。
这些命令只注册定义，不会启动服务或创建 TLS 网关。创建/验证时实例也可能连接服务，服务必须可达。

## 6. 验证

严格接口：

```sql
SELECT upper(hex(sm4_encrypt_python(
    to_binary('Hello Databend'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
))) AS ciphertext_hex;
-- DA12F33F321D4D551A76D8800F5AE244

SELECT to_string(sm4_decrypt_python(
    unhex('DA12F33F321D4D551A76D8800F5AE244'),
    unhex('0123456789abcdeffedcba9876543210'),
    unhex('00112233445566778899aabbccddeeff'), 'CBC'
)) AS plaintext;
-- Hello Databend
```

字符串策略：

```sql
SELECT upper(hex(sm4_encrypt_explicit_iv_python(
    'Hello Databend', '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'CBC'
))) AS ciphertext_hex;
-- 80ECC1CD2C248143DC470A7D5318EF15

SELECT to_string(sm4_decrypt_explicit_iv_python(
    unhex('80ECC1CD2C248143DC470A7D5318EF15'), '12312313123',
    'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj', 'CBC'
)) AS plaintext;
-- Hello Databend
```

配置客户端 SM4_URL/USER/PASSWORD 指向正确实例后：

```bash
.venv/bin/python scripts/check_deployment.py --impl python
```

## 7. 持续运行

开发可以在 tmux 中前台运行；生产应使用组织已有的进程管理器/容器平台。
systemd 模板如下，需按环境修改：

```ini
[Unit]
Description=Databend SM4 Python UDF Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sm4-udf
Group=sm4-udf
WorkingDirectory=/opt/databend-sm4-udf
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/databend-sm4-udf/.venv/bin/python -m sm4_udf.server --bind 127.0.0.1:8815
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

先创建专用用户、安装代码和依赖并调整路径/服务名；按需要设置 CPU、内存、文件权限和日志策略。
跨机访问应经安全网关/受保护网络，不要为方便直接把明文监听改成公网地址。

```bash
# 假设管理员已保存并审阅 sm4-udf.service
sudo systemctl daemon-reload
sudo systemctl enable --now sm4-udf
sudo systemctl status sm4-udf
journalctl -u sm4-udf --since '10 minutes ago'
```

避免日志包含真实 key/明文。健康检查至少包含真实的测试 SQL 或已验证的 Flight 调用，仅检查端口不够。

## 8. 升级和回滚

1. 保存旧服务镜像/虚拟环境、源代码、schema 和注册 SQL。
2. 新版本先在独立进程/端口通过校验，再按组织发布流程切换路由或注册地址。
3. 验证 BINARY/STRING、NULL 行为及所有模式；更新依赖也视为需要回归的升级。
4. 出问题时恢复旧服务及旧路由/注册 SQL。只回滚 SQL、但服务已被原地覆盖，不能恢复旧逻辑。
5. 确认没有旧调用后再停旧进程；若不再使用函数，先确认业务引用后执行 DROP FUNCTION。

## 9. 常见问题和场景

| 现象 | 检查方向 |
|---|---|
| 连接拒绝/超时 | 服务是否运行、Query 节点视角的 DNS/地址、容器网络、防火墙、超时 |
| 明文被拒绝/地址不允许 | 管理员的 allowlist、TLS 策略；不要在生产直接放宽 |
| schema 不匹配 | SDK/Arrow 版本，实际 HANDLER 导出，BINARY 与 STRING 是否混用 |
| 返回 NULL | 参数/填充校验；与进程崩溃和 RPC 失败区分，后者仍可能使整条查询失败 |
| 多线程后不按比例提速 | Python 解释器、GIL、算法库和 SDK 都会影响，增加 Query 线程不是自动多核 SM4 |
| 查询变慢但 Server CPU 不高 | 检查 SDK、RPC、批次、网络、网关；不能全归因于 SM4 算法 |

优先用于 **Data Pipeline** 中需要 Python 生态、外部依赖、已有业务处理逻辑和独立发布/服务治理的环节，前提是能接受并验证 RPC、SDK 和服务调度成本。
对低延迟查询、逐行 CPU 密集计算或严格吞吐 SLA 的关键路径，不建议采用本项目这种纯 Python 标量实现。
**ELT 中批量、计算密集且不依赖外部服务的 T 更适合 WASM**，轻量转换可用 JS。先考虑内置 SQL/函数，再按计算特点、依赖和治理需求选择扩展方式。

Remote UDF 不提供幂等、背压或 exactly-once。
访问外部系统或产生副作用时，应明确查询重试行为，设计超时、限流、幂等和故障恢复，避免假定每行只被调用一次。

换用原生库、向量化、批处理或服务并发后，需要重新测量。
