# Docker Compose 部署手册

面向在部署机上工作的执行者（人或 agent）。这份文档讲**容器化部署**；
原来的 systemd 三件套（[README 部署拓扑](../README.md)、[deployment.md](deployment.md)）仍然有效，
两者可以并存，按本文第 8 节切换与回滚。

## 0. 一句话

一份 compose 起一个实例，**宿主只发布一个端口**（实例网关，隧道指向它）；
一台机器可以跑多个实例，PostgreSQL / Redis / SearXNG 全机共享一套。

## 1. 为什么这样切

改造前一台机器上是三个 systemd 单元 + 一堆回环端口：

| | 改造前（systemd） | 改造后（compose） |
|---|---|---|
| 分流核心 | 宿主 127.0.0.1:8080 | 容器内 8080，**发布到宿主**（唯一端口） |
| 功能页 | 宿主 127.0.0.1:8081 | 容器内 8081，**不发布** |
| 介绍页 | 宿主 127.0.0.1:8082 | 容器内 8082，**不发布** |
| PostgreSQL | 宿主 127.0.0.1:5432 | 容器内 5432，**不发布**（原有发布取消） |
| SearXNG | 宿主 127.0.0.1:8083 | 容器内 8080，**不发布**（原有发布取消） |
| Redis | 可选，宿主 6379 | 容器内 6379，**不发布** |
| 一个实例占用的宿主端口 | 5～6 个 | **1 个** |

多出来的能力：同一台机器再起一个实例，只需要另一个发布端口——容器内部的
8080/8081/8082 各在自己的网络命名空间里，**多实例之间天然不冲突**。

## 2. 拓扑

```
                         隧道（Cloudflare Tunnel 等）
                                   │
                       127.0.0.1:${LAWVER_ROUTER_PUBLISH_PORT}
                                   │
   ┌───────────────────────────────┴────────────────────────────────┐
   │  实例（compose 项目名 = 实例名，每实例一套）                     │
   │                                                                │
   │   router ──┬── http://app:8081    （功能页，FastAPI + dist/）    │
   │   8080     └── http://intro:8082  （介绍页，静态 + current 链接）│
   └───────────────────────────────┬────────────────────────────────┘
                                   │  lawver-infra 网络（external）
   ┌───────────────────────────────┴────────────────────────────────┐
   │  共享基建（compose 项目 lawver-infra，全机一套）                 │
   │   postgres:5432    redis:6379    searxng:8080                  │
   └────────────────────────────────────────────────────────────────┘
```

功能页同时挂在两张网上：自己的实例网（给核心访问）与基建网（按服务名解析
`postgres`/`redis`/`searxng`）。核心只挂实例网——它不该直接连数据库。

## 3. 文件清单

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 功能页镜像（前端 vite 产物 + uv 依赖 + 运行层）。**一个镜像两个 command**：核心用 `command` 覆盖起 `router.py` |
| `compose.infra.yml` | 全机共享基建（PG + Redis + SearXNG），不发布任何宿主端口 |
| `compose.yml` | 实例主体（核心 + 功能页 + 介绍页） |
| `compose.self-hosted.yml` | 自营 overlay：只读挂载语料，法条检索走本地法库 |
| `compose.frontier.yml` | 前沿 overlay（如 2B 合约部署到律所）：不带语料，远程检索 |
| `compose.env.example` | 实例作用域变量模板（端口、网段、路径、Redis 前缀） |
| `infra.env.example` | 基建作用域变量（PG 口令、SearXNG 配置目录） |
| `new-instance.sh` | 建实例：挑不冲突的端口/网段/前缀，生成 compose.env 与 run.sh |
| `build.sh` | 构建镜像（自动取 `lawver` 用户的 uid/gid） |
| `prebuild-law-db.sh` | 在实例的法库卷里预建索引 |
| `rehearsal.sh` | 容器版彩排：起整套并跑与进程版**同一批断言** |
| `verify-on-server.sh` | 部署机验收：基建 + 自营实例 + 法库 + 多实例 + 介绍页热切换 |
| `searxng/settings.yml` | SearXNG 配置模板（含 `formats: [html, json]`） |

