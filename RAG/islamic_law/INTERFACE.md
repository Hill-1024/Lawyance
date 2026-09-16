# 伊斯兰法系管辖库 — 总装接口说明（5.2）

> **范围**：仅马来西亚（`MY`）与印度尼西亚（`ID`）国家转化层 + 共享原则层。  
> **边界**：本目录**只准备检索接口**，**不**修改 `tools/__init__.py` / `mcps.py` / `function_calling.py`；总装由他人接线。

## 1. 如何接入

```python
from RAG.islamic_law import (
    ensure_islamic_database_ready,
    exact_search,
    semantic_search,   # 同 fuzzy_search
    fuzzy_search,
    link_search,
    rules_by_principle,
)

meta = ensure_islamic_database_ready()  # 首次或语料变更时自动建库
```

- 入口包：`RAG.islamic_law`
- 数据库：`RAG/islamic_law/cache/islamic_rules.db`（自动种子，勿手改）
- **所有检索函数返回 JSON 字符串**（`json.loads(...)` 后使用）
- 建议仓库根目录运行；依赖项目 `.venv`

独立冒烟（总装可直接跑）：

```bash
.venv/bin/python -m RAG.islamic_law.scripts.assembly_smoke_cases
```

## 2. 对外查询函数

| 函数 | 用途 | 对齐主库 |
| --- | --- | --- |
| `ensure_islamic_database_ready()` | 确保库就绪（缺库/语料变更则重建） | 类似管辖库 ensure |
| `exact_search(title, article_number)` | 法名 + 条款精确定位 | `exact` |
| `semantic_search(query, limit=5)` | 关键词模糊检索 | 实现同 `fuzzy_search` |
| `fuzzy_search(query, limit=5)` | 与 `semantic_search` 完全等价 | 主库命名 |
| `link_search(message, limit=5)` | 从自然语言抽引用；先 exact 再 semantic | `link` |
| `rules_by_principle(principle_id, country=None, limit=100)` | 按 `SH-PRINCIPLE-*` 反查各国实例 | 本法系扩展 |

可选：`reset_engine()` — 测试换库后清空引擎单例。

### 2.1 `ensure_islamic_database_ready(*, force_rebuild=False) -> dict`

| 字段 | 含义 |
| --- | --- |
| `mode` | `"seed"` 刚重建 / `"reuse"` 复用已有库 |
| `schema_version` | 当前 schema 版本（v3） |
| `db_path` | SQLite 路径 |
| `content_sha256` | 语料指纹 |

### 2.2 `exact_search(title: str, article_number: str) -> str`

**入参**

| 参数 | 说明 |
| --- | --- |
| `title` | 法规/文件名（`law_name`） |
| `article_number` | 条款号，**或**正式条目的显式 `article_key`（如 `MY-RIBA-FORMAL`） |

**出参 JSON**

```json
{
  "success": true,
  "message": "ok",
  "data": { /* 单条 canonical，见 §3 */ },
  "search_time": 0.01
}
```

失败时 `success=false`，`data=null`。

### 2.3 `semantic_search` / `fuzzy_search(query: str, limit: int = 5) -> str`

**入参**：自然语言或关键词；`limit` 默认 5，上限 20。查询中含国家码/`马来西亚`/`印尼` 等会倾向过滤该国。

**出参 JSON**

```json
{
  "success": true,
  "message": "ok",
  "data": [ /* canonical 列表 */ ],
  "total_count": 10,
  "returned_count": 5,
  "search_time": 0.02
}
```

### 2.4 `link_search(message: str, limit: int = 5) -> str`

**入参**：用户原话。若含引号法名 + `Section`/`Pasal`/`Article` 等，优先 exact；不足再用 semantic。

**出参 JSON**

| 字段 | 含义 |
| --- | --- |
| `success` | 是否有可引用结果 |
| `data` | 完整 canonical 列表（本库消费者） |
| `references` | 精简列表：`title` / `article_number` / `url` / `content`（对齐主库 link） |
| `text` | 多行可读引用串 |
| `search_time` | 耗时秒 |

### 2.5 `rules_by_principle(principle_id, country=None, limit=100) -> str`

**入参**

