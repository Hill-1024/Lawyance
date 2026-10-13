# 生产部署手册（面向执行者：人 / agent）

> 本文是从零到上线的完整部署与维护文档。所有 `<尖括号>` 占位符必须先替换成部署机自己的值：
> `<部署机IP>`、`<生产域名>`、`<别名域名>`（见「隧道与 DNS」）、`<强密码>`、`<Fernet密钥>` 等。
> **本文不包含任何真实 IP、域名与凭据**——凭据由部署者通过本文给出的生成命令自行产生，且只落在部署机的 `.env` / 密钥文件里，永不进入仓库与文档。
>
> 目标读者包含自动化 agent：每一步都给出**命令**与**验收标准**，验收不过就不要进入下一步。
> 环境以 Debian 12 / Ubuntu 22.04 为例，其他发行版替换包管理命令即可。

---

## 0. 拓扑与端口（先读懂这张表再动手）

介绍页与功能页是**两个仓库、两个进程**，同一个域名对外，由一台「分流核心」按路径分派：

```
互联网 → 隧道(Cloudflare 或等价) → 本机 127.0.0.1:8080 分流核心
                                        ├─ 介绍页路径 → 127.0.0.1:8082（静态服务）
                                        └─ 其余路径   → 127.0.0.1:8081（功能页 FastAPI）
```

| 组件 | 目录 | 端口 | 对外 |
|---|---|---|---|
| 分流核心（router） | `/srv/lawver/deploy/router` | 8080 | **隧道唯一入口** |
| 功能页（FastAPI + 前端 dist） | `/srv/lawver` | 8081 | 只监听回环 |
| 介绍页（静态服务） | `/srv/lawver-intro` | 8082 | 只监听回环 |
| SearXNG（联网搜索，Docker） | `/srv/lawver-searxng`（配置目录） | 127.0.0.1:8083 → 容器 8080 | 只监听回环 |
| PostgreSQL（Docker） | Docker 卷 `lawver-postgres` | 127.0.0.1:5432 | 只监听回环 |
| Redis（可选，Docker/apt） | — | 6379 | 只有 `UVICORN_WORKERS>1` 时必须 |

- 三件套**都只监听 127.0.0.1**，公网流量一律经隧道落到 8080。
- 功能页路径：`/home`、`/login`、`/settings/*`、`/admin`、`/business`、`/court/*`、`/api/*`、`/assets/*`、`/manifest.webmanifest` 等（详见核心配置 `intro_exact`/`intro_prefixes` 的补集）。
- 介绍页路径：`/`、`/design`、`/download`、`/pricing`、`/robots.txt`、`/sitemap.xml`、`/intro-assets/*`。
- **路径表是一处约定、两处实现**：核心配置的 `intro_exact`/`intro_prefixes` 与介绍页仓库 README 的路径表必须保持一致，改一边就要改另一边。

### 快速执行卡（agent 顺序执行）

| # | 做什么 | 验收标准 |
|---|---|---|
| 1 | 系统用户与目录 | `id lawver` 存在；`/srv`、`/var/lib/lawver` 属主 lawver |
| 2 | 拉两个仓库（`dev` 分支） | 两个目录下 `git log -1` 有输出 |
| 3 | Python 依赖（venv） | `/srv/lawver/.venv/bin/python -c "import fastapi"` 无报错 |
| 4 | PostgreSQL（Docker compose） | `pg_isready` 通过 |
| 5 | 跑 Alembic 迁移 | `alembic upgrade head` 退出码 0 |
| 6 | （可选）Redis | `redis-cli ping` 返回 PONG；不部署则跳过 |
| 7 | SearXNG（Docker） | `curl 'http://127.0.0.1:8083/search?q=test&format=json'` 200 |
| 8 | 写 `/srv/lawver/.env` | 第 8 节的必填键齐；权限 600 |
| 9 | 构建前端 | `/srv/lawver/dist/index.html` 存在 |
| 10 | 构建介绍页 | `/srv/lawver-intro/current/index.html` 存在 |
| 11 | 核心配置 + `--check` | 输出两侧探活状态后退出码 0 |
| 12 | 三个 systemd 单元 | `systemctl is-active` 三个都 `active` |
| 13 | 隧道与 DNS 指向 8080 | 第 13 节自检 200 |
| 14 | 上线自检 + 端到端彩排 | 彩排「通过 35，失败 0」 |

