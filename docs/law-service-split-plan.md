# 法律数据库独立化方案（法库检索服务拆分）

> 状态：草案 · 2026-10-13
>
> 2026-10-20 修复分支补充：当前版本取消跟踪 `RAG/data/`，私有语料同步入口为
> `scripts/sync-rag-data.sh`，默认数据版本 `v2026.10.17`。本次不重写 Git 历史，
> 也不代表部署验收或客户分发门禁全部通过；当前流程见 [RAG/README.md](../RAG/README.md)
> 和 [验证清单](issue-13-validation.md)。下文的资产规模与进程内链路为原方案基线。
> 关联文档：[deployment.md](deployment.md)（生产部署手册）、[architecture/](architecture/)（架构图）
>
> 一句话方案：把 `RAG/data/` 语料与检索引擎抽成独立部署的**法库检索服务**，只跑在我们自己的服务器上，对外暴露带鉴权的 HTTPS 检索 API；B 端客户服务器上只部署主功能实例，通过远程调用获取法条，**任何法律语料都不再落客户机器**。

---

## 1. 背景与目标

Lawver 准备面向 B 端客户做私有化部署：主功能实例（FastAPI + 前端 dist + PostgreSQL + Redis）部署到客户自己的服务器。但当前法律检索能力是**进程内私有资产**——法库随主应用一起构建、一起分发，这意味着每一次 B 端交付都会把整套语料带进客户机房。

本方案的目标：

1. **数据零交付**：法库语料与索引只存在于我方服务器，客户部署物中不包含任何法律数据文件。
2. **客户部署不受影响**：主功能实例在客户服务器上的安装、运行、数据主权（业务数据全部留在客户侧）保持现状。
3. **检索能力不降级**：法条精确查询、模糊检索、信源链接三个工具的行为与本地模式一致。
4. **防批量导出**：即使 API 暴露在公网，也让"低成本复制整库"不可行、可发现、可止损。

### 一个前提认知：防的是"复制整库"，不是"看到一条"

法律、行政法规、司法解释的文本本身是官方公开信息。这套语料的真正资产是：**收集整理的工作量**（尤其 3700+ 件地方性法规的覆盖）、结构化成果（规范别名表、北大法宝引证码/URL 对应、条号切分）、以及建立在语料之上的检索质量（中文数字条号归一化、trigram FTS + 打分、引用抽取）。因此防护设计的矛头是**阻止批量、程序化地重建整库**，而不是阻止单条公开文本在对话中出现——后者本来就是产品功能。附带收益：语料来源涉及第三方平台的引证信息，技术上不再向客户交付语料副本，也降低了再分发授权层面的暴露面（商务边界另行评估）。

## 2. 原方案基线

### 2.1 法库资产

| 资产 | 位置 | 规模 | 是否入 git |
| --- | --- | --- | --- |
| 原始语料 | `RAG/data/`（法律/行政法规/司法解释/地方性法规/监察法规 5 类） | 4937 个 JSON，约 56 MB，含 `pkulaw.com` 信源 URL 与 CLI 引证码 | **是（4943 个文件被跟踪）⚠️** |
| 构建产物 | `RAG/cache/law.db`（SQLite + FTS5 trigram） | 约 198 MB；laws 4,937 条、law_aliases 11,221 条、articles 81,966 条 | 否（`RAG/cache/` 已 gitignore） |
| 检索引擎 | `RAG/law_data_search.py` | 纯 Python + sqlite3，无向量依赖 | 是 |

上述基线跟踪了语料。本修复取消当前版本中的跟踪，但旧提交仍含语料；这部分历史
与已有 clone 不会因 `.gitignore` 或 `git rm --cached` 改变。历史处理与当前交付物清洗
分别核对（见 §6 与 §8 阶段 0）。

### 2.2 检索链路（全进程内，无任何远程通道）

```
agent 循环（backend/function_calling.py）
  → 工具注册表 tools/__init__.py:359-515（get_article / search_article / get_linked_content）
    → 适配层 backend/mcp/pkulaw_client.py        ← 业务侧唯一 import RAG 的收口
      → RAG/law_data_search.py（exact / fuzzy / link 三函数，直连 SQLite + FTS5）
```

