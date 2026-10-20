# 独立法库服务与客户交付（issue #13）

本次代码只在本地修改和验证，服务器由操作者手动上传、启动和验收。以下命令是 Linux 操作示例；先把路径、服务账号、Python 路径、镜像版本、域名替换为目标机实际值。不要把开发机 `.env`、私有语料、密钥、审计日志或整个 Git 目录上传给客户。

本次新增的是 Python 标准库 HTTP 服务，入口 `python -m law_service`，直接复用 SQLite/FTS5 检索引擎，不需要 PostgreSQL、Redis 或应用的 Python 依赖。服务和语料只部署在我方机器；客户运行主应用的远程模式。背景见 [拆分方案](law-service-split-plan.md)，监控、异常判定和周报见 [运营说明](law-service-operations.md)。

## 1. 发布边界与准备

先在 issue 分支跑服务、客户端、分发边界测试；再合入 `dev` 跑本地初步端到端测试。记录测试通过的提交号和私有数据版本，手动上传同一提交的部署物到测试机。完成本文服务器验收后，再按批次提交主分支 PR；本地通过不代表服务器已经验证。

独立法库服务支持 Python 3.10 及以上（本地已验证 3.10 / 3.13），主应用仍按项目要求使用 Python 3.13。我方服务器还需 SQLite FTS5 trigram 支持、Linux/systemd（或 Docker Compose v2）、可写的索引/日志目录，以及从独立私有数据仓同步好的法库数据。先确认：

```bash
python3 --version
python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\"); print(sqlite3.sqlite_version)"
```

主仓 `git ls-files RAG/data/` 必须为空，磁盘上的私有语料可保留。私有数据仓访问与
manifest 校验见 [数据同步说明](../RAG/README.md)。取消当前版本的跟踪不清除 Git 历史，
本修复不表示历史已清洗。数据仓凭据仅留在我方机器。请勿在客户机执行语料同步或索引预构建。

## 2. 我方 Linux 服务器：systemd

示例目录约定如下，实际安装位置可调整；调整后同步修改环境文件和 unit 的 `WorkingDirectory`、`ExecStart`、`ReadWritePaths`。

| 目录 | 用途 | 权限 |
| --- | --- | --- |
| `/srv/lawver-law/releases/<提交号>/` | 本次服务代码 | root 管理，服务只读 |
| `/srv/lawver-law/current` | 指向当前版本的符号链接 | root 管理 |
| `/srv/lawver-law/data/` | 私有法库语料 | 服务只读 |
| `/etc/lawver-law/keys.json` | 独立客户 key 与策略 | `0640 root:lawver-law` |
| `/etc/lawver-law/environment` | systemd 配置 | `0640 root:lawver-law` |
| `/var/lib/lawver-law/cache/` | SQLite、manifest、构建锁 | 服务可写 |
| `/var/lib/lawver-law/audit/` | 审计及轮转备份 | 服务可写，仅运维读取 |

### 2.1 从本地上传明确的代码集合

先提交测试通过的本地修改，再从该提交导出服务代码包。以下包只给我方服务器，不给客户；不包含私有语料或配置。`git archive` 使用指定提交中的内容，请将 `RELEASE_COMMIT` 改成已验证的实际提交号：

```bash
git archive --format=tar.gz --output=law-service-code.tar.gz RELEASE_COMMIT \
  law_service RAG/law_data_search.py scripts/law_service_ops.py \
  deploy/law-service deploy/systemd/lawver-law.service \
  deploy/systemd/lawver-law-check.service deploy/systemd/lawver-law-check.timer \
  deploy/systemd/lawver-law-report.service deploy/systemd/lawver-law-report.timer
```

使用你现有的上传方式将包放到服务器暂存目录。先列出包内容，再解包到一个全新的版本目录；旧版本保留以便回滚。语料按已有私有数据流程单独上传/同步到我方服务器并校验 manifest；不要把语料拷进代码包。

