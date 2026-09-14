# 伊斯兰法系管辖库（Islamic Law DB）

本目录是 **东盟伊斯兰法系横切专题库**（不是第 12 个国家库），遵循管辖库负责人规范：

- 只负责本法系语料清洗、索引与检索
- **不**修改 `tools/__init__.py` / `mcps.py` / `function_calling.py`
- **不**擅自新增 LLM 工具

## 双层物理结构（schema v3）

| 层 | 表 | 说明 |
| --- | --- | --- |
| 宗教法源共享层 | `sharia_principles` | 跨国一份；经训/学说/国际标准；默认 `legal_effect=religious-guidance` |
| 国家转化实例层 | `islamic_rules` | 挂 MY/ID/BN…；立法、监管吸收法特瓦、Qanun 等 |
| 术语 | `terminology` | 阿/英/中/马/印尼 四向对照 + aliases |
| 权威来源 | `authority_sources` | 表6 白名单骨架 |

双向关联键：`sharia_principle_id`（实例 → 原则）；原则侧 `country_rule_ids`（JSON）。

```bash
.venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
```

生成：

- `cache/islamic_rules.db`
- `cache/manifest.shared.json`
- `cache/manifest.country.MY.json`

马来西亚 Step 1.1 已入库：`data/MY/ifsa2013_riba_rules.json`（IFSA 2013 ss.28, 29, 152, 153, 167, 168 + SAC Resolution 81 摘录），权威 PDF 与采集记录在 `sources/MY/ifsa2013/`。IFSA 正文无 “riba” 一词，禁止利息经 Shariah 合规义务间接实现；正式引用以英文原文为准。

## 效力三分类

- `binding`：国内法或法定拘束力裁决
- `regulated-fatwa`：经监管吸收、约束持牌机构
- `religious-guidance`：宗教/学理/国际标准（旧别名 `advisory` 入库时归一）

缺少国内转化时，共享层原则**不得**单独作为合规结论依据。

## 东盟分档

见 `countries.py` 中 `ASEAN_COUNTRY_TIERS`：

- 核心档：`MY` `ID` `BN`
- 有限档：`SG` `PH` `TH`
- 备注档：`VN` `LA` `KH` `MM` `TL`

## 统一检索接口

```python
from RAG.islamic_law import exact_search, semantic_search, link_search, ensure_islamic_database_ready

ensure_islamic_database_ready()
print(semantic_search("Malaysia riba IFSA", 3))
```

返回至少含：`law_name` / `article_number` / `content` / `url`，以及 `country`、`legal_effect`、三重适用、`sharia_principle_id`；命中转化层时附带 `principle` 摘要。

内部引擎默认读 `cache/islamic_rules.db`（关键词打分；可后续换向量后端）。

## 条款级 JSON 脚手架（旧）

`data/BN|ID|SG/*.json` 与 `data/MY/my_ifla_*.json` 仍为早期条款级 demo。`data/MY/ifsa2013_riba_rules.json` 为双层入库语料。

## P1 / P2 / P3 边界

| 阶段 | 本库状态 |
| --- | --- |
| P1 | 双层 schema、术语初版、权威白名单、MY IFSA 2013 riba 链条（AGC PDF 核验）、三路检索联调（当前） |
| P2 | 补 BN/SG/PH/TH；takaful/waqf/faraid 专题 |
| P3 | 与各分国法库双向打通、横向对比检索；经训误引红队（多在总装/Agent） |

共享层经训阿语原文仍待 A 级复核。SAC Resolution 81 摘自采集记录，本地未保存 BNM PDF，正式法律意见引用前须对照官方 URL。
