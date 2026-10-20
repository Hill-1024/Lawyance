# Docker Compose 部署手册

面向在部署机上工作的执行者（人或 agent）。这份文档讲**容器化部署**；
原来的 systemd 三件套（[README 部署拓扑](../README.md)、[deployment.md](deployment.md)）仍然有效，
两者可以并存，按第 10 节切换与回滚。

阅读顺序建议：第 1～4 节搞清形态与前置条件，**第 5 节照着做**（每一步都有验收），
第 6 节是可直接粘贴的完整序列。已经在跑 systemd 版的机器请重点看 5.2 的
「.env 要改哪几行」——**漏改一行 `LAWVER_BLOB_DIR` 就会把用户附件写进容器层**。

---

## 1. 一句话

一份 compose 起一个实例，**宿主只发布一个端口**（实例网关，隧道指向它）；
一台机器可以跑多个实例，PostgreSQL / Redis / SearXNG 全机共享一套。

## 2. 为什么这样切

改造前一台机器上是三个 systemd 单元 + 一堆回环端口：

| | 改造前（systemd） | 改造后（compose） |
|---|---|---|
| 分流核心 | 宿主 127.0.0.1:8080 | 容器内 8080，**发布到宿主**（唯一端口） |
| 功能页 | 宿主 127.0.0.1:8081 | 容器内 8081，**不发布** |
| 介绍页 | 宿主 127.0.0.1:8082 | 容器内 8082，**不发布** |
| PostgreSQL | 宿主 127.0.0.1:5432 | 容器内 5432，**不发布** |
| SearXNG | 宿主 127.0.0.1:8083 | 容器内 8080，**不发布** |
| Redis | 可选，宿主 6379 | 容器内 6379，**不发布** |
| **一个实例占用的宿主端口** | **5～6 个** | **1 个** |

多实例因此变得自然：再起一个实例只需要另一个发布端口——容器内部的
8080/8081/8082 各在自己的网络命名空间里，互不冲突。

## 3. 拓扑

```
                         隧道（Cloudflare Tunnel 等）
                                   │
                       127.0.0.1:${LAWVER_ROUTER_PUBLISH_PORT}
                                   │
   ┌───────────────────────────────┴────────────────────────────────┐
   │  实例（compose 项目名 = 实例名，每实例一套）                     │
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

## 4. 文件与前置条件

### 4.1 文件清单

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

### 4.2 前置条件（逐条验收）

```bash
# 1) Docker 与 Compose v2（部署机实测 Docker 29.8.1 / Compose v5.5.1）
docker version --format '{{.Server.Version}}'      # 有版本号
docker compose version                              # v2 及以上

# 2) lawver 用户存在，并记下它的 uid/gid —— 容器内就跑这个用户
id lawver                                           # 部署机实测 uid=996 gid=993（不是 1000）

# 3) 磁盘：镜像约 730MB，法库索引约 200MB，再留出数据增长
df -h /                                             # 建议 ≥ 10GB 可用

# 4) 出网：拉镜像（GHCR）、同步 APK（GitHub 私有仓需令牌，见 5.2）、法条远程检索（如启用）
curl -s -o /dev/null -w '%{http_code}\n' https://ghcr.io/v2/   # 401 说明能连上（未认证正常）

# 5) 两个仓库的检出都在 main（部署分支）
sudo -u lawver git -C /srv/lawver branch --show-current        # main
sudo -u lawver git -C /srv/lawver-intro branch --show-current  # main
```

> **分支模型**：`main` 是部署分支，`dev` 只用于迭代测试。改动先推 `dev`、
> 在 dev 上跑彩排/验收确认没问题，再合到 `main`；部署机各自目录 `git pull` 拉到的就是 `main`。
> 容器化部署同样遵守这条——`LAWVER_APP_IMAGE` 指向的镜像也应从打过 tag 的 `main` 构建。

镜像二选一：

```bash
# A. 拉 GHCR：tag v*.*.* 触发 .github/workflows/docker-images.yml 推
#    ghcr.io/hill-1024/lawver-app（介绍页仓推 lawver-intro）。私有仓需先登录：
# echo "$GHCR_TOKEN" | docker login ghcr.io -u <用户名> --password-stdin