```bash
# 首次安装，以有 sudo 权限的部署账号操作。
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin lawver-law
sudo install -d -m 0755 /srv/lawver-law/releases
sudo install -d -o root -g lawver-law -m 0750 /etc/lawver-law
sudo install -d -o lawver-law -g lawver-law -m 0700 \
  /var/lib/lawver-law/cache /var/lib/lawver-law/audit
tar -tzf law-service-code.tar.gz
sudo install -d -m 0755 /srv/lawver-law/releases/RELEASE_COMMIT
sudo tar -xzf law-service-code.tar.gz -C /srv/lawver-law/releases/RELEASE_COMMIT
sudo ln -s /srv/lawver-law/releases/RELEASE_COMMIT /srv/lawver-law/current
```

已有账号或 `current` 时跳过创建，不要覆盖其业务数据。升级切换符号链接的原子方法见回滚部分。

### 2.2 建立 key 与环境配置

将示例复制到 `/etc/lawver-law` 后编辑。仓库示例只有占位文本，不能直接使用。每个客户独立生成随机 key，另外创建独立验收 key、`rpm=1` 的限流测试 key 和 `canary:true` 的诊断 key；不要共用生产客户 key 做压测。

```bash
sudo install -o root -g lawver-law -m 0640 \
  /srv/lawver-law/current/deploy/law-service/environment.example /etc/lawver-law/environment
sudo install -o root -g lawver-law -m 0640 \
  /srv/lawver-law/current/deploy/law-service/keys.example.json /etc/lawver-law/keys.json
sudoedit /etc/lawver-law/environment
sudoedit /etc/lawver-law/keys.json
```

生成值可用 `python3 -c "import secrets; print('lvk_' + secrets.token_urlsafe(32))"`；仅在受控终端生成并传递，不粘贴到 issue、PR、聊天记录或截图。首次配置完成后检查 JSON 语法和服务账号读取权限，不输出文件内容：

```bash
sudo -u lawver-law python3 -c "import json; json.load(open('/etc/lawver-law/keys.json')); print('keys JSON readable')"
sudo -u lawver-law test -r /srv/lawver-law/data
sudo -u lawver-law test -w /var/lib/lawver-law/cache
```

核心变量：

| 变量 | 用途 |
| --- | --- |
| `LAW_LISTEN` | systemd 保持 `127.0.0.1:8084` |
| `LAW_DATA_DIR` | 私有语料绝对路径 |
| `LAW_DB_PATH` | 可写 SQLite 路径；manifest/构建锁默认同目录 |
| `LAW_KEYS_FILE` | key 策略文件绝对路径 |
| `LAW_AUDIT_LOG` | 审计 JSONL 路径 |

`EnvironmentFile` 使用 `KEY=value` 格式，不写 `export`。路径包含空格时按 systemd 环境文件规则加引号。独立服务不读取主应用 `.env`。

### 2.3 启动与绑定检查

确认 `/usr/bin/python3` 是 Python 3.10 及以上且通过前面的 SQLite 检查；Ubuntu 22.04 可直接使用其 Python 3.10，不必升级系统 Python。若使用其它解释器或已有虚拟环境，应修改 unit `ExecStart` 为绝对路径。不需要给独立服务执行主应用的 `uv sync`。从示例复制 unit 并检查实际用户/路径：

```bash
sudo install -m 0644 /srv/lawver-law/current/deploy/systemd/lawver-law.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/lawver-law.service
sudo systemctl daemon-reload
sudo systemctl enable --now lawver-law.service
sudo systemctl status lawver-law.service --no-pager
sudo journalctl -u lawver-law.service -n 50 --no-pager
sudo ss -ltnp '( sport = :8084 )'
curl --fail --silent --show-error http://127.0.0.1:8084/healthz
```

监听应只有回环地址；构建索引期间 `/healthz` 返回 `503 {"ready":false}`，就绪后返回 `200`。首次构建等待完成，不要因短暂 `503` 连续重启。构建失败会保持未就绪，修复文件/权限后重启。首次发请求前确认 audit 目录可写。

