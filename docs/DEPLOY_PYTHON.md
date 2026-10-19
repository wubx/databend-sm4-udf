# 部署 Python UDF Server

```text
SQL → Databend Query → Arrow Flight RPC → Python UDF Server → gmssl → 结果返回 Query
```

Python 代码跑在独立的服务进程里，需要自己负责发布、网络、访问控制和监控。项目使用 gmssl 的 SM4 分组原语，模式和 padding 由项目代码统一实现，保证和 JS、WASM 结果一致。

需要准备：Python 3.10+，支持外部 UDF 的 Databend，以及管理员允许的 UDF 服务地址。权限、备份和接口选择先看 [部署总览](DEPLOYMENT.md)。

> 服务使用明文 gRPC，示例配置只适合本机测试，**不要直接暴露到公网**。

## 1. 安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.lock
.venv/bin/python -m pip install --no-deps -e python

.venv/bin/python -m sm4_udf.server --help
```

依赖版本按锁文件安装。PyArrow、databend-udf、gmssl 升级都需要重新回归。

## 2. 本机启动

确认 8815 端口空闲，在 Query 所在机器上启动：

```bash
.venv/bin/python -m sm4_udf.server --bind 127.0.0.1:8815
```

另开终端确认在监听（Linux）：

```bash
ss -ltnp | grep ':8815'
```

端口在监听只说明进程起来了，还要注册函数并用 SQL 验证。

注意 `127.0.0.1` 是从 **Query 节点** 看到的本机。如果 Query 跑在容器里、其他机器上，或是多节点 warehouse，就要换成每个 Query 节点都能访问的地址。

## 3. 网络与安全配置

注册函数前，请管理员确认：

- 实例已启用外部 UDF，服务地址在允许列表中。
- 每个可能执行查询的 Query 节点都能访问该地址。
- URI scheme、TLS 证书、DNS、网关的 HTTP/2/gRPC 转发和防火墙配置正确。
- 明文连接只用于隔离的本机开发环境。实例禁止明文时，保持这个限制，改用 TLS 方案。

当前的 `databend-udf==0.2.20` 没有内置 TLS 监听。跨机部署时，需要在服务前面另外配置 TLS 终止网关（比如 Nginx、Envoy），下文示例里的 `https://...` 指的就是这个网关。具体配置项以所用 Databend 版本或托管平台为准，不要为了跑通示例关闭生产环境的安全校验。

## 4. 注册函数

同机测试：

```bash
python3 scripts/generate_sql.py --python-address http://127.0.0.1:8815
bendsql --query="$(<sql/python.sql)"          # 严格接口，2 个函数
bendsql --query="$(<sql/compat_python.sql)"   # 字符串参数入口，4 个函数
```

通过网关访问时，换成网关地址：

```bash
python3 scripts/generate_sql.py --python-address https://sm4-gateway.example:443
```

生成器每次会重写全部六个 SQL 文件，如果 WASM 路径也有自定义值，要同时传 `--wasm-path`。注册函数时实例可能会连接服务，所以服务要先启动。

## 5. 验证

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

字符串参数入口：

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

只读检查（需先配置 `SM4_URL` 等变量）：

```bash
.venv/bin/python scripts/check_deployment.py --impl python
```

## 6. 长期运行

开发时可以在 tmux 里前台运行；生产建议用组织已有的进程管理或容器平台。下面是 systemd 模板，路径、用户和服务名按实际环境调整：

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

先创建专用用户，安装代码和依赖，再按需设置 CPU、内存、文件权限和日志策略：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sm4-udf
sudo systemctl status sm4-udf
journalctl -u sm4-udf --since '10 minutes ago'
```

建议：

- 日志里不要出现真实 key 或明文。
- 健康检查要真正调用一次函数（测试 SQL 或 Flight 调用），只看端口不够。
- 跨机访问走 TLS 网关或受保护网络，不要直接把监听地址改成公网 IP。

## 7. 升级与回滚

1. 保存旧的服务镜像或虚拟环境、源码和注册 SQL。
2. 新版本先用独立进程或端口启动并验证，再切换路由或注册地址。
3. 验证所有模式、BINARY/STRING 和 NULL 行为。依赖升级也按版本升级对待。
4. 出问题时同时恢复旧服务和旧路由/注册 SQL。如果服务已被原地覆盖，只回滚 SQL 是不够的。
5. 确认没有调用后再停掉旧进程。

## 8. 常见问题

| 现象 | 排查方向 |
|---|---|
| 连接被拒绝或超时 | 服务是否在运行；从 Query 节点看地址和 DNS 是否正确；容器网络、防火墙、超时设置 |
| 明文被拒或地址不允许 | 管理员的允许列表和 TLS 策略 |
| schema 不匹配 | SDK 和 Arrow 版本、HANDLER 名称、BINARY 与 STRING 是否用混 |
| 结果为 NULL | 参数或 padding 不合法；进程崩溃、RPC 失败通常会让整条查询报错，而不是返回 NULL |
| 加了 Query 线程也不变快 | Python 的 GIL、算法库和 SDK 都会限制并行度 |
| 查询慢但服务 CPU 不高 | 瓶颈可能在 SDK、RPC、批次大小、网络或网关 |

## 9. 适合的场景

需要 Python 生态、模型、外部依赖或已有业务组件，并且希望独立发布和治理的处理环节。本项目的纯 Python SM4 实现比 JS 和 WASM 都慢，对延迟或吞吐要求高的批量加解密，更适合用 WASM。换成 C 实现的密码库、向量化或批处理后，性能会有明显变化，需要重新测量。

Remote UDF 不提供幂等和 exactly-once 保证。函数如果要写外部系统或产生其他副作用，要考虑查询重试带来的重复调用，自行设计超时、限流和幂等。选型对比见 [三种 UDF 怎么选](ARCHITECTURE.md)。