# B. 本地构建（部署机自带源码时）：
cd deploy/docker && INTRO_REPO=/srv/lawver-intro ./build.sh
# 产出 lawver-app:local / lawver-intro:local；uid/gid 自动取 `id -u lawver`
```

---

## 5. 部署流程（逐步）

### 5.0 准备目录与权限

```bash
sudo install -d -o lawver -g lawver -m 755 /srv/lawver-instances
sudo install -d -o lawver -g lawver -m 750 /srv/lawver-searxng
```

**验收**：`ls -ld /srv/lawver-instances /srv/lawver-searxng` 属主都是 `lawver`。

### 5.0.1 本地语料挂载（仅自营环境）

当前代码版本不再跟踪 `RAG/data/`。使用本地法库的自营 overlay，或独立法库服务，
须在构建/启动前准备其只读挂载的数据目录；客户远程实例跳过此步骤。

将 `CANDIDATE_ROOT` 替换为首次部署或未被运行容器使用的候选代码目录：

```bash
CANDIDATE_ROOT=/absolute/path/to/candidate
sudo -u lawver env LAWVER_RAG_DATA_REPO=git@github.com:Hill-1024/Lawyance-Law-Data.git \
  bash "$CANDIDATE_ROOT/scripts/sync-rag-data.sh" v2026.10.17
```

目标是脚本所属项目的 `RAG/data/`，由脚本路径决定，不由执行时的工作目录决定。
已有私有数据目录时可设置 `LAWVER_RAG_DATA_DIR`；目录须有 `manifest.sha256`，
并与目标分开。脚本先校验暂存副本，再备份和替换；不会重启容器或重建索引。
默认版本预期 5,237 个语料文件。核对 compose 实际挂载路径、数据版本和三个检索
端点后再发布。同步与备份说明见 [RAG/README.md](../RAG/README.md)。

### 5.1 起共享基建（一台机器只做一次）

```bash
cd <仓库>/deploy/docker
cp -n infra.env.example infra.env && chmod 600 infra.env
```

编辑 `infra.env`，把 `LAWVER_POSTGRES_PASSWORD` 换成强口令（`openssl rand -base64 24`）。

SearXNG 配置（它的容器以 **uid 977** 运行，且启动时会往 `/etc/searxng` 写运行时文件，
所以目录必须可写——不能挂只读）：

```bash
cp -n searxng/settings.yml /srv/lawver-searxng/settings.yml
sed -i "s/REPLACE_WITH_RANDOM_HEX/$(openssl rand -hex 32)/" /srv/lawver-searxng/settings.yml
sudo chown -R 977:977 /srv/lawver-searxng
```

起基建：

```bash
LAWVER_SEARXNG_DIR=/srv/lawver-searxng \
  docker compose --env-file infra.env -f compose.infra.yml up -d
docker compose --env-file infra.env -f compose.infra.yml ps
```

**验收**（三条都要过）：

```bash
docker ps --filter 'label=com.docker.compose.project=lawver-infra' --format '{{.Names}} {{.Status}} {{.Ports}}'
# postgres / redis 显示 (healthy)；searxng 起来
# 三个容器的 Ports 列都应为空 —— 基建不发布宿主端口

docker exec lawver-infra-searxng-1 sh -c \
  'wget -qO- "http://127.0.0.1:8080/search?q=test&format=json" >/dev/null && echo searxng-json-ok'
# 输出 searxng-json-ok（settings.yml 的 search.formats 必须含 json）

