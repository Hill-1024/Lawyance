# 客户部署：远程法条检索

此交付物只包含客户主应用和客户编排模板。法条通过我方独立 HTTPS API 按需查询。客户包和客户镜像不包含 `RAG/`、法律语料、索引、自营 `law_service/` 或私有数据同步凭据。

## 前提

- 已有 Docker Engine、Compose v2、客户自己的业务配置与持久化目录。
- 部署服务器可解析并经 TCP/443 访问发放的法库域名，TLS 证书可验证；模型等其它外部能力按既有配置开放。
- 我方交付的是已验收的 `lawver-customer:<版本>` 镜像（Dockerfile `customer` target），以及单独的介绍页镜像与介绍页发布目录。使用固定版本/摘要。
- 每客户独立 Bearer key。不得把 key 写入 Git、工单、日志、截图或镜像。

下面路径与镜像版本都是示例，需改为当前客户服务器实际值。

## 1. 交付复验

我方在交付前运行 `scripts/package-customer.py --verify <客户归档>`，其 `CUSTOMER-MANIFEST.json` 记录 SHA-256。接收方可对照 manifest 检查传输后完整性；它用于发现损坏，不替代通过可信渠道核验发布摘要。

离线上传镜像归档时先 `docker load -i lawver-customer-<版本>.tar`；从私有仓拉取时使用发放的只读访问凭据。检查实际镜像边界：

```bash
docker run --rm --entrypoint python lawver-customer:RELEASE_TAG \
  -c "from pathlib import Path; p=Path('/app'); assert not any((p/x).exists() for x in ('RAG','law_service','.git','.env')); print('customer image OK')"
```

源码交付需要按 `pyproject.toml`/`uv.lock` 安装 Python 3.13 依赖；前端使用 `pnpm install --frozen-lockfile --ignore-scripts` 后执行 `pnpm exec vite build`。`pnpm build` 会运行只在主仓存在的 Android 同步脚本，客户源码包请使用前述 Web 构建命令。包中 `.env_example` 仅为占位示例。默认归档不带前端 `dist`；我方可在同版本构建后选择交付。服务入口 `python agent.py`，必须使用下节的远程配置。

## 2. 配置业务与网络

在客户服务器创建受限目录（示例 `/etc/lawver-customer`）。把 `.env_example` 复制为 `/etc/lawver-customer/app.env`，由部署管理员编辑，并将属主设为客户镜像实际运行 UID/GID、权限设为 `0600`。不能保留 `root:root 0600`，否则非 root 应用容器无法读取鉴权和业务配置。保留既有账号/模型/其它业务配置，增加：

```dotenv
LAWVER_LAW_SOURCE=remote
LAWVER_LAW_SERVICE_URL=https://law-api.example.invalid
LAWVER_LAW_SERVICE_KEY=REPLACE_WITH_THIS_CUSTOMERS_KEY
LAWVER_LAW_SERVICE_TIMEOUT=10
```

URL 改成发放的真实法库服务域名；不要禁用 TLS 校验。URL 不带账户、密码或路径。不能访问我方 API 的纯离线环境不适用此方案。

法库客户端始终直连，不读取环境代理、`NO_PROXY` 或 `.netrc`；其它模型/搜索客户端
的代理配置按各自规则生效。TLS 默认校验保留；`REQUESTS_CA_BUNDLE` 与
`CURL_CA_BUNDLE` 不用于该法库客户端。若网络强制代理或使用私有 CA，先由部署方
明确配置与验收方案，再接入法库服务。

新业务库首次启动还需要设置至少 32 字符的随机 `SECRET_KEY` 和强随机的
`INITIAL_ADMIN_PASSWORD`，用于初始化用户名为 `admin`、角色为 `sudo` 的账号。
通过 `LAWVER_WORKBENCH_USERS` 显式启用需要使用工作台的账号，例如首次验收设为
`admin`。实际配置只保存在客户的受限 app.env 中。

## 3. 基建与持久化

