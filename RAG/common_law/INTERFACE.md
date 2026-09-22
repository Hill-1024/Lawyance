# 普通法系库接口说明（INTERFACE）

覆盖法域：缅甸（`MM`）、新加坡（`SG`）。`legal_system` 固定为 `common`。

库文件：

- `RAG/common_law/cache/myanmar_law.db`
- `RAG/common_law/cache/singapore_law.db`

不并入 `RAG/cache/law.db`，也不和大陆法系、伊斯兰法系共用库。

## 1. 对外函数

```python
from RAG.common_law import (
    ensure_common_law_database_ready,  # (*, force_rebuild: bool = False) -> dict
    exact_search,                      # (title: str, article_number: str) -> str
    fuzzy_search,                      # (query: str, limit: int = 5) -> str
    semantic_search,                   # 与 fuzzy_search 等价
    link_search,                       # (message: str, limit: int = 5) -> str
    reset_engine,
)
```

三个检索函数返回 JSON 字符串。`limit` 钳制在 `1…20`。

路由规则：

- 文本里出现「新加坡 / Singapore / eGazette」时只查新加坡。
- 出现「缅甸 / Myanmar / ဥပဒေ」时只查缅甸。
- 都没有时，`exact_search` 先缅甸、未命中再新加坡；`fuzzy_search` / `link_search` 合并两边结果后截断到 `limit`。

需要只建某一国的库时，直接用国家引擎：

- `RAG.common_law.myanmar.ensure_myanmar_database_ready`
- `RAG.common_law.singapore.ensure_singapore_law_database_ready`

## 2. 命中字段

两边都保证核心四字段：`law_name`、`article_number`、`content`、`url`。

| 字段 | 取值 |
|---|---|
| `country` | `MM` / `SG` |
| `legal_system` | `common` |
| `language` | 缅甸语料为 `my` / `en` / `my+en`；新加坡种子为 `en` |

新加坡正文以英文为准，中文只用于召回，不能当成官方译本。缅甸正文是信息部来源的机器抽取文本，未人工核验的条目带 `review_required`。