介绍页镜像定义在介绍页仓：`Lawyance_Intro/Dockerfile`（只装 `server/serve.py`）。

## 4. 前置条件

- Docker Engine + Compose v2（部署机实测 Docker 29.8.1 / Compose v5.5.1）。
- 存在 `lawver` 用户；**容器内运行用户就是它的 uid/gid**（部署机实测 996/993，
  不是 1000）。`build.sh` 会自动取，`new-instance.sh` 会从镜像里读。
- 镜像二选一：
  - 拉 GHCR：tag `v*.*.*` 触发 `.github/workflows/docker-images.yml` 推
    `ghcr.io/hill-1024/lawver-app`（介绍页仓推 `lawver-intro`）。私有仓需 `docker login ghcr.io`。
  - 本地构建：`INTRO_REPO=/srv/lawver-intro ./build.sh`（产出 `lawver-app:local` / `lawver-intro:local`）。

## 5. 首次部署

### 5.1 起共享基建（一台机器只做一次）

```bash
cd deploy/docker
cp -n infra.env.example infra.env && chmod 600 infra.env
openssl rand -base64 24          # 填进 LAWVER_POSTGRES_PASSWORD
mkdir -p /srv/lawver-searxng
cp -n searxng/settings.yml /srv/lawver-searxng/
sed -i "s/REPLACE_WITH_RANDOM_HEX/$(openssl rand -hex 32)/" /srv/lawver-searxng/settings.yml
chown -R 977:977 /srv/lawver-searxng        # SearXNG 容器以 uid 977 运行
LAWVER_SEARXNG_DIR=/srv/lawver-searxng docker compose --env-file infra.env -f compose.infra.yml up -d
docker compose --env-file infra.env -f compose.infra.yml ps
```

**验收**：`postgres` 与 `redis` 显示 `(healthy)`；`searxng` 起来；
`docker ps` 里这三个**都没有宿主端口映射**。

### 5.2 建实例

```bash
./new-instance.sh main 8080        # 第二个实例再跑一次，换个端口
```

它会：挑一个空闲宿主端口与未占用的网段（默认从 `10.42.0.0/24` 起）、生成
`/srv/lawver-instances/<名字>/{compose.env,run.sh}`、建好 `data/{data,TEMP,Result}` 与
`state/router` 并把属主改成容器用户、把数据库口令继承自 `infra.env`。

**验收**：输出里的端口、网段、Redis 前缀互不冲突；`compose.env` 的
`LAWVER_DATABASE_URL` 口令与 `infra.env` 一致。

### 5.3 起实例

```bash
/srv/lawver-instances/main/run.sh up -d              # 自营（挂语料）
/srv/lawver-instances/main/run.sh up -d --frontier   # 前沿（不挂语料）
/srv/lawver-instances/main/run.sh ps
```

首次 `up` 会在法库卷里建索引。**实测（2 核部署机）：建库 14 秒**（4937 个源文件、
197MB `law.db`），索引就绪后再启动只需 12～31 秒。想更早拿到索引可预建：

```bash
./prebuild-law-db.sh /srv/lawver-instances/main
```

**验收**：

```bash
PORT=8080
curl -s -o /dev/null -w 'core:%{http_code}\n'  http://127.0.0.1:$PORT/__core/status   # 200
curl -s -o /dev/null -w 'app:%{http_code}\n'   http://127.0.0.1:$PORT/api/health      # 200
curl -s http://127.0.0.1:$PORT/__core/status | python3 -m json.tool                   # 两侧 up:true
curl -s -o /dev/null -D - http://127.0.0.1:$PORT/ | grep -i x-core-upstream           # intro
ss -ltnp | grep $PORT                                                                 # 只有这一个
```

### 5.4 隧道

隧道仍指向 `http://127.0.0.1:${LAWVER_ROUTER_PUBLISH_PORT}`。
**不要把隧道指向容器里的 8081/8082** —— 它们连宿主端口都没有。

## 6. 多实例

一台机器上多实例的做法就是"再跑一次 `new-instance.sh`"，需要各不相同只有三样：