---

## 1. 前置条件

### 1.1 系统用户与目录

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin lawver
sudo mkdir -p /srv /var/lib/lawver/{workbench-blobs,backups,router-state}
sudo chown -R lawver:lawver /srv /var/lib/lawver
```

**验收**：`ls -ld /srv /var/lib/lawver` 属主均为 `lawver:lawver`。

### 1.2 软件包

| 软件 | 版本要求 | 用途 |
|---|---|---|
| git | 任意 | 拉代码 |
| Python | **≥ 3.13** | 功能页与核心（核心只用到标准库 + httpx） |
| Node | **≥ 20** + pnpm **10.33.2** | 两个前端构建（介绍页构建也需要） |
| Docker + compose 插件 | 任意（推荐） | PostgreSQL、SearXNG（本文以外的另装方式见各节备选） |
| PostgreSQL | **17**（Docker 镜像即可） | 账号、会话、工作台数据 |

```bash
sudo apt update && sudo apt install -y git python3.13 python3.13-venv curl
# Node ≥20（任选一种：发行版源 / NodeSource / nvm），然后激活 pnpm：
corepack enable && corepack prepare pnpm@10.33.2 --activate
pnpm --version   # 期望 10.33.2
```

**验收**：`python3.13 --version` ≥ 3.13；`node --version` ≥ v20；`pnpm --version` = 10.33.2；`docker compose version` 有输出。

---

## 2. 拉取两个仓库

```bash
sudo -u lawver git clone --branch dev https://github.com/Hill-1024/Lawyance.git       /srv/lawver
sudo -u lawver git clone --branch dev https://github.com/Hill-1024/Lawyance_Intro.git /srv/lawver-intro
```

两个仓库互不依赖，**更新也各自独立**（第 12 节）——这正是分开拉取的目的。

**验收**：两个目录都存在且 `sudo -u lawver git -C <dir> branch --show-current` 输出 `dev`。

---

## 3. Python 依赖（功能页 venv）

```bash
sudo -u lawver python3.13 -m venv /srv/lawver/.venv
sudo -u lawver /srv/lawver/.venv/bin/pip install -U pip
sudo -u lawver /srv/lawver/.venv/bin/pip install -r /srv/lawver/requirements.txt
```

> 也可以把最后一行换成 `uv pip install --python /srv/lawver/.venv/bin/python -r /srv/lawver/requirements.txt`（机器上装了 uv 时更快），venv 路径不变，systemd 单元指向的仍是 `/srv/lawver/.venv/bin/python`。

**验收**：`sudo -u lawver /srv/lawver/.venv/bin/python -c "import fastapi, httpx, alembic; print('ok')"` 输出 ok。

---

## 4. PostgreSQL（Docker compose，推荐）

仓库自带 `deploy/workbench/compose.yml`（仅 PostgreSQL 服务，端口 `127.0.0.1:5432`，数据在卷 `lawver-postgres`）：

```bash
cd /srv/lawver/deploy/workbench
sudo -u lawver env LAWVER_POSTGRES_PASSWORD='<强密码>' docker compose up -d
```

**备选：本机 PostgreSQL 17**（不用 Docker 时）：

```bash
sudo -u postgres createuser --pwprompt lawver
sudo -u postgres createdb --owner=lawver lawver
```

**验收**：

```bash
docker compose -f /srv/lawver/deploy/workbench/compose.yml ps   # postgres 运行中且 healthy
docker exec workbench-postgres-1 pg_isready -U lawver -d lawver # 或本机：pg_isready
```

`<强密码>` 建议 `openssl rand -base64 24` 生成，只写入 compose 环境与 `.env`，不落仓库。

### 4.1 跑迁移（**必须在 `backend/` 下执行**，`alembic.ini` 在那里）

```bash
cd /srv/lawver/backend
sudo -u lawver env LAWVER_DATABASE_URL='postgresql+psycopg://lawver:<强密码>@127.0.0.1:5432/lawver' \
  /srv/lawver/.venv/bin/alembic -c alembic.ini upgrade head