### 2.4 独立 HTTPS 入口

在现有隧道或反向代理新增专用主机名，将 `https://law-api.<你的域名>` 路由至 `http://127.0.0.1:8084`。保持 TLS 校验；不要把公网 8084 直接打开，也不复用主产品分流核心的路由表。

Cloudflare Tunnel ingress 示例（替换域名并保留现有其它路由与末尾兜底）：

```yaml
ingress:
  - hostname: law-api.example.invalid
    service: http://127.0.0.1:8084
  # 原有产品路由……
  - service: http_status:404
```

配置 API 路由不缓存，Authorization 不写接入层日志，禁止记录请求体。应用自身只信任 TCP 对端地址；隧道后审计可能只看到回环/网桥地址。客户出口 IP 允许列表应在隧道/反向代理层落实，不要为获取地址而无条件采信任意 `X-Forwarded-For`。需要更强隔离时在入口配置 mTLS。

## 3. 我方服务器：独立容器（systemd 的替代选项）

独立法库镜像与客户应用镜像分别构建。以下命令在上传同一代码提交的我方服务器执行，不需要将语料放入 Docker 构建上下文：

```bash
docker build -f deploy/docker/Dockerfile.law-service \
  --build-arg LAW_UID="$(id -u lawver-law)" \
  --build-arg LAW_GID="$(id -g lawver-law)" \
  -t lawver-law:RELEASE_COMMIT .
sudo install -m 0600 deploy/law-service/compose.env.example /etc/lawver-law/compose.env
sudoedit /etc/lawver-law/compose.env
docker compose --env-file /etc/lawver-law/compose.env \
  -f deploy/docker/compose.law-service.yml config --quiet
docker compose --env-file /etc/lawver-law/compose.env \
  -f deploy/docker/compose.law-service.yml up -d
docker compose --env-file /etc/lawver-law/compose.env \
  -f deploy/docker/compose.law-service.yml ps
```

容器内监听 `0.0.0.0:8084`，宿主发布仍固定回环 `127.0.0.1:8084`。语料、key 目录只读挂载；仅 `/var/lib/lawver-law` 可写，其宿主 UID/GID 必须与镜像构建参数一致。配置源目录必须已经存在，避免 Docker 默默创建空目录。key 挂载整个目录，使原子替换文件后的热重载可见。此容器单独运行，不依赖应用基建网络。不要同时启用 systemd 主服务与容器争用 8084。

构建独立镜像需完整代码检出，或单独上传 `law_service/`、`RAG/law_data_search.py`、`deploy/docker/Dockerfile.law-service` 与 Compose 文件；上节最小 systemd 代码包默认不包含 Dockerfile。

## 4. 服务器验收（人工执行并回填结果）

使用新建测试 key，在 shell 中通过 `read -r -s` 输入，避免写进 shell 历史。先测我方回环，再从客户服务器测 HTTPS；第二次限流验收换新 rate key，或等待一个完整限速窗口，避免第一次调用就已达上限：

```bash
read -r -s -p 'Acceptance key: ' LAW_VERIFY_KEY; echo
read -r -s -p 'NEW rpm=1 key: ' LAW_ACCEPTANCE_RATE_KEY; echo
read -r -s -p 'Canary diagnostic key: ' LAW_CANARY_KEY; echo
export LAW_VERIFY_KEY LAW_ACCEPTANCE_RATE_KEY LAW_CANARY_KEY
LAW_VERIFY_URL=http://127.0.0.1:8084 bash deploy/law-service/verify.sh
# 客户端网络验收时，在持有验收脚本的受控终端执行同一条命令：
# LAW_VERIFY_URL=https://law-api.<你的域名> bash deploy/law-service/verify.sh
unset LAW_VERIFY_KEY LAW_ACCEPTANCE_RATE_KEY LAW_CANARY_KEY
```

