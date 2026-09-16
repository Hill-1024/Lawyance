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
.venv/bin/python -m RAG.islamic_law.scripts.verify_formal_semantic
```

生成：

- `cache/islamic_rules.db`
- `cache/manifest.shared.json`
- `cache/manifest.country.MY.json`
- `cache/manifest.country.ID.json`
- `sources/shared/verify_formal/`：正式条目语义检索批量验证报告（每条 ≥1 相关 query 命中）

马来西亚 riba / 金融第二批与印尼 halal 核心已入库：

- 共享层 `data/shared/riba_scripture_principle.json`：Quran 2:275–279（Tanzil 阿语 + Saheeh International 英译 + 马坚中译）及已核圣训编号（`sources/shared/scripture_riba/`）；`legal_effect=religious-guidance`
- 共享层扩展 `data/shared/principles_step3_1.json`：gharar / maysir / sukuk / takaful / halal-haram（均为 `religious-guidance`）
- 共享层治理原则 `data/shared/principle_governance_step3_2.json`：`SH-PRINCIPLE-GOVERNANCE-001`（4:58；`religious-guidance`）
- **正式综合条目** `data/MY/my_riba_ifsa_2013_formal.json`：`MY-RIBA-IFSA-2013-001`（挂 `SH-PRINCIPLE-RIBA-001`）
- **3.2 正式条目** `data/MY/my_step3_2_formal.json`（7 条，累计 MY formal=8）：
  - `MY-SUKUK-BNM-SAC-001` → `SH-PRINCIPLE-SUKUK-001`
  - `MY-TAKAFUL-BNM-SAC-001` → `SH-PRINCIPLE-TAKAFUL-001`
  - `MY-IFSA-2013-GOV-S28-29-001` / `MY-IFSA-2013-GOV-S30-38-001` / `MY-BNM-SGP-2019-FORMAL-001` → `SH-PRINCIPLE-GOVERNANCE-001`
  - `MY-HALAL-ACT730-FORMAL-001` / `MY-HALAL-MS1500-FORMAL-001` → `SH-PRINCIPLE-HALAL-HARAM-001`
- 支撑包：`bnm_sac_sukuk_rules.json`、`bnm_sac_takaful_rules.json`、`ifsa2013_shariah_governance_rules.json`、`bnm_sgp_2019_rules.json`、`jakim_halal_rules.json`
- 既有：`ifsa2013_riba_rules.json`、`cba2009_sac_rules.json`、`bnm_sac_riba_rules.json`
- **4.1 印尼 halal 核心** `data/ID/id_halal_formal.json`（4 条 formal，均挂 `SH-PRINCIPLE-HALAL-HARAM-001`）：
  - `ID-HALAL-UU33-2014-001`（UU 33/2014）
  - `ID-HALAL-PP42-2024-001`（PP 42/2024）
  - `ID-HALAL-BPJPH-2026-001`（BPJPH 2026-10-18 公告）
  - `ID-HALAL-JPH-CORE-001`（综合正式条目）
- 支撑包：`data/ID/id_halal_uu33_pp42_rules.json`；来源 `sources/ID/halal_bpjph/`（含官方 PDF）
- **特别标注**：`2026-10-18 全面强制、官方不再延期`（过渡期至 2026-10-17，次日起强制）；印尼语原文为准；MUI/DSN-MUI 具体 fatwa 编号待核验
- **4.2 印尼伊斯兰金融** `data/ID/id_islamic_finance_formal.json`（4 条 formal）：
  - `ID-FIN-MUI-BUNGA-2004-001`（Fatwa MUI 1/2004 禁息）→ `SH-PRINCIPLE-RIBA-001`
  - `ID-FIN-UU21-2008-001`（UU 21/2008 伊斯兰银行母法）→ `SH-PRINCIPLE-RIBA-001`
  - `ID-FIN-POJK16-2022-001`（POJK 16/POJK.03/2022 BUS）→ `SH-PRINCIPLE-RIBA-001`
  - `ID-FIN-POJK18-2015-001`（POJK 18/POJK.04/2015 Sukuk）→ `SH-PRINCIPLE-SUKUK-001`
- 支撑包：`data/ID/id_islamic_finance_rules.json`；来源 `sources/ID/islamic_finance/`（含官方 PDF）
- **链条**：MUI 法特瓦（宗教裁决，无 LN/TLN，但被监管援引）→ UU 21/2008 → POJK 16/2022（银行）+ POJK 18/2015（sukuk，Pasal 1 明文回接 DSN-MUI）；注意 UU 21/2008 经 UU 4/2023 修订、POJK 18/2015 ≠ POJK 18/2023

IFSA 正文无 “riba” 一词，禁止利息经 Shariah 合规义务间接实现；CBA ss.56–58 规定 SAC 的提交、拘束力与优先。SAC 无单独“riba 裁决”，以汇编决议序号为可追溯编号。共享层经训不得单独作为国家合规结论。正式引用以英文立法文本与阿语经训原文为准。印尼方向以印尼语官方文本为准。

## 与主库的关系（增量对齐，不重造）

本库**有意复用**主库 `RAG/law_data_search.py` 的外壳：SQLite + `search_blob` 关键词打分 + `exact` / 模糊 / `link` 三接口 + JSON envelope（`law_name` / `article_number` / `content` / `url`）。

**不合并进** `RAG/cache/law.db`，因为伊斯兰库需要双层（共享原则 ↔ 国家转化）与 `legal_effect` / `country` / `fatwa_*` 等字段；硬塞进主库 `laws`/`articles` 会变形。

已做的简单对齐：

- `fuzzy_search` 作为 `semantic_search` 别名（主库命名）
- `link_search` 同时返回 `data`（完整）与 `references`（精简，对齐主库）
- `cache/manifest.build.json`：对 `schema.sql` + `data/**/*.json` 做 content hash，变更才重建（对齐主库 rebuild 思路）
- 连接开启 `PRAGMA journal_mode=WAL`

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

`data/BN|ID|SG/*.json` 与 `data/MY/my_ifla_*.json` 仍为早期条款级 demo。`data/MY/my_riba_ifsa_2013_formal.json`、`data/MY/my_step3_2_formal.json`、`data/shared/riba_scripture_principle.json`、`data/shared/principles_step3_1.json`、`data/shared/principle_governance_step3_2.json` 与各 `data/MY/*_rules.json`、`data/ID/id_halal_*.json`、`data/ID/id_islamic_finance_*.json` 为双层入库语料。

## P1 / P2 / P3 边界

| 阶段 | 本库状态 |
| --- | --- |
| P1 | 双层 schema；MY formal 8 条 + ID halal formal 4 条 + ID 伊斯兰金融 formal 4 条；共享层含 riba/gharar/maysir/sukuk/takaful/halal-haram/governance；下一步可扩 BN 或 ID 产品级 DSN 法特瓦 |
| P2 | 补 BN/SG/PH/TH；takaful/waqf/faraid 专题 |
| P3 | 与各分国法库双向打通、横向对比检索；经训误引红队（多在总装/Agent） |

辞朝演说圣训分条号、阿语拉丁转写仍待核验（字段已标「待核验」）。BNM SAC 2010 汇编本地为内容核对副本，正式法律意见引用前须对照 bnm.gov.my / tanzil.net / sunnah.com 官方 URL。