- 启动期由 `backend/services/law_cache.py` 在 FastAPI lifespan 里跑 `ensure_law_database_ready`（按 manifest sha256 增量重建索引），这是客户部署会在启动时碰语料的唯一位置。
- OCP 输出审查（`backend/ocp.py:120-127`）也会回调 `get_linked_content` / `search_article` 补信源，走同一适配层。
- 案例匹配（`match_legal_case`）**不在本库**，走得理开放 API（`backend/mcp/deli_client.py`），已是外部依赖，与本方案无关（见 §10）。
- `backend/mcps.py` 对 `ensure_law_database_ready` 做 re-export，`law_cache.py` 从那里取。

### 2.3 与业务数据的关系：本来就是分开的

业务库是 PostgreSQL 17（`LAWVER_DATABASE_URL`，账号/会话/工作台/计费），法库是独立 SQLite 文件，两者**无任何引擎关联、外键或共享连接**。本方案不需要动业务库，也不需要动记忆库（`data/memory_cache.sqlite3`）。

### 2.4 现有部署拓扑

见 [deployment.md](deployment.md)：Cloudflare 隧道 → 127.0.0.1:8080 分流核心（router）→ 8081 功能页 / 8082 介绍页；旁挂 SearXNG（8083）与 PostgreSQL（5432）；三件套 systemd 单元、全部只监听回环。本方案沿用这套模式新增一个单元。

## 3. 目标架构

```
┌─ 客户服务器（B 端机房）────────────────┐      ┌─ 我方服务器 ──────────────────────┐
│                                        │      │                                   │
│  lawver-app（FastAPI + dist, 8081）    │      │  law-api.<我方域名>               │
│    └─ law_service_client（新，HTTP） ───┼─ HTTPS ─→ 隧道 → 127.0.0.1:8084      │
│  PostgreSQL 5432 / Redis / SearXNG     │  Bearer Key   lawver-law.service      │
│  文件工作区 TEMP/Result、记忆库         │      │    └─ RAG/data 语料 + law.db      │
│                                        │      │    └─ keys.json / 审计日志         │
│  ✗ 不含 RAG/、不含任何语料、无索引构建  │      │  ✓ 语料与索引仅存于此              │
└────────────────────────────────────────┘      └───────────────────────────────────┘
```

**数据边界**：

| | 客户服务器 | 我方服务器 |
| --- | --- | --- |
| 业务数据（账号/会话/工作台/计费） | ✅ 全部留在客户侧 | — |
| 用户上传/生成的文件 | ✅ 客户侧 | — |
| 法律语料 + 索引 + 检索逻辑 | ❌ 零交付 | ✅ 仅存于此 |
| 对话记忆 | ✅ 客户侧 | — |

这个架构还带来两个顺手的收益：**法规更新只改我方一处**，所有客户部署即时生效（不再需要"重新分发数据包 + 各点重建索引"）；客户实例**启动不再构建 198 MB 索引**，冷启动更快、磁盘占用更小。

## 4. 法库检索服务设计

### 4.1 服务形态

- 独立 FastAPI 小服务，代号 **lawver-law**，代码放本仓新顶层目录 `law_service/`，以库形式复用 `RAG/law_data_search.py`（该模块零改动或近零改动）。
- **零外部依赖**：不需要 PostgreSQL、不需要 Redis。SQLite 只读 + 一个 keys 文件 + 滚动审计日志，单进程即可承载（现有检索是毫秒级、低频的 agent 工具调用）。
- systemd 单元 `lawver-law.service`，监听 `127.0.0.1:8084`，公网暴露经由隧道（见 §7）。
- 语料目录与库路径通过环境变量指定（服务端不再硬编码 `RAG/` 相对路径），例如 `LAW_DATA_DIR` / `LAW_DB_PATH`。

### 4.2 API 契约（`/v1` 前缀）

三个业务端点与 `law_data_search.py` 三函数一一对应，**响应体沿用现有 `{"success": ..., "data"/"message"/"text"}` 形态**，客户端几乎透传，`pkulaw_client.py` 现有的格式化与错误处理逻辑不动：