脚本使用 curl，断言无 key `401`、健康 `ready:true`、`/v1/meta` 的有效 schema/摘要与非零语料数、三个业务端点 `success:true` 及正确的非空结果结构、独立低配额 key 的 `200 → 429` 和 `Retry-After`，可选验证专用 canary。curl 通过标准输入读取鉴权头，不在进程参数里放 key。默认用民法典第一条和“违约责任”检索；数据集不含这些测试法条时，通过 `LAW_VERIFY_TITLE`、`LAW_VERIFY_NUMBER`、`LAW_VERIFY_QUERY`、`LAW_VERIFY_TEXT` 指定已知会命中的合成验收输入，脚本用 Python 安全编码 JSON。设置 `LAW_VERIFY_SHA256` 可断言 `/v1/meta` 摘要等于批准的数据版本。正文与信源的语义仍需按同版本本地结果人工对照。

验收还需补以下检查并记录提交号、数据版本、日期和结果，不记录 key 或案件原文：

1. 用同一语料版本比对本地与远程 `get_article`、`search_article`、`get_linked_content` 输出，确认正文与信源一致。
2. 检查审计只含时间、key 名、端点、query 长度/hash、耗时、结果数、状态、对端 IP；不包含 Authorization、key 值、查询原文、返回法条正文。用合成案件关键词验证日志不出现原文。
3. 编辑测试 key 为 `enabled:false`，原子替换 `keys.json`；无需重启，应返回 `403`。无效 key 应 `401`。错误 JSON/丢失 keys 文件必须 `503`，修复后自动恢复。
4. canary 只对 `canary:true` key 且严格查询 `__lawver_canary__` 返回诊断标记；普通 key 和普通法律查询不注入虚构法条。验收后吊销/移除测试 key。
5. 停止服务或暂时阻断测试客户的访问，远程工具明确返回暂不可用，不回退读取本地语料、不生成本地索引；恢复后无需同步语料即可恢复。
6. 用客户专用分发物/镜像在无 `RAG/` 的干净环境启动，完成登录和三项法条工具的实际对话走查。

## 5. 客户交付：不带语料和检索引擎

客户只运行主应用、基建与介绍页；出网通过 HTTPS 到我方法库服务。详见随分发物附带的 [客户安装步骤](../deploy/customer/README.md)。

### 5.1 源码包与包内复验

默认打包只选取 Git 已跟踪且通过客户文件允许清单的文件，读取当前工作区内容；发布前应先提交测试通过的代码。整个 `RAG/`、`law_service/`、`.git`、真实 `.env`、keys、日志、运行数据、缓存、历史部署方案、自营部署脚本一律不进入客户包。`.env_example` 与客户专用占位配置可以交付。私有语料仍留在工作区，不需要删除。

```bash
git ls-files RAG/data/
python scripts/package-customer.py --verify-only
python scripts/package-customer.py --output customer-RELEASE_COMMIT.zip
python scripts/package-customer.py --verify customer-RELEASE_COMMIT.zip
```

`git ls-files` 必须零输出。归档带 `CUSTOMER-MANIFEST.json`，包含所交付文件的 SHA-256，验证命令同时检查敏感路径和所有文件校验和。输出归档已存在时拒绝覆盖；目录导出用 `--output-dir NEW_OR_EMPTY_DIRECTORY`，非空目录拒绝写入。默认不带 `dist`，需要预构建网页时先从同一提交执行 `pnpm exec vite build`，再加 `--include-dist`。客户源码包不包含自营 Dockerfile；镜像由我方从主仓构建。

`--no-git-context` 只消费由可信 Git 导出流程生成的 `CUSTOMER-MANIFEST.json`，
校验清单、文件 SHA-256 与完整成员集合；缺失清单、内容变化或混入额外文件即拒绝。
它不会扫描原始工作区选择源码。正常源码归档保持默认 Git 模式，以保留语料脱跟踪门禁。
清单用于验证已批准导出物的完整性，不能替代通过可信渠道核验版本与发布摘要。

### 5.2 客户专用镜像

