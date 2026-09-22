# 大陆法系库接口说明（INTERFACE）

对齐《Lawver 管辖库工作协调规范》v1.0 §2 / §3。本包只提供管辖库 Python API，
**不注册 LLM Tool**；面向模型的工具名与路由由总装决定。

- 语料语言：印尼语 / 泰语 / 越南语（无中文正文，中文仅用于法名别名召回）
- 覆盖法域：印度尼西亚（ID）、泰国（TH）、越南（VN）
- 库文件：`RAG/civil_law/cache/civil_law.db`（独立库，**不并入** `RAG/cache/law.db`）

---

## 1. 暴露的六个函数

```python
from RAG.civil_law import (
    ensure_civil_law_database_ready,   # (*, force_rebuild: bool = False) -> dict
    exact_search,                      # (title: str, article_number: str) -> str
    fuzzy_search,                      # (query: str, limit: int = 5) -> str
    semantic_search,                   # (query: str, limit: int = 5) -> str
    link_search,                       # (message: str, limit: int = 5) -> str
    reset_engine,                      # () -> None
)
```

三个检索函数一律返回 `json.dumps(..., ensure_ascii=False)` 的 **JSON 字符串**，由调用方 `json.loads`。
`limit` 被钳制在 `1…20`，越界取默认值 5。

### 1.1 `ensure_civil_law_database_ready`

返回 dict（不是 JSON 字符串）：

```json
{
  "mode": "reuse | incremental | full",
  "content_sha256": "<语料指纹，schema 版本 + 每个文件的路径/大小/内容哈希>",
  "db_path": "…/RAG/civil_law/cache/civil_law.db",
  "schema_version": 2,
  "file_count": 3405,
  "law_count": 3404,
  "article_count": 86721
}
```

三种模式（对齐规范 §3.5 的状态约定）：

| mode | 触发条件 | 实测耗时 |
|---|---|---|
| `reuse` | 语料指纹未变，直接用现成的库 | 0.08 秒 |
| `incremental` | 只有部分文件变了，**就地**只重建变化的文件 | 0.2 秒 |
| `full` | 库缺失 / `schema_version` 升级 / `force_rebuild=True` | 约 6 秒 |

`incremental` 会额外返回 `changed_files` / `removed_files` / `deleted_articles` /
`indexed_articles` / `removed_laws`，便于总装判断这次维护实际重算了多少。

**`incremental` 是给服务维护用的**：改一部法律不用等整库重建，重启几乎无感。
它的正确性有强保证——冒烟与专项验证都核对过「多次增量后的库」与「强制全量重建后的库」
**内容哈希完全一致**。

`article_count` 是**入库条文总数**（含被过滤的 3,795 条），可检索的是 82,926 条。

引擎初始化会自动调用它。构建期间会持有一把跨进程文件锁（`cache/build.lock`），
多 worker 部署时不会出现两个进程同时改库。

## 2. Envelope（规范 §3.1）

### A. `exact_search`

```json
{"success": true, "message": "找到匹配的法条", "data": {…命中对象…}, "search_time": 0.001}
```

失败时 `success=false`、`data=null`、`message` 说明原因（法名找不到 / 条号无法识别 / 该条不存在）。

### B. `fuzzy_search` / `semantic_search`

```json
{"success": true, "message": "检索到 439 条相关法条", "data": [ …命中对象… ],
 "total_count": 439, "returned_count": 5, "search_time": 0.412}
```

`semantic_search` 是 `fuzzy_search` 的等价别名（规范要求二者行为一致，冒烟用例会验证结果完全相同）。

### C. `link_search`

```json
{"success": true, "message": "找到相关法规信源", "text": "1. 《…》第 1 条: https://…",
 "references": [{"title": "…", "article_number": "…", "url": "…", "content": "…"}],
 "data": [ …命中对象… ], "search_time": 0.003}
```

`references` 对齐主库 `law_link_search` 的键名（`title / article_number / url / content`）；
额外返回 `data`（规范强烈建议），两者一一对应。

## 3. 命中对象字段（规范 §3.2 / §3.3）

四核心字段全部必填，且**键一定存在**（`url` 可为空串，不省略键）：

| 字段 | 说明 |
|---|---|
| `law_name` | 法律名称，与 `exact_search` 的 `title` 对齐 |
| `article_number` | 条文号，保留原文写法（`Pasal N` / `มาตรา N` / `Điều N`） |
| `content` | 条文正文，超过 4000 字符截断 |
| `url` | 可核验来源链接；无链接时为空串 |

统一建议字段：