docker exec lawver-infra-postgres-1 pg_isready -U lawver -d lawver
# 输出 accepting connections
```

### 5.2 应用配置：`.env` 怎么放（**迁移时最容易出错的一步**）

应用照旧自己读工作目录下的 `.env`（[单一事实来源](../deploy/systemd/lawver-app.service)），
容器里由 `LAWVER_APP_ENV_FILE` 把它**只读**挂到 `/app/.env`。

两层分工，刻意不混：

- **业务配置**（LLM 密钥、得理/企查查/法宝令牌、限流参数……）写在这个 `.env` 里。
- **容器拓扑**（监听地址、数据库/Redis/SearXNG 的服务名、可信代网段、数据路径）由
  compose 的 `environment:` 给。python-dotenv 默认**不覆盖**已存在的环境变量，
  所以拓扑项不会被 `.env` 顶掉。

#### 从 systemd 版迁移时，`.env` 要改哪几行

线上现成的 `/srv/lawver/.env` 直接拿来用会踩两类坑：

| 键 | systemd 版的值形态 | 容器里必须怎么改 | 不改的后果 |
|---|---|---|---|
| `LAWVER_BLOB_DIR` | 宿主绝对路径（如 `/var/lib/lawver/workbench-blobs`） | **删掉这一行**（默认就变成 `$LAWVER_DATA_DIR/workbench-blobs` = `/app/data/workbench-blobs`，在挂载卷内），或显式写成 `/app/data/workbench-blobs` | 容器里 `/var/lib/lawver` 不存在，附件会写进**容器可写层**：容器一重建，用户附件全丢，且备份脚本也读不到 |
| `LAWVER_DATABASE_URL` | `…@127.0.0.1:5432/lawver` | 可以留着（compose 会用 `postgres:5432` 覆盖它），但建议直接删掉，避免两处不一致的错觉 | 不会出错（compose 优先），但排查时会误导人 |
| `SEARXNG_BASE_URL` | `http://127.0.0.1:8083/` | 同上（compose 覆盖为 `http://searxng:8080/`） | 同上 |
| `LAWVER_HOST` | `127.0.0.1` | 同上（compose 覆盖为 `0.0.0.0`） | 同上 |
| `DELI_APPID` / `DELI_SECRET` | 旧版得理凭据 | 改成 `DELI_API_KEY`（2026-10 得理换新平台，旧凭据已废弃） | 案例检索一直失败 |
| `LAWVER_RELEASE_DIR` | `data/releases/android`（相对路径） | 不用改：相对 cwd，容器里 cwd=`/app`，正好落在挂载卷内 | —— |
| 其它绝对路径（`LAWVER_MEMORY_DB`、`LAWVER_USAGE_LOG_PATH` 等） | 宿主绝对路径 | 同样要删掉或改成 `/app/data/...` | 同类：写进容器层 |

**一句话规则**：`.env` 里出现的**任何宿主绝对路径**都要删掉（让默认值在容器内生效）
或改成 `/app/...`。`/app/data`、`/app/TEMP`、`/app/Result`、`/app/RAG/cache` 是唯一被挂载的四棵可写树。

还有一个容易忽略的：APK 分发要从 GitHub 私有仓同步，需要令牌，否则启动只是记状态不报错、
页面上的版本信息会一直回落：

```bash
# 在 .env 里加（细粒度只读 PAT，能读 Lawyance 的 Releases 即可）
LAWVER_GITHUB_TOKEN=github_pat_xxx
```

**验收**：

```bash
sudo -u lawver grep -nE '^(LAWVER_BLOB_DIR|LAWVER_DATABASE_URL|SEARXNG_BASE_URL|LAWVER_HOST)=' /srv/lawver/.env
# 期望：只有你想保留的那些（建议一条都不留），且没有任何宿主绝对路径
```

### 5.3 建实例

```bash
cd <仓库>/deploy/docker
./new-instance.sh main 8080
```

它会：

1. 挑一个宿主空闲端口（给了就用给的）与未占用的实例网段（默认从 `10.42.0.0/24` 起）；
2. 建 `/srv/lawver-instances/main/`，内含 `compose.env`、`run.sh`、`data/{data,TEMP,Result}`、`state/router`；
3. 把数据目录属主改成**容器内用户**（从镜像里读 uid/gid，探测不到才退到 `id -u lawver`）；
4. 把 `LAWVER_DATABASE_URL` 的口令从 `infra.env` 继承过来。

**验收**：输出末尾会打印端口、网段、Redis 前缀、数据根、维护开关目录；再核对一遍：