客户只能使用 `deploy/docker/Dockerfile` 的 **`customer` target**，不能使用保留本地检索引擎的 `runtime` target，也不要直接执行默认自营 `build.sh` 作为客户交付。构建/导出例：

```bash
LAWVER_APP_UID=1000 LAWVER_APP_GID=1000 \
  bash deploy/docker/build-customer.sh --tag RELEASE_COMMIT
docker run --rm --entrypoint python lawver-customer:RELEASE_COMMIT \
  -c "from pathlib import Path; p=Path('/app'); assert not (p/'RAG').exists(); assert not (p/'law_service').exists(); assert not (p/'.git').exists(); assert not (p/'.env').exists(); print('customer image boundary OK')"
docker save -o lawver-customer-RELEASE_COMMIT.tar lawver-customer:RELEASE_COMMIT
```

UID/GID 用客户持久化目录实际值，1000 只是示例。只交付最终 `customer` 镜像，不能推送/导出包含自营代码的构建中间 stage、构建缓存或完整主仓副本。客户 Compose 使用 `compose.customer.yml`，其 app 不创建任何 RAG 卷；不要叠加 `compose.self-hosted.yml`，也不运行 `prebuild-law-db.sh`。

构建脚本先从 Git 已跟踪文件生成独立临时上下文，只包含清单内应用文件及
`scripts/package-customer.py`、`deploy/docker/Dockerfile` 两个构建辅助文件。
未跟踪的内部源码不会被送入 Docker；无 Git 导出会校验上下文的成员与哈希，
两个辅助文件不进入客户应用层。网页从这份受控源码重新构建，不复用工作区 `dist`。
脚本只构建本地 `lawver-customer:<tag>`，不推送，结束时清理其临时目录。

只准备上下文（无需 Docker，也不构建镜像）可执行：

```bash
python scripts/package-customer.py --build-context TEMP/customer-build-RELEASE_COMMIT
```

目标须为新目录或空目录；此模式不接受 `--include-dist`。后续手动构建的 context
和 Dockerfile 路径都必须指向该目录，不能把原始仓库根目录作为客户构建上下文。
GitHub 发布工作流对 `customer` 使用相同准备流程，自营 `runtime` 继续使用原有上下文。

## 6. 客户出网与隐私边界

客户服务器需允许 DNS 和到指定法库域名的 TCP/443 出站，证书链可验证；其他第三方模型/搜索服务依赖沿用既有部署配置。HTTPS 入口不可用、缺少 URL/key 或 key 被吊销时，客户法条功能报告不可用；纯离线客户不适用此远程架构。

主应用的远程法库适配器使用独立直连会话，不读取 `HTTP_PROXY`、`HTTPS_PROXY`、
`ALL_PROXY`、`NO_PROXY` 的大小写变体或 `.netrc`。同一进程内模型、搜索等其它客户端
仍按各自配置联网；配置准备脚本也不再补写 `NO_PROXY/no_proxy`，以免影响它们。
该适配器仍启用 Requests 默认信任库与 TLS 证书/主机名校验，但不读取环境中的
`REQUESTS_CA_BUNDLE`、`CURL_CA_BUNDLE`。要求出口代理或私有 CA 的环境需要另外明确
设计其法库网络与信任配置，并在目标机验收；不能用关闭证书校验的方式接入。

账号、完整对话、附件、工作区和记忆仍由客户主应用保管；法库服务收到调用工具所需的 `title/number`、搜索 `query` 或引用抽取 `text`。这些字段可能含案件信息，因此不能承诺“没有客户内容出网”。应在客户网络/隐私约定中明确这次外呼，并尽量仅传法名、条号、最小检索短语。服务无查询/结果磁盘缓存，审计不落原文；入口代理、隧道、APM 同样禁记请求体与 Authorization。法条返回值可能作为客户已有业务对话的一部分保留，服务端不会向客户交付整库/索引或建立独立法库缓存。

## 7. 更新、轮转、回滚