```

**验收**：退出码 0；`alembic current` 显示最新 revision。

> 账号与会话表（`accounts` / `account_sessions`）就在这个库里：**没配 `LAWVER_DATABASE_URL` 就没人能登录**，服务照常起、界面提示「工作台尚未就绪」。
> 首次启动若账号表为空，会依次尝试导入遗留的 `data/account.json`、`data/auth.sqlite3`，都没有才用 `INITIAL_ADMIN_PASSWORD` 引导出 `admin` 账号。

---

## 5. Redis（可选——先读这里再决定）

- **默认单 worker 部署不需要 Redis。** 限流计数与会话布隆过滤器退回进程内实现，行为正确。
- **只有 `UVICORN_WORKERS>1`（或将来多实例）时才必须配**：否则每个 worker 各自计数、各自预热布隆过滤器，真实限流上限被放大到 worker 数倍。
- 使用**普通 Redis 即可**，不需要 RedisBloom 模块（位图由 SETBIT/GETBIT 实现）。
- Redis 只是防护层：连不上、URL 写错都会自动降级，不影响登录与鉴权。

```bash
# 方式 A：apt
sudo apt install -y redis-server && sudo systemctl enable --now redis-server
# 方式 B：Docker
docker run -d --name lawver-redis --restart unless-stopped \
  -p 127.0.0.1:6379:6379 redis:7-alpine
```

**验收**：`redis-cli ping` 返回 `PONG`（Docker 版：`docker exec lawver-redis redis-cli ping`）。
然后回到第 8 节，在 `.env` 里设置 `LAWVER_REDIS_URL="redis://127.0.0.1:6379/0"`。

---

## 6. SearXNG（联网搜索，功能页的搜索工具依赖它）

功能页的「联网搜索」工具调用自托管 SearXNG 的 **JSON API**（`format=json`），不依赖任何第三方搜索 API Key。

### 6.1 配置目录与 settings.yml

```bash
sudo mkdir -p /srv/lawver-searxng
sudo tee /srv/lawver-searxng/settings.yml >/dev/null <<'YAML'
use_default_settings: true
server:
  # 必须换成自己生成的随机值：openssl rand -hex 32
  secret_key: "<searxng密钥>"
  limiter: false
  image_proxy: false
  bind_address: "0.0.0.0:8080"
search:
  safe_search: 0
  default_lang: "all"
  formats:
    - html
    - json          # 功能页依赖 JSON API，不可去
engines:
  - name: bing
    disabled: false
  - name: duckduckgo
    disabled: false
  - name: brave
    disabled: false
  - name: startpage
    disabled: false
YAML
# 容器内以 uid 977 运行，配置目录需可读（按需调整；chown 977:977 最省心）
sudo chown -R 977:977 /srv/lawver-searxng
```

### 6.2 启动容器

```bash
docker run -d --name searxng --restart unless-stopped \
  -p 127.0.0.1:8083:8080 \
  -v /srv/lawver-searxng:/etc/searxng \
  searxng/searxng:latest
```

**验收**（两个都要过）：

```bash
docker ps --filter name=searxng            # 运行中
curl -s 'http://127.0.0.1:8083/search?q=test&format=json' | head -c 200   # 返回 JSON
```

### 6.3 更新 / 调整

```bash
# 引擎增减、超时、安全搜索等 → 改 /srv/lawver-searxng/settings.yml 后重启容器
docker restart searxng