```bash
grep -E '^(LAWVER_ROUTER_PUBLISH_PORT|LAWVER_NETWORK_SUBNET|LAWVER_REDIS_PREFIX|LAWVER_DATABASE_URL)=' \
  /srv/lawver-instances/main/compose.env
# 口令应与 infra.env 的 LAWVER_POSTGRES_PASSWORD 一致
```

> `run.sh` 里记的是生成时 `<仓库>/deploy/docker` 的绝对路径。之后把仓库挪走会让
> `run.sh` 失效——重跑一次 `new-instance.sh`（换个名字）即可，或手工改 `run.sh` 里的 `HERE_DOCKER`。

### 5.4 （可选）预建法库索引

自营实例首次启动会建索引。实测（2 核机器）**14 秒**建完 4937 个源文件 → 197MB `law.db`，
不算慢；但想把这 14 秒也省掉、或想先确认语料没问题，可以预建：

```bash
./prebuild-law-db.sh /srv/lawver-instances/main
# 输出里 mode=full 表示这次建了库；file_count 应与语料文件数一致
```

### 5.5 起实例

```bash
/srv/lawver-instances/main/run.sh up -d              # 自营：挂语料，本地法库
/srv/lawver-instances/main/run.sh up -d --frontier   # 前沿：不带语料，远程检索
/srv/lawver-instances/main/run.sh ps
```

`run.sh` 是对 `docker compose --env-file compose.env -f compose.yml [-f overlay]` 的封装，
参数原样透传：`up / down / stop / start / restart / ps / logs -f app / exec -T app …`。

**验收**：

```bash
P=8080
curl -s -o /dev/null -w 'core:%{http_code}\n' "http://127.0.0.1:$P/__core/status"   # 200
curl -s -o /dev/null -w 'app:%{http_code}\n'  "http://127.0.0.1:$P/api/health"      # 200
curl -s "http://127.0.0.1:$P/__core/status" | python3 -m json.tool | grep -E 'up|reason'
#   sides.app.up / sides.intro.up 都应为 true
ss -ltnp | grep ":$P "                                                             # 只有这一个端口
```

### 5.6 端到端验收

先跑彩排（隔离项目名与 18080 端口，跑完自动收干净，不动正在运行的实例）：

```bash
cd <仓库>/deploy/docker
INTRO_REPO=/srv/lawver-intro ./rehearsal.sh          # 期望：通过 37，失败 0
```

再跑部署机验收（会占用项目名 `lawver`/`billing`/`lawver-infra`，**已部署过的机器会拒绝启动**）：

```bash
./verify-on-server.sh                                # 期望：通过 26，失败 0
```

### 5.7 隧道与 DNS