| 参数 | 说明 |
| --- | --- |
| `principle_id` | 如 `SH-PRINCIPLE-RIBA-001` |
| `country` | 可选 `MY` / `ID` |
| `limit` | 默认 100，上限 200 |

**出参要点**：`principle` 摘要、`data` 实例列表、`by_country` 分组、`country_rule_ids`、`total_count`。

常用原则 ID：

| ID | 主题 |
| --- | --- |
| `SH-PRINCIPLE-RIBA-001` | 禁止 riba |
| `SH-PRINCIPLE-SUKUK-001` | sukuk |
| `SH-PRINCIPLE-TAKAFUL-001` | takaful（目前主要 MY） |
| `SH-PRINCIPLE-HALAL-HARAM-001` | halal/haram |
| `SH-PRINCIPLE-GOVERNANCE-001` | 沙里亚治理（目前主要 MY） |

## 3. Canonical 返回字段（`data` 条目）

与主库对齐的核心四字段 + 伊斯兰扩展：

| 字段 | 含义 |
| --- | --- |
| `law_name` | 法规/文件检索主名称 |
| `article_number` | 条款定位（正式条目常为 Formal… 描述） |
| `content` | 正文/摘录 |
| `url` | 可核验来源链接 |
| `rule_id` | 本库唯一 ID（如 `MY-RIBA-IFSA-2013-001`） |
| `source_id` | 采集追踪编号 |
| `country` / `country_label` | 国家码 / 显示名 |
| `legal_effect` | `binding` / `regulated-fatwa` / `religious-guidance` |
| `sharia_principle_id` | 挂接的共享原则 |
| `madhhab` | 教法学派（默认 Shafi'i） |
| `applicability_person` / `_subject` / `_territory` | 属人 / 属事 / 属地 |
| `fatwa_issuer` / `fatwa_id` | 法特瓦机构与编号 |
| `rule_subject` | 中文主题摘要 |
| `national_transformation` | 国家转化说明 |
| `output_annotation` | 输出注释（效力、待核验等） |
| `principle` | 可选：共享层摘要（含 `country_rule_ids`） |
| `status` / `effective_date` / `language` | 效力状态、生效日、语言 |

**效力约定**：共享原则多为 `religious-guidance`，**不得单独作为某国合规结论**；合规以国家层 `binding`（及被监管援引的法特瓦链）为准。

## 4. 正式条目速查（总装可优先引用）

马来西亚 8 条 + 印尼 8 条（`record_grade=formal`）。exact 时建议传库内 `article_key`：

| rule_id | article_key（exact 第二参） |
| --- | --- |
| `MY-RIBA-IFSA-2013-001` | `MY-RIBA-FORMAL` |
| `MY-SUKUK-BNM-SAC-001` | `MY-SUKUK-FORMAL` |
| `ID-FIN-MUI-BUNGA-2004-001` | `ID-FIN-MUI-BUNGA-FORMAL` |
| `ID-HALAL-UU33-2014-001` | `ID-HALAL-UU33-FORMAL` |
| … | 见 `data/MY|ID/*formal*.json` 的 `article_key` |

完整清单与自测报告：`sources/shared/verify_full_selftest/REPORT.step5_1.md`。

## 5. 总装测试用例（独立脚本）

脚本：`scripts/assembly_smoke_cases.py`（5 个用例，可独立运行，不依赖 tools/mcps）。

| # | 场景 | 调用 | 期望 |
| --- | --- | --- | --- |
| 1 | 中文跨语言：禁止 riba | `semantic_search` | 命中含 MY 与 ID |
| 2 | 精确：马来西亚 riba formal | `exact_search` | `rule_id=MY-RIBA-IFSA-2013-001` |
| 3 | 链接抽取：禁止 riba | `link_search` | `data` 含 MY+ID |
| 4 | 原则反查：riba → 印尼 | `rules_by_principle(..., country="ID")` | 含 Fatwa MUI / UU21 formal |
| 5 | 中文：印尼 2026-10-18 清真强制 | `semantic_search` | 命中 BPJPH/核心 formal |

运行成功退出码 0；失败非 0，并打印每条 PASS/FAIL。