| 端点 | 请求体 | 对应函数 | 说明 |
| --- | --- | --- | --- |
| `POST /v1/laws/exact` | `{"title": str, "number": str}` | `law_exact_search` | 精确取条，返回单条全文 + 信源 URL |
| `POST /v1/laws/search` | `{"query": str, "limit": int ≤ 20}` | `law_fuzzy_search` | 模糊检索，上限对齐 `MAX_SEARCH_LIMIT` |
| `POST /v1/laws/links` | `{"text": str, "limit": int}` | `law_link_search` | 引用抽取 → 信源链接 |
| `GET /v1/meta` | — | — | 数据版本（manifest 摘要）、schema 版本，供诊断与核对更新 |
| `GET /healthz` | — | — | 存活/索引就绪 |

错误语义：`401` key 无效、`403` 已禁用、`429` 限流或配额耗尽、`503` 索引重建中。全部请求要求 `Authorization: Bearer lvk_...`。

### 4.3 鉴权与 Key 管理

- 每个 B 端部署发放一个独立 key（`lvk_` 前缀随机串），**可独立吊销、独立统计、独立限流**——一个客户泄露不牵连其他客户。
- key 清单落 `keys.json`（不入仓）：

  ```json
  {
    "keys": [
      { "key": "lvk_...", "name": "customer-a", "enabled": true,
        "rpm": 30, "daily_quota": 20000 }
    ]
  }
  ```

- 支持 mtime 热重载（改文件即生效，无需重启服务），吊销 = `enabled: false`。
- 服务端限流用进程内滑动窗口按 key 计数（单实例部署，不需要分布式限流）。

### 4.4 防泄露设计（本方案核心）

| 措施 | 防什么 | 做法 |
| --- | --- | --- |
| 无批量端点 | 程序化重建整库 | 不提供列举/翻页/导出/全量接口；`search`/`exact` 空查询直接 400；`limit` 硬上限 20；`exact` 必须给出精确法律名 + 条号（天然"按需取用"形态） |
| 限流 + 日配额 | 高速抓取 | 每 key `rpm` 与 `daily_quota`，超限 429；配额按天计数 |
| 异常模式检测 | 低速长期抓取 | 统计每 key 单位时间 query 去重率与调用频率；去重率异常低（字典遍历特征）或持续贴近限速上限时告警，可自动降速直至吊销 |
| 审计日志 | 事后溯源 | 除精确 `/healthz` 外逐请求记录：时间 / key 名 / 端点 / query **长度与 sha256（不落原文）** / 耗时 / 结果数 / TCP 直连对端 IP（代理后通常为回环或网桥地址；客户分析按 key，真实来源另查可信入口日志） |
| 金丝雀数据 | 泄露溯源 | 不入库；由服务端对特定查询按 key 动态注入 1–2 条虚构条目（标题生僻、内容带该 key 的唯一盐）。任一渠道出现整库副本时，凭 canary 定位泄露来源客户 |
| 网络层 | 任意来源访问 | 仅回环监听 + 隧道 TLS；可选按客户出口 IP 配允许列表；需要更强保证的客户可开 mTLS（TLS 客户端证书） |
| 分发物清洗 | 数据随包外流 | 客户构建物不含 `RAG/`（见 §6），并由架构边界测试断言 |
| 密钥卫生 | key 入仓/入档 | key 只落客户部署机 `.env` 与我方 keys 文件，永不进仓库与文档（与 deployment.md 的凭据纪律一致） |

**审计不落 query 原文是刻意设计**：检索 query 由 LLM 生成，`exact`/`links` 的输入可能携带客户案件信息，落原文会让我方服务器变成客户数据的二次汇聚点——既引隐私问题，又制造新的泄露面。哈希足以支撑限流去重率分析与滥用比对。

### 4.5 服务端配置（`.env`）

```bash
LAW_LISTEN = "127.0.0.1:8084"
LAW_DATA_DIR = "/srv/lawver-law/RAG/data"
LAW_DB_PATH = "/srv/lawver-law/cache/law.db"
LAW_KEYS_FILE = "/srv/lawver-law/keys.json"
LAW_AUDIT_LOG = "/var/lib/lawver-law/audit.jsonl"
LAW_RATE_LIMIT_ENABLED = "1"
```

## 5. 主应用改造

改造面是本方案最大的优点：**收敛在 3 个文件 + 配置**，工具注册表、agent 循环、OCP、`mcps.py` 全部不动。

### 5.1 改造点清单