语料更新先放到我方新的数据目录，按私有 manifest 校验。备份当前索引/manifest 和配置，调整 `LAW_DATA_DIR` 指向新版本，重启服务并等待 `/healthz` 就绪，检查 `/v1/meta` 的数据摘要变化，再做三端点验收。**不要直接覆盖正在读取的语料目录或将 SQLite 文件原地热替换。** 单实例重建时会暂时返回 `503`，安排维护窗口；限流和日配额为进程内计数，重启会重置，入口层可补更长周期限制。

key 更新用同目录新文件写好、校验 JSON、设置相同属主/权限后原子 `mv` 覆盖；有效修改即时生效。吊销某客户只需改该条 `enabled:false`。密钥文件、数据与审计备份保存在私有运维备份范围，不进 Git 或客户归档。

审计文件内置按 10 MiB 轮转、保留 7 份备份（另有当前文件）；运维按隐私保留期归档或清理更早日志，留意状态目录磁盘容量。报告要覆盖轮转文件，详见运营说明。服务日志与审计访问均按最小权限设置。

代码升级用新的独立 release 目录，保留旧代码/配置/数据版本记录；创建新符号链接后原子替换：

```bash
sudo ln -s /srv/lawver-law/releases/NEW_COMMIT /srv/lawver-law/current.next
sudo mv -Tf /srv/lawver-law/current.next /srv/lawver-law/current
sudo systemctl restart lawver-law.service
```

失败时用同样方式切回 `OLD_COMMIT`，恢复相配的配置；如 schema 变化，停止服务后恢复旧数据/索引/manifest 成套副本，再启动验收。不要删除客户业务库、工作区或运行数据。容器回滚仅把 `LAW_IMAGE` 切回旧不可变标签/摘要并 `up -d`，必要时同样恢复相配的我方数据状态。

客户侧回滚到上一个已验收的 **customer** 镜像与配置，保留 URL/key 远程模式；不得临时改用 `runtime` 镜像或向客户补发语料兜底。服务器验收完成前，PR/发布记录中应明确“本地已验证，服务器待人工上传验收”。

## 8. 定时检查与周报

模板在 `deploy/systemd/lawver-law-{check,report}.{service,timer}`，安装后按实际路径修改 unit。**启用检查 timer 前**，先为 `keys.json` 中的 `monitor` 条目生成独立随机 key，并将同一值写入受限环境文件 `LAW_MONITOR_KEY`；默认 `30 rpm / 1000 次每日` 足够五分钟一次鉴权巡检，不能使用客户 key。检查每五分钟验证健康和鉴权 `/v1/meta`，周报每周一北京时间 09:00 输出到 journal。默认不启用 canary 检查；如需启用，先签发专用 `canary:true` key，将其值以 `LAW_CANARY_KEY=...` 写入受限环境文件，再用 `systemctl edit lawver-law-check.service` 的 `[Service]` override 清空 `ExecStart=`，重写同一条命令并追加 `--canary-key-env LAW_CANARY_KEY`。对接现有告警系统可在 check unit 的本地 override 添加 `OnFailure=`；代码和模板不主动向外部渠道发消息。

```bash
sudo install -m 0644 /srv/lawver-law/current/deploy/systemd/lawver-law-check.service /etc/systemd/system/
sudo install -m 0644 /srv/lawver-law/current/deploy/systemd/lawver-law-check.timer /etc/systemd/system/
sudo install -m 0644 /srv/lawver-law/current/deploy/systemd/lawver-law-report.service /etc/systemd/system/
sudo install -m 0644 /srv/lawver-law/current/deploy/systemd/lawver-law-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lawver-law-check.timer lawver-law-report.timer
sudo systemctl start lawver-law-check.service lawver-law-report.service
sudo journalctl -u lawver-law-check.service -u lawver-law-report.service --since today
```

容器部署时也可在宿主保留同版本 `scripts/law_service_ops.py` 运行这些定时任务，修改 unit 的工作目录和审计宿主路径；宿主探针仍访问回环发布端口。阈值调整、故障演练和周报解读见 [运营说明](law-service-operations.md)。