# 升级镜像（先拉再重建同名容器，配置在宿主机不受影响）
docker pull searxng/searxng:latest
docker rm -f searxng
docker run -d --name searxng --restart unless-stopped \
  -p 127.0.0.1:8083:8080 -v /srv/lawver-searxng:/etc/searxng searxng/searxng:latest
```

对应功能页 `.env`：`SEARXNG_BASE_URL="http://127.0.0.1:8083/"`（末尾斜杠保留）。若走了外部 SearXNG 且启用了 Cloudflare Access，则另配 `CF_ACCESS_CLIENT_ID/SECRET`（见 `.env_example`）。

---

## 7. 写功能页配置 `/srv/lawver/.env`

应用用 python-dotenv 读**工作目录下的 `.env`**（systemd 单元的工作目录就是 `/srv/lawver`）：

```bash
sudo -u lawver cp /srv/lawver/.env_example /srv/lawver/.env
sudo chmod 600 /srv/lawver/.env
sudo chown lawver:lawver /srv/lawver/.env
# 然后按下面的表逐项填写
sudo -u lawver nano /srv/lawver/.env
```

> 单元刻意不用 `EnvironmentFile`：systemd 的环境文件解析与 dotenv 不同（引号、`*` 语义不一样），双份来源只会让「本地跑得通、systemd 下读不到」更难查。

### 7.1 必填（漏一项就无法完成验收）

| 键 | 说明 | 生成方式 / 取值 |
|---|---|---|
| `SECRET_KEY` | 认证签名密钥，≥32 位 | `openssl rand -hex 32` |
| `INITIAL_ADMIN_PASSWORD` | **一次性**：账号表为空时引导内置 `admin`（sudo 角色）。**引导成功后删掉这一行并重启** | 自定强密码 |
| `LAWVER_DATABASE_URL` | 与第 4 步一致 | `postgresql+psycopg://lawver:<强密码>@127.0.0.1:5432/lawver` |
| `LAWVER_BLOB_DIR` | 附件 blob 存储 | `/var/lib/lawver/workbench-blobs` |
| `LAWVER_CONNECTOR_KEY` | 插件凭据加密密钥（Fernet）。**与数据库/备份分开保管；丢失 = 插件凭据全部解不开** | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `LAWVER_WORKBENCH_USERS` | 工作台灰度名单，如 `admin`；全部验收后再改 `*` | `admin` |
| `LAWVER_HOST` | **部署机必须为 `127.0.0.1`**（收回回环）。systemd 单元已用 `Environment=` 预设，手工部署的也写上 | `127.0.0.1` |

### 7.2 功能必需（不配则对应能力不可用）

| 键 | 说明 |
|---|---|
| `API_KEY` / `BASE_URL` / `LLM_MODEL` | 主模型（OpenAI 兼容端点）。不配 = 不能对话 |
| `DELI_APPID` / `DELI_SECRET` | 得理法律数据 API（法条/案例检索） |
| `QCC_ACCESS_TOKEN` | 企查查 MCP（企业信息；可留空，对应工具不可用） |
| `SEARXNG_BASE_URL` | 第 6 步的 `http://127.0.0.1:8083/` |

### 7.3 按需（可留空/注释）

| 键 | 说明 |
|---|---|
| `OCP_API_KEY` / `OCP_BASE_URL` / `OCP_LLM_MODEL` | 输出审查（OCP）独立模型；不设回退主模型 |
| `MEMORY_EMBEDDING_ENABLED` + `EMBEDDING_*` | 记忆向量召回（默认关闭） |
| `LAWVER_REDIS_URL` 等 | 见第 5 节；含前缀/超时/限流参数（`LAWVER_API_RATE_LIMIT` 默认 600、`LAWVER_LOGIN_RATE_LIMIT` 默认 30） |
| `LAWVER_RELEASE_*` / `LAWVER_PUBLIC_BASE_URL` / `LAWVER_APK_DOWNLOAD_RPM` | Android APK 分发（从 GitHub Release 同步）；私有仓或 API 限流时可加 `LAWVER_GITHUB_TOKEN` |
| `UVICORN_WORKERS` | 多 worker 时必须同时配 `LAWVER_REDIS_URL`（见第 5 节） |
| `SEARXNG_ENGINES` / `SEARXNG_LANGUAGE` / `SEARXNG_SAFE_SEARCH` 等 | 覆盖 SearXNG 默认参数；通常留空，让服务端 settings.yml 决定 |