把域名指到 `http://127.0.0.1:${LAWVER_ROUTER_PUBLISH_PORT}`（默认 8080）。
**不要把隧道指向容器里的 8081/8082** —— 它们连宿主端口都没有。

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<域名>/        # 200
curl -sI https://<域名>/ | grep -i x-core-upstream              # app（走到功能页）
curl -sI https://<域名>/robots.txt | grep -i x-core-upstream    # intro（走到介绍页）
```

`X-Core-Upstream` 是分流核心打的来源标记，用它判断"这条路真的走到想要的那一侧"。

### 5.8 上线自检清单

| # | 检查 | 命令/判据 |
|---|---|---|
| 1 | 基建健康 | `compose -f compose.infra.yml ps` → postgres/redis healthy |
| 2 | 只发布一个端口 | `docker ps` 里实例只有核心一行有 `127.0.0.1:<端口>->8080` |
| 3 | 核心两侧在线 | `/__core/status` 的 app/intro 均 `up: true` |
| 4 | 接口免鉴权可用 | `/api/health` 200 |
| 5 | **登录与 Cookie** | 浏览器登录一次，DevTools 看 `Set-Cookie` 带 `Secure`；再查访问日志确认记的是**真实客户端 IP**：`tail -1 <实例>/data/usage.log` → 形如 `… \| INFO \| 203.0.113.77 \| anonymous \| web \| POST \| /api/login \| 200`（不是 `172.x` 网桥地址）→ 说明可信代理与真实 IP 透传都配对了 |
| 6 | 数据库真的连上 | `docker compose --env-file infra.env -f compose.infra.yml exec postgres psql -U lawver -d lawver -tAc "select count(*) from information_schema.tables where table_schema='public'"` → 大于 5；能登录成功也等于证明了这条 |
| 7 | 附件落盘在卷里 | 工作台上传一个附件，宿主 `ls /srv/lawver-instances/main/data/data/workbench-blobs/` 能看到分片目录 |
| 8 | 法条检索 | 自营实例：`run.sh exec -T -e PYTHONPATH=/app/backend:/app -w /app app python -c "from mcp import pkulaw_client; print(pkulaw_client.get_article('民法典','第五百七十七条')[:120])"` → `success: true` |
| 9 | APK 版本信息 | `curl -s "http://127.0.0.1:$P/api/releases/android/latest" \| head -c 120` → 有 `versionName`（私有仓要配 `LAWVER_GITHUB_TOKEN`） |
| 10 | 介绍页换版 | 宿主跑 `tools/build.sh`，页面随之变化且**容器未重启**（`run.sh ps -q intro` 的 id 不变） |

### 5.9 数据库迁移

应用**不会**在启动时自动跑 alembic（只自愈建表）。首次部署与每次代码更新后手工执行：

```bash
/srv/lawver-instances/main/run.sh exec -T -w /app/backend app alembic -c alembic.ini upgrade head
```

---

## 6. 完整照抄版（从零到能访问）

把 `<仓库>`、`<端口>`、`<实例名>` 换掉即可。

```bash
# ── 0. 前置 ────────────────────────────────────────────────
docker version --format '{{.Server.Version}}' && docker compose version
id lawver                                       # 记下 uid/gid
sudo install -d -o lawver -g lawver -m 755 /srv/lawver-instances
sudo install -d -o lawver -g lawver -m 750 /srv/lawver-searxng
cd <仓库>/deploy/docker

# ── 1. 镜像 ────────────────────────────────────────────────
INTRO_REPO=/srv/lawver-intro ./build.sh          # 或：docker login ghcr.io && 用 GHCR 镜像

# ── 2. 共享基建 ────────────────────────────────────────────
cp -n infra.env.example infra.env && chmod 600 infra.env
sed -i "s/^LAWVER_POSTGRES_PASSWORD=.*/LAWVER_POSTGRES_PASSWORD=$(openssl rand -base64 24)/" infra.env
cp -n searxng/settings.yml /srv/lawver-searxng/settings.yml
sed -i "s/REPLACE_WITH_RANDOM_HEX/$(openssl rand -hex 32)/" /srv/lawver-searxng/settings.yml
sudo chown -R 977:977 /srv/lawver-searxng
LAWVER_SEARXNG_DIR=/srv/lawver-searxng docker compose --env-file infra.env -f compose.infra.yml up -d
docker compose --env-file infra.env -f compose.infra.yml ps     # 期望 healthy

# ── 3. 应用 .env（业务配置；务必看 5.2 的迁移表）───────────
#   关键：删掉 LAWVER_BLOB_DIR 等宿主绝对路径；补 DELI_API_KEY / LAWVER_GITHUB_TOKEN
ls -l /srv/lawver/.env                          # 迁移时就是这一份
grep -nE '^(LAWVER_BLOB_DIR|LAWVER_DATABASE_URL|SEARXNG_BASE_URL|LAWVER_HOST)=' /srv/lawver/.env

# ── 4. 建实例并起 ──────────────────────────────────────────
./new-instance.sh main <端口>
/srv/lawver-instances/main/run.sh up -d
sleep 30                                        # 首次含建索引，实测 14 秒左右

# ── 5. 迁移 + 验收 ─────────────────────────────────────────
/srv/lawver-instances/main/run.sh exec -T -w /app/backend app alembic -c alembic.ini upgrade head
curl -s -o /dev/null -w 'core:%{http_code}\n' "http://127.0.0.1:<端口>/__core/status"
curl -s -o /dev/null -w 'app:%{http_code}\n'  "http://127.0.0.1:<端口>/api/health"
ss -ltnp | grep ":<端口> "