| 项 | 变量 | 冲突后果 |
|---|---|---|
| 宿主发布端口 | `LAWVER_ROUTER_PUBLISH_PORT` | 起不来（端口被占） |
| 实例网段 | `LAWVER_NETWORK_SUBNET` | 起不来（ipam 网段重叠） |
| Redis 前缀 | `LAWVER_REDIS_PREFIX` | **不报错但更糟**：限流计数与登录节流互串 |

`new-instance.sh` 会校验这三项并拒绝重复。数据、卷、容器名、网络都由
`COMPOSE_PROJECT_NAME` 隔离，不需要手工区分。

**共享 Redis 的注意点**：前缀重了不会立刻出问题，症状是"限流看起来没生效"或
"另一个实例的用户被误伤"。`new-instance.sh` 在生成时就直接拒绝。

## 7. 配置怎么放

两层分工，刻意不混：

- **应用业务配置**仍写在应用的 `.env` 里（LLM 密钥、得理/企查查令牌、限流参数……），
  由 `LAWVER_APP_ENV_FILE` 指向并**只读**挂进容器 `/app/.env`。与 systemd 单元
  "刻意不用 EnvironmentFile"同一条理由：单一事实来源。
- **容器拓扑**由 compose 的 `environment:` 给：`LAWVER_HOST=0.0.0.0`（容器内必须，
  systemd 那份 `127.0.0.1` 在容器里不可达）、数据库/Redis/SearXNG 的服务名、
  `LAWVER_TRUSTED_PROXY_CIDRS=${LAWVER_NETWORK_SUBNET}`。python-dotenv 不覆盖已存在的
  环境变量，所以拓扑项不会被 `.env` 顶掉。
- **实例作用域**（端口、网段、路径、Redis 前缀）放 `compose.env`，用 `--env-file` 传；
  它与应用的 `.env` 是**两个文件**。

`LAWVER_TRUSTED_PROXY_CIDRS` 必须覆盖核心容器所在的网段，否则限流与访问日志拿不到
真实客户端 IP（`CF-Connecting-IP` 只在直连对端是可信代理时才采信）。这里用同一个
`LAWVER_NETWORK_SUBNET` 喂网络 `ipam` 与该变量，两处不可能漂移。

## 8. 从 systemd 切换 / 回滚

切换前提：容器版彩排与验收都绿。切换步骤（以现有机器为例）：

```bash
# 1. 停三件套（保留 unit 文件，随时能回滚）
sudo systemctl stop lawver-router lawver-app lawver-intro
# 2. 起共享基建与实例（端口沿用原来的 8080，隧道不用改）
cd /srv/lawver/deploy/docker && docker compose --env-file infra.env -f compose.infra.yml up -d
/srv/lawver-instances/main/run.sh up -d
# 3. 验收（第 5.3 节那几条），再把隧道/反代保持指向 127.0.0.1:8080
```

**回滚**：`run.sh down` + 基建 `down`，再 `sudo systemctl start lawver-router lawver-app lawver-intro`。
systemd 单元与 `/srv/lawver` 目录都保留不动。

注意：容器版与 systemd 版**不能同时监听同一个宿主端口**。回滚前先 `down`。

## 9. 日常维护

| 事情 | 命令 |
|---|---|
| 更新应用镜像 | `docker compose ... pull` 或本地 `./build.sh --tag <版本>`，再 `run.sh up -d` |
| 应用迁移 | `run.sh exec app sh -c 'cd backend && alembic -c alembic.ini upgrade head'` |
| 介绍页换版 | 在宿主 `cd /srv/lawver-intro && tools/build.sh`（**容器不用重启**，符号链接原子翻转） |
| 语料更新 | `git -C <语料检出> pull`，再 `run.sh restart app`（启动期扫描会走增量） |
| 备份 | `run.sh exec app python -m workbench.maintenance backup /app/data/backup`（镜像里装了 `postgresql-client`；基建不发布 5432，备份只能在容器内做） |
| 计划维护 | `touch /srv/lawver-instances/main/state/router/app.maintenance`（核心照旧认这个标志位） |
| 看日志 | `run.sh logs -f app` / `router` / `intro` |
| 数据库 shell | `docker compose --env-file infra.env -f compose.infra.yml exec postgres psql -U lawver -d lawver` |