| 文件 | 动作 | 内容 |
| --- | --- | --- |
| `backend/mcp/law_service_client.py` | **新增** | HTTP 客户端；提供与 `law_exact_search` / `law_fuzzy_search` / `law_link_search` **同签名、同 JSON 返回**的三个函数，内部走 `/v1` 端点 |
| `backend/mcp/pkulaw_client.py` | 修改 | 顶部按 `LAWVER_LAW_SERVICE_URL` 分发：配置了 URL → 转发到 `law_service_client`；未配置 → 延迟 import `RAG.law_data_search` 走本地（延迟 import 保证客户机器上没有 `RAG/` 也能正常运行远程模式） |
| `backend/services/law_cache.py` | 修改 | 远程模式直接返回 `{"mode": "remote"}` 跳过本地构建，可选 ping 一次 `/healthz` 把可达性写进启动日志 |
| `.env_example` | 修改 | 新增 `LAWVER_LAW_SERVICE_URL` / `LAWVER_LAW_SERVICE_KEY` / `LAWVER_LAW_SERVICE_TIMEOUT`（留空 = 本地模式，兼容所有现存环境） |
| `tests/test_architecture_boundaries.py` | 修改 | 新增边界用例：远程模式下不 import `RAG.*`；客户构建物断言无 `RAG/data` 文件 |
| `law_service/` | **新增** | 检索服务本体（§4），仅在己方服务器部署 |

`tools/__init__.py` 的注册、`backend/ocp.py` 的回调、`backend/mcps.py` 的转发边界均不需要改动——它们感知不到适配层背后换成了 HTTP。

### 5.2 双模式开关

- **本地模式**（默认）：不配 `LAWVER_LAW_SERVICE_URL`，行为与今天完全一致，开发环境与自营部署零迁移成本。
- **远程模式**：配 URL + KEY 后生效，B 端交付一律此模式。

### 5.3 超时与降级

- 连接超时 3 s、读取超时 10 s。本地 trigram 检索是毫秒级，加一次公网 RTT 对 agent 工具调用节奏无感；服务端 `/healthz` 和鉴权 `/v1/meta` 双探针与 p95 延迟接监控，分别覆盖索引就绪与密钥/审计可用性。
- 失败重试至多 1 次；仍失败则沿用 `pkulaw_client.py` 现有的结构化错误 JSON 路径返回"法条检索暂不可用"，agent 会向用户如实说明——**不做客户侧结果缓存、不做部分语料热缓存落盘**：任何落盘都是一次部分数据交付，违背方案目标。客户明确要求离线兜底的，走 §7.3 的商务例外，不走技术缓存。

## 6. 数据出库与分发物清洗

阶段 0 的核心动作，先于一切服务化改造：

1. `git rm -r --cached RAG/data/`，`.gitignore` 追加 `RAG/data/`；工作区文件保留。
2. 语料迁入**私有数据仓**（私有 repo 或对象存储），只同步到我方服务器；此后语料的增删改走数据仓，不再经代码仓。
3. ⚠️ **git 历史仍含全部语料**：仓库保持私有的前提下风险可接受；若未来计划开源/公开，必须先 `git filter-repo` 清洗历史中的 `RAG/data/` 再公开。把这条写进开源前检查单。
4. 打包/构建脚本（含未来 Docker 镜像）排除整个 `RAG/` 目录；B 端部署手册单独成文，不含任何语料同步步骤。
5. 边界测试断言客户构建物中 `RAG/data` 不存在，防止将来回归。

## 7. 部署方案

### 7.1 我方服务器（新增 lawver-law）

```
/srv/lawver-law/          服务代码 + RAG/data 语料 + cache/law.db
/srv/lawver-law/keys.json key 清单（0600）
/var/lib/lawver-law/      审计日志（lawver 用户属主）
```

- systemd 单元 `lawver-law.service`（对齐 `deploy/systemd/lawver-app.service` 的写法：`lawver` 用户、`python agent.py` 等价入口、只监听回环）。
- 公网暴露：**独立子域**（如 `law-api.<我方域名>`），Cloudflare Tunnel 增加一条 ingress hostname 直指 `127.0.0.1:8084`。不走产品域名的 8080 分流核心——避免与介绍页/功能页的路径表约定产生耦合，也让法库 API 的访问日志、防护策略独立。
- 数据更新流程：私有数据仓发布获批准的版本 → 在未投产的候选目录同步并校验语料 →
  构建/验证匹配的索引和三个检索端点 → 按已验证 release 切换服务并检查 `/v1/meta`。
  同步脚本不会自行重建索引或重启服务；路径和备份约定见 [RAG/README.md](../RAG/README.md)。