### 7.4 已废弃 / 无需

- `PKU_ACCESS_TOKEN`、`MODELSCOPE_*`：**不再需要**（法条检索走本地法库 `RAG/law_data_search`），示例文件里已移除。老机器上若残留可删。
- `PORT`：**不要写**（见第 15 节禁止事项）。

**验收**：`sudo -u lawver bash -c 'cd /srv/lawver && set -a && source .env && set +a && echo $LAWVER_DATABASE_URL | grep -q postgresql && echo env-ok'`；以及权限 `stat -c %a /srv/lawver/.env` 为 `600`。

---

## 8. 构建前端（功能页的 dist）

功能页由 FastAPI 同进程服务 `dist/`（SPA fallback 在 `backend/routes/spa.py`），所以**部署必须构建前端**：

```bash
sudo -u lawver bash -c 'cd /srv/lawver && pnpm install --frozen-lockfile && pnpm run build'
```

> `pnpm run build` 内含 `sync-android-config`（同步 Android 配置）+ `vite build`，产物在仓库根 `dist/`。
> 只改了 `frontend/` 或 `package.json`/`pnpm-lock.yaml` 时才需要重建；只改后端可以跳过。

**验收**：`ls /srv/lawver/dist/index.html` 存在；`ls /srv/lawver/dist/assets | head` 有 hash 资源。

---

## 9. 构建介绍页（releases/current 零停机布局）

```bash
sudo -u lawver bash -c 'cd /srv/lawver-intro && tools/build.sh'
```

`tools/build.sh` 的行为：`pnpm install --frozen-lockfile`（可用 `--skip-install` 跳过）→ `pnpm run build` → 产物移入 `releases/<时间戳>/` → **原子翻转 `current` 符号链接**（`server/serve.py` 每个请求重新解析链接，所以换版零停机、不重启进程）。保留最近 3 个版本（`LAWVER_INTRO_KEEP` 可调）。构建失败时 `current` 不动，线上继续跑上一版。

**验收**：`readlink -f /srv/lawver-intro/current` 指向 `releases/<时间戳>`；`ls /srv/lawver-intro/current/index.html` 存在。

---

## 10. 分流核心配置与自检

```bash
sudo -u lawver cp /srv/lawver/deploy/router/config.example.json /srv/lawver/deploy/router/config.json
```

改这几项，其余保持默认：

| 字段 | 值 |
|---|---|
| `state_dir` | `/var/lib/lawver/router-state`（**不要用仓库内默认路径**：维护开关与探测状态都应该在仓库外，`git pull` 不受影响） |
| `port` | `8080`（隧道入口，不要改） |
| `app_upstream` | `http://127.0.0.1:8081` |
| `intro_upstream` | `http://127.0.0.1:8082` |
| `intro_exact` / `intro_prefixes` | 与介绍页仓库 README 的路径表保持一致（改一边就要改另一边） |

自检（探活一次并打印两侧状态后退出）：

```bash
/srv/lawver/.venv/bin/python /srv/lawver/deploy/router/router.py \
  --config /srv/lawver/deploy/router/config.json --check
```

**验收**：输出中两侧探活结果符合预期（此时功能页还没起可以 down，但配置解析必须无报错、退出码 0）。

---

## 11. 三个 systemd 单元

单元文件都在仓库里，复制到 `/etc/systemd/system/` 后按部署机实际路径与用户核对一遍：