| 字段 | 取值 |
|---|---|
| `source_id` | 采集追踪号 |
| `status` | `in_force` / `repealed` / `amended` / `unknown` |
| `effective_date` | `YYYY-MM-DD` 或空串 |
| `language` | `id` / `th` / `vi` |
| `country` | `ID` / `TH` / `VN` |
| `country_label` | `印度尼西亚` / `泰国` / `越南` |
| `jurisdiction` | 与 `country_label` 同值（按协调方 2026-09-17 定的口径） |
| `legal_system` | 固定 `civil` |

`status` 与 `effective_date` 在当前语料中多为 `unknown` / 空串——三国官方源普遍不提供
逐条效力与生效日期，**未核验的值不推测**（规范 §2.3 禁止编造）。

## 4. 法名与条号的解析规则

### 4.1 法名（`title` 参数）

按以下顺序解析，命中即返回：

1. 法名压缩后完全相等（去空格、标点、大小写）
2. 别名表精确命中（含从 `tentang`、`số`、国名前缀派生的形式）
3. **提问文本里含有某别名**——支持「印尼民法典第 5 条」这类中文写法
4. 法名里含有提问文本——支持只写部分法名

别名表包含 16 部核心法典的**中文通称**（印尼民法典、泰国民商法典、越南劳动法典、KUHPerdata、
CCC、BLDS 等）。中文通称只是命名对照，**不是官方译本，不得替代原文**（规范 §6.1）。

### 4.2 条号（`article_number` 参数）

`normalize_article_key` 把下列写法统一归一到同一把键：

| 输入 | 归一化结果 |
|---|---|
| `Pasal 131a` | `131a` |
| `มาตรา ๑๒`（泰文数字） | `12` |
| `Điều 217a` | `217a` |
| `第12条` | `12` |

因此调用方可以**用中文条号查三国法条**，不必自己转换。

## 5. 已知能力边界

1. **不返回中文正文**。语料是三国官方语言原文；中文提问靠法名别名召回，正文仍是原文。
2. **泰国 2,583 条 `url` 为空**（民商法典、民诉法典、刑诉法典、税法典第 54 号修正法），
   命中这些条文时 `url` 是空串。OCP 会据此写「该条缺少可核验链接」，不会编造链接。
3. **质检不合格的 3,795 条已排除在检索之外**（印尼 3,716 条 OCR 页眉/签名块 + 越南 79 条假条号），
   索引层用 `usable = 1` 过滤，调用方无需再处理。
4. `fuzzy_search` 是关键词匹配（`instr` 包含判断 + 打分排序），**不是向量语义检索**。
   真正的语义检索需要 embedding 服务，当前环境未配置。

## 6. 总装接线清单（**需总装执行；管辖库侧不得自行修改这些文件**）

三国库本身已就绪，但**整个应用启动时不会触发它的索引准备**。下面是需要总装落的两处改动，
以及为什么必须由总装来做。

### 6.1 现状：启动期不会建三国库

应用启动链是：

```
app_factory.py  →  services/law_cache.py::prepare_on_startup()  →  mcps.ensure_law_database_ready()
                                                                    └─ 只调了中国法主库
```

`ensure_civil_law_database_ready()` 目前只在**引擎首次被使用**时自动调用，所以：

- 应用启动完 → 三国库**还没建**
- 第一个检索三国法条的请求到达 → 现场建库（首次约 7 秒），这个请求会明显变慢

要变成"启动即就绪"，就得在 `prepare_on_startup` 里加一行。而这一步绕不开 `mcps.py`。

### 6.2 为什么管辖库侧改不了

架构护栏 `tests/test_architecture_boundaries.py` 的 **I4 明文规定：`services/**`、`routes/**`
不得 import `RAG`** —— 能力子系统只能经 `mcps.py` 转发。也就是说，在 `services/law_cache.py`
里直接 `from RAG.civil_law import ...` 会让架构测试挂掉，**唯一合规的写法必须在 `mcps.py`
里加一行转发**。

而 `mcps.py` 正是《Lawver 管辖库工作协调规范》§2.3 的红线文件
（"禁止修改 `tools/__init__.py`、`mcps.py`、`function_calling.py`、`mcp/pkulaw_client.py`"）。
管辖库侧不擅自改总装入口，因此这部分留给总装。

### 6.3 改动一：`mcps.py` 加一行转发

在现有的主库转发旁边加（位置见下）：

```python
from memory_system import MemoryRevisionConflict, prune_conversation_memory
from mcp.pkulaw_client import ensure_law_database_ready

# ↓↓↓ 新增这一行 ↓↓↓
# 大陆法系（印尼/泰国/越南）法域库的启动期准备入口，与主库并列。
# 独立 SQLite（RAG/civil_law/cache/civil_law.db），不并入 RAG/cache/law.db；
# 只转发"准备索引"这一个只读入口，不注册 LLM Tool、不改工具 schema。
from RAG.civil_law import ensure_civil_law_database_ready  # noqa: F401
```