PostgreSQL、Redis、SearXNG 沿用现有部署；新机器可用 `deploy/docker/compose.infra.yml` 创建。复制 `infra.env.example` 为受限的 `infra.env`，设置强随机数据库口令；复制 SearXNG `settings.yml` 到指定可写配置目录并更改其 `secret_key`。Compose 的 `LAWVER_SEARXNG_DIR` 指向该目录，属主按所用 SearXNG 镜像要求设置（现有模板镜像为 uid 977）。不向公网发布数据库或缓存端口。

```bash
docker compose --env-file /etc/lawver-customer/infra.env \
  -f deploy/docker/compose.infra.yml up -d
```

主应用挂载目录为 `<LAWVER_DATA_HOST_DIR>/{data,TEMP,Result}`；另建 router-state 目录。属主需匹配交付镜像里的实际 uid/gid（`docker run --rm --entrypoint id <客户镜像>` 可查看），不要假定一定是 1000。目录不可被其他非管理员用户读取。介绍页目录沿用独立交付的 `current` 发布结构，宿主挂载路径与容器内路径一致。

## 4. 启动客户实例

复制 `deploy/docker/customer.env.example` 为受限的 `/etc/lawver-customer/compose.env` 并编辑：

- 固定客户镜像和介绍页镜像版本；不能填带本地检索引擎的自营镜像。
- 设置绝对路径、数据库连接、独立 Redis 前缀、空闲端口与不冲突网段。
- `LAWVER_LAW_SERVICE_URL` 与 app.env 的远程服务地址一致。key 只放 app.env。

```bash
docker compose --env-file /etc/lawver-customer/compose.env \
  -f deploy/docker/compose.customer.yml config --quiet
docker compose --env-file /etc/lawver-customer/compose.env \
  -f deploy/docker/compose.customer.yml run --rm --no-deps \
  -w /app/backend --entrypoint alembic app -c alembic.ini upgrade head
docker compose --env-file /etc/lawver-customer/compose.env \
  -f deploy/docker/compose.customer.yml up -d
```

对外入口是回环 `127.0.0.1:<router端口>`，接客户既有 HTTPS 隧道/反向代理。不要叠加自营 Compose，不挂载 `/app/RAG`，不创建法库缓存卷，不执行法库数据同步或预构建脚本。源码部署也不得把本地语料作为兜底。

## 5. 验收与故障处理

检查 `/api/health`、登录、实际对话中的精确法条查询、模糊检索、引用链接。由我方提供独立验收 key 进行 API 的 401/三端点/429 测试，完成后吊销验收 key。确认启动无语料构建和本地索引，网络中断时工具明确报告检索暂不可用；恢复联网后再次验证。

生产入口通过 HTTPS 验证登录。若使用 Python 脚本在应用容器内通过
`http://127.0.0.1:8081` 验收，应在这一回环 HTTP 请求中设置
`X-Forwarded-Proto: http`；应用默认给未声明协议的受信回环请求设置 Secure
Cookie，Python 客户端会拒绝在明文 HTTP 中回传该 Cookie。正式网关按真实访客
协议转发此头，HTTPS 请求继续使用 Secure Cookie。

完整账号/对话/文件/工作区由客户主应用保存。法库请求会发送查询必需的法名、条号、搜索短语或引用文本，其中可能含案件内容；应尽量使用最少上下文。服务审计只保留查询长度和哈希等元信息，不落原文或密钥；代理、隧道和 APM 同样不得记录请求体/Authorization。检索结果可能作为客户业务对话的一部分保存，客户侧不建立单独法库缓存或接收全量语料/索引。

遇到 401 检查 key、403 联系我方检查吊销状态、429 读取 Retry-After 并检查配额、503 检查网络/服务就绪。不要连续重试 401/403/429，也不要把密钥或案件正文粘贴到排障日志。回滚只切回此前已验收的客户镜像和配置，保留远程模式和客户业务数据；按既有数据库迁移备份流程处理 schema 兼容性。