```bash
sudo cp /srv/lawver/deploy/router/systemd/lawver-router.service /etc/systemd/system/
sudo cp /srv/lawver/deploy/systemd/lawver-app.service          /etc/systemd/system/
sudo cp /srv/lawver-intro/deploy/lawver-intro.service          /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now lawver-router lawver-app lawver-intro
systemctl status lawver-router lawver-app lawver-intro --no-pager
```

| 单元 | 关键点 |
|---|---|
| `lawver-router` | `Restart=always` + `StartLimitIntervalSec=0`：它是整站入口，挂了整站只剩隧道的错误页 |
| `lawver-app` | 工作目录 `/srv/lawver`（`.env` 与 `data/` 都在这里解析）；单元内 `Environment=LAWVER_HOST=127.0.0.1`（优先级高于 `.env`，别丢） |
| `lawver-intro` | 只在改了 `server/serve.py` 时才需重启；换版走符号链接 |

**验收**：

```bash
systemctl is-active lawver-router lawver-app lawver-intro   # 三行全 active
curl -s -o /dev/null -w 'app:%{http_code}\n'  http://127.0.0.1:8081/api/health     # 200
curl -s -o /dev/null -w 'intro:%{http_code}\n' http://127.0.0.1:8082/healthz       # 200
curl -s http://127.0.0.1:8080/__core/status | python3 -m json.tool                 # 两侧 up:true
```

期望日志（`journalctl -u lawver-router -f`）：`分流核心监听 127.0.0.1:8080 → 功能页 http://127.0.0.1:8081、介绍页 http://127.0.0.1:8082`。

---

## 12. 隧道与 DNS

隧道（Cloudflare Tunnel / 等价方案）把这些主机名指向本机回环 `http://127.0.0.1:8080`：

| 主机名 | 目标 | 备注 |
|---|---|---|
| `<生产域名>` | `http://127.0.0.1:8080` | 主入口 |
| `<别名域名1>`（如原生直连入口） | `http://127.0.0.1:8080` | 已安装的 Android 客户端可能直连它；**保持现状不要动** |
| `<别名域名2>`（如海外机） | `http://127.0.0.1:8080` | 每台机器跑同一套布局 |

执行顺序：**先起三件套并用别名域名自检完（第 13 节）再切主域名**；如果主域名上有旧站（Cloudflare Pages / Worker），切换时删除旧路由，注意有两个方向的短暂窗口（先切隧道后删旧路由会有一小段旧站 502；先删旧路由会有一小段空窗），按你能接受的顺序做，别两边同时改。

**验收**：`curl -s -o /dev/null -w '%{http_code}' https://<生产域名>/` 返回 200。

---

## 13. 上线自检

```bash
BASE=https://<别名域名>   # 切换主域名前用它自检；切完把 BASE 换成生产域名再跑一遍

# 1) 两侧状态（期望 status: ok，sides.app.up 与 sides.intro.up 都是 true）
curl -s 127.0.0.1:8080/__core/status | python3 -m json.tool

# 2) 三条路径走一遍（期望 200/200/200，归属依次 intro / app / app）
for p in / /home /api/plans; do
  printf '%-12s %s  %s\n' "$p" \
    "$(curl -s -o /dev/null -w '%{http_code}' $BASE$p)" \
    "$(curl -s -o /dev/null -D - $BASE$p | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
done

# 3) 端到端彩排：自起隔离实例（18080/18081/18082），不动线上
INTRO_REPO=/srv/lawver-intro bash /srv/lawver/deploy/router/rehearsal.sh
```

第 3 步逐项验路径分派、大文件逐字节、杀一侧不影响另一侧、维护跳转、自动恢复与计划维护开关——**这是上线前唯一需要的端到端验收**，期望输出「通过 35，失败 0」。