> 注意：这里**只加 import 转发**。不新增工具、不改任何工具 schema、不动 `tools = default_tools`
> 那一组注册——工具面的改动是 §6.7，与本条无关。

### 6.4 改动二：`services/law_cache.py` 调用

把整个 `prepare_on_startup` 换成下面这版（改动集中在后半段）：

```python
"""
模块描述：后端启动期本地法库缓存准备服务。

两个法域库互不影响、各建各的独立 SQLite：

- 中国法主库 `RAG/cache/law.db`
- 大陆法系三国库 `RAG/civil_law/cache/civil_law.db`（印尼/泰国/越南）

都在进程开始服务之前准备好，请求到达时走的是现成的索引。
"""

import asyncio

from fastapi import FastAPI

from mcps import ensure_civil_law_database_ready, ensure_law_database_ready


async def _prepare_civil_law() -> dict:
    """准备大陆法系三国库。失败只降级该法域，不让整个服务起不来。"""
    try:
        return await asyncio.to_thread(ensure_civil_law_database_ready)
    except Exception as exc:  # noqa: BLE001 - 单一法域库故障不应阻断主库与服务启动
        return {"mode": "failed", "error": f"{type(exc).__name__}: {exc}"}


async def prepare_on_startup(app: FastAPI) -> None:
    status = await asyncio.to_thread(ensure_law_database_ready)
    app.state.law_cache_status = status
    print(f"[法库] 启动缓存准备完成: mode={status.get('mode', 'unknown')}, "
          f"files={status.get('file_count', 0)}")

    civil_status = await _prepare_civil_law()
    app.state.civil_law_cache_status = civil_status
    if civil_status.get("mode") == "failed":
        print(f"[法系库] 大陆法系缓存准备失败: {civil_status.get('error')}")
    else:
        print(f"[法系库] 大陆法系缓存准备完成: mode={civil_status.get('mode')}, "
              f"laws={civil_status.get('law_count', 0)}, "
              f"articles={civil_status.get('article_count', 0)}")
```

### 6.5 三条设计说明（供 review 时判断）

1. **三国库构建失败不阻断启动。** 主库是主链路，三国库缺失只影响对应法域检索。
   所以 `_prepare_civil_law()` 吞掉异常、把 `mode="failed"` 和错误原因记进
   `app.state.civil_law_cache_status`，服务照常起。若你们认为必须硬失败，去掉 try/except 即可。
2. **两个库各自独立**。三国库写 `RAG/civil_law/cache/civil_law.db`，
   不并入 `RAG/cache/law.db`（协调规范 §2.3 明令禁止混库）。
3. **启动耗时**：`reuse` 0.08 秒 / `incremental` 0.2 秒 / `full` 约 7 秒。
   只有首次部署或语料大改才会走 `full`；部署流程里可以先跑
   `python -m RAG.civil_law.scripts.warm_cache` 预热，让启动固定走 `reuse`。

### 6.6 接线后怎么验收

```bash
.venv/Scripts/python -m pytest tests/test_architecture_boundaries.py -q   # I4 必须仍通过

# 启动应用，日志应出现：
#   [法库] 启动缓存准备完成: mode=..., files=4943
#   [法系库] 大陆法系缓存准备完成: mode=full, laws=3404, articles=86721

# 再启动一次，应变成 mode=reuse
# 删掉 RAG/civil_law/cache/ 再启动，应重新走 mode=full
```

### 6.7 同一批还有一块（LLM 工具面，也属总装）

让 OCP 与对话流程能**调**到三国库，还需要：

1. `tools/__init__.py` 里 `get_article` / `search_article` / `get_linked_content` 三个工具
   的 schema **增加 `jurisdiction` 参数**（这是协调规范里说好的："仅修改
   search_article/get_article/get_linked_content schema"）；
2. 新增 `mcp/legal_search_router.py`，按 `jurisdiction` 路由到中国法主库或本包
   （"router 是唯一需要知道它们在哪里的地方"）。

本包不改 `tools/`、也不新增 LLM Tool——只提供 §1 的六个 Python 函数供 router 调用。

### 6.8 不想动红线的备选路

如果总装短期排不上，**部署流程里先跑一次预热**也能达到同样效果：

```bash
.venv/Scripts/python -m RAG.civil_law.scripts.warm_cache
```

它做的事和 §6.4 完全一样（调 `ensure_civil_law_database_ready()`），只是发生在进程启动之前。
代价是有人跳过这一步部署时，第一个三国法条请求仍会触发一次 7 秒建库。