# ── 6. 隧道指向 127.0.0.1:<端口> 后 ────────────────────────
INTRO_REPO=/srv/lawver-intro ./rehearsal.sh     # 期望 37 项全过
```

---

## 7. 多实例

再跑一次 `new-instance.sh` 就是第二个实例。需要各不相同的只有三样：

| 项 | 变量 | 冲突后果 |
|---|---|---|
| 宿主发布端口 | `LAWVER_ROUTER_PUBLISH_PORT` | 起不来（端口被占） |
| 实例网段 | `LAWVER_NETWORK_SUBNET` | 起不来（ipam 网段重叠） |
| Redis 前缀 | `LAWVER_REDIS_PREFIX` | **不报错但更糟**：限流计数与登录节流互串，症状是"限流看起来没生效"或"另一个实例的用户被误伤" |

`new-instance.sh` 会校验这三项并拒绝重复。数据、卷、容器名、网络都由
`COMPOSE_PROJECT_NAME` 隔离，不需要手工区分。

多实例共用一套基建，所以**每个实例的数据库要分开**：建库并改该实例的 `compose.env`：

```bash
docker compose --env-file infra.env -f compose.infra.yml exec postgres \
  psql -U lawver -d lawver -c 'CREATE DATABASE lawver_<实例名> OWNER lawver'