再补一条登录链路验收：用管理面板给自己开一个账号（或首次引导的 `admin`）在浏览器登录一次，确认能进工作台、能发一条消息。**验收完成后**：若 `.env` 里还留着 `INITIAL_ADMIN_PASSWORD`，删掉它并 `systemctl restart lawver-app`；把 `LAWVER_WORKBENCH_USERS` 从灰度名单按需放开。

---

## 14. 日常维护手册

### 14.1 更新功能页（会短暂中断服务，几秒到十几秒）

```bash
sudo -u lawver bash -c 'cd /srv/lawver && git pull'
# 依赖有变（requirements.txt / uv.lock 变了）时：
sudo -u lawver /srv/lawver/.venv/bin/pip install -r /srv/lawver/requirements.txt
# 前端有变（frontend/ / package.json / pnpm-lock.yaml 变了）时：
sudo -u lawver bash -c 'cd /srv/lawver && pnpm install --frozen-lockfile && pnpm run build'
# 有迁移（backend/migrations/versions/ 出现新文件）时：
cd /srv/lawver/backend && sudo -u lawver env LAWVER_DATABASE_URL='<同第 4 步>' \
  /srv/lawver/.venv/bin/alembic -c alembic.ini upgrade head
sudo systemctl restart lawver-app
```

**验收**：`curl -s 127.0.0.1:8081/api/health` 200；`journalctl -u lawver-app -n 30 --no-pager` 无异常栈。

> 迁移是**增量新增，不支持破坏性 downgrade**——回滚只回代码，别回迁移。

### 14.2 更新介绍页（零停机，不重启进程）

```bash
sudo -u lawver bash -c 'cd /srv/lawver-intro && git pull && tools/build.sh'
```

**验收**：`readlink -f current` 指向新时间戳；`curl -s http://127.0.0.1:8082/healthz` 200。

### 14.3 更新分流核心（只有 `deploy/router/` 变了才需要，重启只占几十毫秒）

```bash
sudo -u lawver bash -c 'cd /srv/lawver && git pull'
sudo systemctl restart lawver-router
```

### 14.4 维护窗口

| 目的 | 做法 |
|---|---|
| 只读维护（功能页仍可读、写操作被拒） | `.env` 里 `LAWVER_WORKBENCH_READ_ONLY=1` 并 `systemctl restart lawver-app` |
| 整侧维护（不动进程，用户看到维护页） | `sudo -u lawver touch /var/lib/lawver/router-state/app.maintenance`（介绍页换 `intro.maintenance`），撤销就删文件。**路径必须是核心配置的 `state_dir` 下**，不是仓库目录 |
| 通知用户 | 管理面板发「开屏公告」 |

### 14.5 备份与恢复

见 [docs/workbench/operations.md](./workbench/operations.md)。要点：

- 每日先切只读，再 `python -m workbench.maintenance backup /var/lib/lawver/backups/$(date +%F)`，用 `verify` 校验，保留 30 天。
- **`LAWVER_CONNECTOR_KEY` 与备份分开保管**（丢了备份也解不开插件凭据）。
- 数据库容器数据在 Docker 卷 `lawver-postgres`；整机级备份别漏了它（或导 `pg_dump`）。

### 14.6 日志与观测

```bash
journalctl -u lawver-router -u lawver-app -u lawver-intro -f
journalctl -u lawver-app -n 100 --no-pager            # 看最近异常
curl -s 127.0.0.1:8080/__core/status | python3 -m json.tool   # 可直接挂监控/拨测
docker ps                                              # postgres/searxng 存活
curl -s 'http://127.0.0.1:8083/search?q=test&format=json' | head -c 80  # SearXNG 存活
```

### 14.7 回滚

| 对象 | 做法 |
|---|---|
| 介绍页 | `current` 指回上一个 `releases/<时间戳>`；或 `git pull` 到上一个提交后重跑 `tools/build.sh`（`tools/build.sh` 全程原子，随时可回） |
| 功能页 | `git checkout <上一个 tag/提交>` + 重跑依赖与构建 + 重启；**迁移不回滚** |
| 分流核心 | 同功能页思路，`git checkout` 后重启 `lawver-router` |