### 7.2 客户服务器（B 端部署）

布局与 [deployment.md](deployment.md) 完全一致，仅两处差异：

1. 分发物不含 `RAG/`；
2. `.env` 多两行：

   ```bash
   LAWVER_LAW_SERVICE_URL = "https://law-api.<我方域名>"
   LAWVER_LAW_SERVICE_KEY = "lvk_..."
   ```

### 7.3 网络要求（硬前提）

客户服务器必须能出网经 443 访问 `law-api` 子域。**这是本方案的适用边界**：纯内网、物理隔离的客户环境本方案不适用，此类需求走商务例外流程（合同与保密条款约束 + 加密交付等非默认路径，或该环境裁剪法条功能），技术侧不提供默认的离线数据交付通道。

## 8. 实施计划

按阶段推进，每阶段有独立验收标准，阶段 0 立即可做且独立产生价值：

| 阶段 | 内容 | 验收标准 | 粗估 |
| --- | --- | --- | --- |
| 0 数据出库 | §6 的 git 移除 + 私有数据仓建立 + 测试机语料重放 | `git ls-files RAG/data/` 为空；工作区语料完整；测试机 `lawver-app` 启动与检索正常 | 0.5 天 |
| 1 服务孵化 | `law_service/` 本体：三端点 + keys + 限流 + 审计 + healthz；部署测试机 | curl 三端点带 key 返回与本地函数一致；无 key 401；超速 429；审计日志落盘且无 query 原文 | 2–3 天 |
| 2 主应用双模式 | §5 改造；测试机 `lawver-app` 切远程模式 | 远程模式下 `get_article` / `search_article` / `get_linked_content` 输出与本地模式对照一致；删除 `RAG/` 后启动与全部法条工具仍正常；边界测试通过 | 1–2 天 |
| 3 分发清洗 | 打包脚本排除 `RAG/`；B 端部署手册成文 | 用清洗后分发物在干净机器完成一次完整部署走查 | 0.5–1 天 |
| 4 加固运营 | 告警（服务不可用 / p95 / 异常模式）、canary 注入、配额调优、用量周报 | 告警演练通过；canary 在测试 key 下可被检出 | 1–2 天 |

合计约 **5–9 人日**。阶段 1–2 完成即具备首个 B 端交付条件，阶段 4 可与试运行并行。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 检索增加一次公网 RTT | 工具调用变慢 | 实测毫秒级检索 + 一次 RTT 对 agent 节奏无感；监控 p95，超阈值再议连接复用/就近部署 |
| 我方法库服务不可用 | 全部客户法条功能不可用 | 服务极简（无外部依赖）+ 存活探针 + 告警；恢复后无需客户侧任何动作 |
| 客户内网/离线环境 | 方案不适用 | §7.3 商务例外流程；不提供默认离线通道 |
| 查询内容离开客户内网 | 客户侧隐私顾虑 | 审计不落 query 原文；合同/隐私条款中明示检索外呼行为；远期可选 query 最小化（发送前剥离上下文细节） |
| key 泄露 | 第三方冒用配额、可探测接口 | 单 key 吊销即止损；异常模式检测；可选出口 IP 允许列表 / mTLS |
| 语料经 git 历史外流 | 历史 clone 持有语料 | 仓库保持私有（现状）；开源前 `git filter-repo` 清洗（§6 第 3 条） |
| 检索质量回归 | 远程模式行为漂移 | 阶段 2 的本地/远程对照验收；`/v1/meta` 固定数据版本使对照可复现 |

## 10. 范围外事项

- **案例匹配（得理）、企业信息（企查查）、SearXNG**：本就是客户部署各自配置凭据的外部依赖，本方案不触及；若 B 端客户不愿自备凭据、需要我方统一代理转发，另立方案（可复用本方案的 key/限流/审计模式）。
- **向量检索**：法库当前无 embedding、无向量库，本方案不引入；未来若上向量召回，仍收敛在 lawver-law 一处，客户侧形态不变。
- **计费集成**：本方案仅对法库调用量**计量**（审计日志已含所需字段）；把调用量接入现有 credit 体系（`backend/billing/`）作为后续独立迭代。