## 10. 故障排查

| 症状 | 原因与处理 |
|---|---|
| 功能页容器反复重启，日志 `PermissionError: Operation not permitted: '/app/data'` | 宿主 `data` 目录属主不是容器用户。`new-instance.sh` 以 root 跑时会自动 chown；手工建的目录执行 `chown -R 996:993 <实例目录>/data`（uid 以 `docker run --rm --entrypoint id <镜像> -u` 为准） |
| 核心重启，日志 `Permission denied: '/state/app.maintenance'` | 同上，状态目录属主要对 |
| 介绍页整站 404，日志 `构建产物不存在：.../current` | `current` 符号链接的目标不在挂载树内。`tools/build.sh` 建的是**绝对**链接（指向 `<仓库>/releases/<时间戳>`），compose 因此把仓库挂在与宿主**完全相同的路径**上。链接指向树外（例如把站点建在别处再绝对链接过来）就会这样 |
| compose 报 `network lawver-infra ... could not be found` | 先起共享基建：`compose.infra.yml up -d` |
| compose 去拉 GHCR 镜像报 `denied` | 用的是私有镜像且没登录；本地构建的话在 `compose.env` 里把 `LAWVER_APP_IMAGE` / `LAWVER_INTRO_IMAGE` 指到 `lawver-app:local` / `lawver-intro:local` |
| 限流/日志里看到的是网桥 IP | `LAWVER_TRUSTED_PROXY_CIDRS` 没覆盖实例网段（默认取 `LAWVER_NETWORK_SUBNET`，改过网段变量就自动带上） |
| 法条检索命中不了长句 | 这是既有实现行为，**不是容器化引入的**：本地法库是关键词式（SQLite FTS5 trigram），长句自然语言描述匹配不到；用关键词组合（如 `劳动合同 解除`）或走远程数据源（`PKU_LAW_SOURCE=remote` / 将来的自营法库服务） |

## 11. 本次实测记录（2026-10-16，部署机 103.30.78.42，2 核 / 3.9G）

| 项 | 结果 |
|---|---|
| 镜像体积 | `lawver-app` 652MB、`lawver-intro` 78.8MB |
| 镜像内 SQLite | 3.40.1，`tokenize='trigram'` 的 FTS5 可用（≥3 字命中） |
| 镜像内用户 | `uid=996(lawver) gid=993(lawver)`，与宿主 `lawver` 一致 |
| 镜像内是否含语料 | **否**（`RAG/data` 不入镜像，交付边界成立） |
| 容器版彩排 | **37 项全过 / 0 失败**（含杀一侧、维护跳转、8MB 穿透、计划维护开关、单端口） |
| 部署机验收 | **26 项全过 / 0 失败**（基建健康、双实例并存、法库本地检索、介绍页热切换） |
| 首次建索引 | 14 秒（full rebuild，4937 源文件 → 197MB `law.db`） |
| 索引就绪后再启动 | 12～31 秒（`mode=unchanged`） |
| 进程版彩排（重构后回归） | **35 项全过 / 0 失败**（断言已抽到 `rehearsal-lib.sh` 供两个版本共用） |

## 12. 还没做的（下一轮）

- **自营法库服务**：`law_service/`（`/v1` 三端点 + keys.json + 限流 + 审计 + canary）尚未实现，
  见 [law-service-split-plan.md](law-service-split-plan.md)。位置已在 `compose.self-hosted.yml`
  里以注释标好（`law-db` 服务 + `LAWVER_LAW_SERVICE_URL`）。
  落地后：自营实例去掉语料挂载、改指该服务；前沿实例从 `PKU_LAW_SOURCE=remote`（第三方付费）
  换成自营法库，实例侧不用改代码——那是同一个适配层的第三个数据源。
- 外部服务池化（[external-services-pool-plan.md](external-services-pool-plan.md)）未实现。