sed -i 's#/lawver$#/lawver_<实例名>#' /srv/lawver-instances/<实例名>/compose.env
/srv/lawver-instances/<实例名>/run.sh up -d
/srv/lawver-instances/<实例名>/run.sh exec -T -w /app/backend app alembic -c alembic.ini upgrade head
```

## 8. 配置分层的规则

| 层 | 放哪 | 例子 |
|---|---|---|
| 业务配置 | 应用的 `.env`（只读挂进 `/app/.env`） | `SECRET_KEY`、`API_KEY`/`BASE_URL`/`LLM_MODEL`、`DELI_API_KEY`、`QCC_ACCESS_TOKEN`、`PKU_*`、限流参数、`LAWVER_GITHUB_TOKEN` |
| 容器拓扑 | `compose.yml` 的 `environment:`（由 compose 覆盖 `.env`） | `LAWVER_HOST=0.0.0.0`、`LAWVER_DATABASE_URL`、`LAWVER_REDIS_URL`、`SEARXNG_BASE_URL`、`LAWVER_DATA_DIR`、`LAWVER_TRUSTED_PROXY_CIDRS` |
| 实例作用域 | `<实例>/compose.env`（`--env-file` 传入） | 项目名、发布端口、网段、挂载路径、Redis 前缀、镜像标签 |
| 基建作用域 | `deploy/docker/infra.env`（全机一份） | PG 口令、SearXNG 配置目录 |

**为什么拓扑项不能用 `.env`**：容器里 `127.0.0.1` 指的是容器自己，不是宿主也不是兄弟容器。
服务名（`postgres`/`redis`/`searxng`/`app`/`intro`）才是容器网络里的地址。

`LAWVER_TRUSTED_PROXY_CIDRS` 必须覆盖核心容器所在网段，否则限流与访问日志拿不到真实客户端 IP
（`CF-Connecting-IP` 只在直连对端是可信代理时才采信）。这里用同一个 `LAWVER_NETWORK_SUBNET`
既喂网络 `ipam` 又喂该变量，两处不可能漂移。

## 9. 日常维护

| 事情 | 命令 |
|---|---|
| 更新应用镜像 | 在 `main` 上打 tag 触发 GHCR 构建（或 `./build.sh --tag <版本>`），改 `compose.env` 的 `LAWVER_APP_IMAGE`，再 `run.sh up -d` |
| 更新后迁移 | `run.sh exec -T -w /app/backend app alembic -c alembic.ini upgrade head` |
| 介绍页换版 | 宿主 `/srv/lawver-intro` 在 `main` 上 `git pull && tools/build.sh`（**容器不重启**，符号链接原子翻转；实测生效） |
| 语料更新 | 在候选目录用 `bash scripts/sync-rag-data.sh <已批准数据版本>` 同步私有语料，校验索引与三个端点，再按自营实例或独立服务的发布流程换版 |
| 备份 | `run.sh exec -T -w /app/backend app python -m workbench.maintenance backup /app/data/backup/$(date +%F)`，再 `... verify /app/data/backup/$(date +%F)`。**目的地必须落在挂载卷内**（`/app/data/...`），否则备份留在容器层 |
| 计划维护 | `touch /srv/lawver-instances/<实例>/state/router/app.maintenance`（核心认这个标志位；删掉文件即恢复，进程不用重启） |
| 看日志 | `run.sh logs -f app` / `router` / `intro`；或 `--since 10m` |
| 数据库 shell | `docker compose --env-file infra.env -f compose.infra.yml exec postgres psql -U lawver -d lawver` |
| 重启单个服务 | `run.sh restart app`（核心与介绍页不受影响） |

## 10. 从 systemd 切换与回滚

前提：`rehearsal.sh` 与 `verify-on-server.sh` 都全过，且 5.2 的 `.env` 迁移完成。

```bash
# 1) 停三件套（unit 文件保留，随时能回滚）
sudo systemctl stop lawver-router lawver-app lawver-intro
# 2) 起基建与实例（端口沿用 8080，隧道不用改）
cd <仓库>/deploy/docker
LAWVER_SEARXNG_DIR=/srv/lawver-searxng docker compose --env-file infra.env -f compose.infra.yml up -d
/srv/lawver-instances/main/run.sh up -d
# 3) 按 5.8 自检清单逐条过，再观察一个维护窗口
```

**回滚**：

```bash
/srv/lawver-instances/main/run.sh down
docker compose --env-file infra.env -f compose.infra.yml down
sudo systemctl start lawver-router lawver-app lawver-intro
```

两条路**不能同时监听同一宿主端口**：先 `down` 再 `start`。

原 systemd 版里 PG 与 SearXNG 是宿主上的容器/进程（`workbench-postgres-1`、`searxng`），
与新的 `lawver-infra` 是**两套**。切换期间注意不要同时写同一个数据库：要么让实例指向
原来的库，要么确认新库已迁移完再切。

## 11. 故障排查

| 症状 | 原因与处理 |
|---|---|
| 功能页反复重启，日志 `PermissionError: Operation not permitted: '/app/data'` | 宿主数据目录属主不是容器用户。`new-instance.sh` 以 root 跑时会自动 chown；手工建的目录执行 `sudo chown -R 996:993 <实例>/data`（uid 以 `docker run --rm --entrypoint id <镜像> -u` 为准） |
| 核心重启，日志 `Permission denied: '/state/app.maintenance'` | 同上，状态目录属主要对 |
| 介绍页整站 404，日志 `构建产物不存在：.../current` | `current` 符号链接的目标不在挂载树内。`tools/build.sh` 建的是**绝对**链接（`→ <仓库>/releases/<时间戳>`），所以 compose 把仓库挂在与宿主**完全相同的路径**上；链接指向树外（例如站点建在别处再绝对链接过来）就会这样 |
| compose 报 `network lawver-infra ... could not be found` | 先起共享基建 |
| compose 去拉 GHCR 镜像报 `denied` | 私有镜像且未登录；本地构建的话把 `compose.env` 的 `LAWVER_APP_IMAGE`/`LAWVER_INTRO_IMAGE` 指到 `lawver-app:local`/`lawver-intro:local` |
| 附件上传后重启就没了 | `.env` 里 `LAWVER_BLOB_DIR` 还指着宿主路径（见 5.2） |
| 页面版本信息一直是"最新版"兜底文案 | APK 同步没成功：私有仓要配 `LAWVER_GITHUB_TOKEN`；或 `LAWVER_RELEASE_SYNC_ON_STARTUP=0` 被打开了 |
| 限流/日志里是网桥 IP | `LAWVER_TRUSTED_PROXY_CIDRS` 没覆盖实例网段（改过 `LAWVER_NETWORK_SUBNET` 会自动带上） |
| 登录后 cookie 不带 `Secure` | 直连对端是否被判定为可信代理；隧道需透传 `X-Forwarded-Proto`/`cf-visitor` |
| 法条检索命中不了长句 | **既有实现行为，不是容器化引入的**：本地法库是关键词式（SQLite FTS5 trigram），长句自然语言匹配不到；用关键词组合（如 `劳动合同 解除`），或走远程数据源（`PKU_LAW_SOURCE=remote` / 将来的自营法库服务） |

## 12. 本次实测记录（2026-10-16，部署机 103.30.78.42，2 核 / 3.9G）

| 项 | 结果 |
|---|---|
| 镜像体积 | `lawver-app` 652MB、`lawver-intro` 78.8MB |
| 镜像内 SQLite | 3.40.1，`tokenize='trigram'` 的 FTS5 可用（≥3 字命中；2 字本就该走短词 LIKE 兜底） |
| 镜像内用户 | `uid=996(lawver) gid=993(lawver)`，与宿主 `lawver` 一致 |
| 镜像内是否含语料 | **否**（`RAG/data` 不入镜像，交付边界成立） |
| 容器版彩排 | **37 项全过 / 0 失败**（含杀一侧、维护跳转、8MB 逐字节穿透、计划维护开关、单端口） |
| 部署机验收 | **26 项全过 / 0 失败**（基建健康、双实例并存、法库本地检索、介绍页热切换） |
| 登录与可信代理 | 登录返回 `auth_token` Cookie 带 `Secure; HttpOnly; SameSite=strict`；`usage.log` 记录到转发来的 `203.0.113.77` 而非网桥地址 → 真实 IP 透传与限流口径都正确 |
| 数据库鉴权路径 | 容器内登录 200（账号在共享基建 PG 的库表里，走 `postgres:5432`） |
| alembic | 容器内可执行：`exec -T -w /app/backend app alembic -c alembic.ini upgrade head`，`current` 显示 `20261002_pending_plan (head)` |
| `prebuild-law-db.sh` | 可执行，输出 `mode: unchanged`（卷里已有索引） |
| 可写路径落点 | `usage.log`、`web_tools.log` 都落在 `<实例>/data/` 下（`/app/data` 挂载卷内），没有落进容器层 |
| 进程版彩排（重构后回归） | **35 项全过 / 0 失败**（断言抽到 `rehearsal-lib.sh` 供两个版本共用） |
| 首次建索引 | 14 秒（full rebuild，4937 源文件 → 197MB `law.db`） |
| 索引就绪后再启动 | 12～31 秒（`mode=unchanged`） |

## 13. 独立法库服务与后续工作

- **自营法库服务（issue #13）**：代码与部署模板已提供，服务器由操作者手动上传验收。
  用独立 [法库部署说明](law-service-deployment.md) 和 `compose.law-service.yml` 部署我方 API，
  使用 `LAWVER_LAW_SERVICE_URL` / `LAWVER_LAW_SERVICE_KEY` 连接；监控见
  [运营说明](law-service-operations.md)。原有本地语料实例仍使用本手册前面的 `runtime` 镜像与自营 overlay。
- **客户交付边界**：客户必须使用 Dockerfile 的 `customer` target 和 `compose.customer.yml`，
  不能直接使用本手册默认 `build.sh` 构建的自营 `runtime` 镜像。客户镜像不含整个 `RAG/`
  或自营服务；归档用 `scripts/package-customer.py` 生成并复验。客户操作步骤见
  [客户部署说明](../deploy/customer/README.md)，不要给客户执行本手册的语料同步/索引构建步骤。
- 外部服务池化（[external-services-pool-plan.md](external-services-pool-plan.md)）未实现。
- 部署机 `/srv/lawver` 目前无法 `git pull`（主仓转私有后该机没有凭证），
  更新要走"配只读 PAT 或从开发机同步"两条路之一。