---

## 15. 故障排查

| 症状 | 判断 | 处置 |
|---|---|---|
| `/home` 打不开但 `/` 正常 | 功能页下线，核心已自动给维护页 | `systemctl status lawver-app`、`journalctl -u lawver-app -n 100` |
| `/` 显示维护页但 `/home` 正常 | 介绍页下线 | `systemctl status lawver-intro` |
| 两侧都进维护 | 看 `/__core/status` 的 `reason`：`probe failed: ConnectError` = 进程没起或端口不通；`planned` = 开关文件还在 | 按 reason 处置；忘了撤开关就删 `state/*.maintenance` |
| 页面能开但白屏 / 变成下载文件 | Content-Type 或产物缺失 | `curl -sI 127.0.0.1:8082/` 应为 `text/html`；`/intro-assets/<真实文件名>` 应为 `text/javascript` |
| 登录后一直「工作台尚未就绪」 | `LAWVER_DATABASE_URL` 没配或 PG 不可达 | 核对 `.env`；`docker compose ps` / `pg_isready`；重启 `lawver-app` |
| 所有人都登不进 | 迁移没跑，或账号表为空 | 跑 4.1 迁移；确认 `INITIAL_ADMIN_PASSWORD` 引导过（引导后记得删除） |
| 全站 502 / 超时 | 核心没起，或别的进程占着 8080 | `ss -ltnp \| grep 8080`、`journalctl -u lawver-router` |
| 大量 429「操作过于频繁」 | 限流触发（默认 600 次/分/IP；共享出口 IP 会叠加） | 看是否异常客户端在刷；确需放宽调 `LAWVER_API_RATE_LIMIT`（登录另有 `LAWVER_LOGIN_RATE_LIMIT`） |
| 联网搜索工具报错 | SearXNG 挂了或 JSON 格式没开 | 6.2 的两个验收命令；确认 settings.yml 里 `formats` 含 `json` |
| 想确认某请求落到哪一侧 | 响应头 `X-Core-Upstream: app\|intro` | 不用猜 |

---

## 16. 禁止事项（踩过的坑，逐条有依据）

- 不要把隧道指向 8081 / 8082——它们是回环上的内部端口，且没有核心的维护兜底。
- 不要在 `.env` 里设 `PORT`，也不要用 8080 起功能页——会和核心抢端口，症状是核心起不来。
- 不要 `pkill -f agent.py`：机器上可能同时跑着别的实例，统一用 `systemctl`。
- 不要删除 `releases/` 里正被 `current` 指向的目录。
- 不要为了「省事」把 `LAWVER_CONNECTOR_KEY` 存进备份目录。
- 不要把 `SECRET_KEY` / `LAWVER_DATABASE_URL` 密码 / `LAWVER_CONNECTOR_KEY` 写进任何提交、工单或聊天记录。
- 不要在核心配置里把 `state_dir` 留在仓库内（`git pull` 与维护开关会互相干扰）。
- 迁移只增不减：不要指望 `alembic downgrade` 回滚生产。

---

## 17. Agent 操作纪律

1. **验收驱动**：每一步的验收命令必须真实执行并看到期望输出，再进入下一步；验收失败先排查，不要「继续往下试试看」。
2. **密钥处理**：生成后只写入目标文件（`.env`，600 权限）；任何命令回显、日志或汇报中不得出现密钥明文；`ssh`/`scp` 使用已配置的密钥或凭据文件，不要把密码写进命令行参数（会进 shell history）。
3. **改动最小化**：只按文档执行；对不在本文档内的现有服务（已有数据库、已有隧道配置）先读现状再动手，与预期不符时停下报告。
4. **幂等优先**：拉取用 `--ff-only`；重建容器前先 `docker inspect` 记下现有挂载与端口。
5. **变更后自检**：任何更新（14.1–14.3）之后跑对应验收命令；全站级变更后跑一遍第 13 节的路径检查。
