# 伊斯兰法系管辖库 — P1 建设文档（5.3 交接用）

> 对象：接手本库的同事 / 总装接线人  
> 范围：**马来西亚（MY）+ 印度尼西亚（ID）**；金融 + halal 首批正式条目  
> 边界：**不**改 `tools/__init__.py` / `mcps.py` / `function_calling.py`  
> 接口：见 [INTERFACE.md](./INTERFACE.md)；总览：[README.md](./README.md)

---

## 1. 一句话现状

双层 SQLite 库已就绪：共享原则（`sharia_principles`）↔ 国家转化（`islamic_rules`）。  
**正式条目 16 条**（MY 8 + ID 8，落在截图「15–20 条」目标内），主题覆盖 riba / sukuk / takaful / 沙里亚治理 / halal。  
自测（5.1）、总装冒烟（5.2）、跨国对比（4.4）均已通过。

```bash
# 建库 + 总装冒烟（仓库根目录）
.venv/bin/python -m RAG.islamic_law.scripts.insert_riba_sample
.venv/bin/python -m RAG.islamic_law.scripts.assembly_smoke_cases
```

库文件：`cache/islamic_rules.db`（gitignore，种子脚本生成）。

---

## 2. 已入库正式条目清单

字段约定：**编号** = `rule_id`；**主题** = 中文摘要；**国家** = MY/ID；**来源** = 主权威文本 / URL 入口。

### 2.1 马来西亚（MY）— 8 条

| 编号 | 主题 | 国家 | 来源 |
| --- | --- | --- | --- |
| `MY-RIBA-IFSA-2013-001` | 禁止 riba — IFSA/CBA/SAC 正式转化 | MY | IFSA 2013 (Act 759) AGC；CBA 2009；BNM SAC Resolutions；[AGC PDF](https://lom.agc.gov.my/) |
| `MY-SUKUK-BNM-SAC-001` | sukuk — BNM SAC 决议正式转化 | MY | BNM *Shariah Resolutions* 2nd ed.；[bnm.gov.my](https://www.bnm.gov.my/) |
| `MY-TAKAFUL-BNM-SAC-001` | takaful — BNM SAC 决议正式转化 | MY | 同上 BNM SAC 汇编 |
| `MY-IFSA-2013-GOV-S28-29-001` | 沙里亚合规义务 + 央行标准权（ss.28–29） | MY | IFSA 2013 |
| `MY-IFSA-2013-GOV-S30-38-001` | Shariah 委员会设置与运行（ss.30–38） | MY | IFSA 2013 |
| `MY-BNM-SGP-2019-FORMAL-001` | 沙里亚治理政策文件 SGP 2019 | MY | BNM Shariah Governance Policy Document |
| `MY-HALAL-ACT730-FORMAL-001` | halal 法定框架（Act 730 + P.U.(A) 430/431） | MY | Trade Descriptions Act；JAKIM 相关附属立法 |
| `MY-HALAL-MS1500-FORMAL-001` | halal 技术/程序基准（MS 1500 / MPPHM） | MY | MS 1500:2019；[halal.gov.my](https://www.halal.gov.my) |

原则挂接：riba→`SH-PRINCIPLE-RIBA-001`；sukuk→`…-SUKUK-001`；takaful→`…-TAKAFUL-001`；治理→`…-GOVERNANCE-001`；halal→`…-HALAL-HARAM-001`。

### 2.2 印度尼西亚（ID）— 8 条

| 编号 | 主题 | 国家 | 来源 |
| --- | --- | --- | --- |
| `ID-HALAL-UU33-2014-001` | 清真产品保障母法 UU 33/2014 | ID | [BPJPH/cmsbl UU PDF](https://cmsbl.halal.go.id/) |
| `ID-HALAL-PP42-2024-001` | 实施条例 PP 42/2024（过渡期至 2026-10-17） | ID | [BPJPH/cmsbl PP PDF](https://cmsbl.halal.go.id/) |
| `ID-HALAL-BPJPH-2026-001` | 2026-10-18 全面强制官方口径 | ID | [BPJPH 公告](https://bpjph.halal.go.id/) |
| `ID-HALAL-JPH-CORE-001` | halal 核心综合正式条目 | ID | UU + PP + BPJPH 链 |
| `ID-FIN-MUI-BUNGA-2004-001` | Fatwa MUI 1/2004 禁息（被监管援引） | ID | [fatwamui.com PDF](https://fatwamui.com/)；DSN-MUI 索引 |
| `ID-FIN-UU21-2008-001` | 伊斯兰银行母法 UU 21/2008 | ID | [OJK UU PDF](https://ojk.go.id/)（后经 UU 4/2023 修订） |
| `ID-FIN-POJK16-2022-001` | 伊斯兰商业银行细则 POJK 16/POJK.03/2022 | ID | [OJK POJK](https://www.ojk.go.id/) |
| `ID-FIN-POJK18-2015-001` | Sukuk 发行条件 POJK 18/POJK.04/2015 | ID | OJK；Pasal 1 回接 DSN-MUI（≠ POJK 18/2023） |

本地 PDF 副本：`sources/ID/halal_bpjph/`、`sources/ID/islamic_finance/`（含 MD5 / provenance）。

### 2.3 共享原则层（非「国家正式条目」，但已入库）

| 编号 | 主题 | 国家 | 来源 |
| --- | --- | --- | --- |
| `SH-PRINCIPLE-RIBA-001` | 禁止 riba（经训） | 共享 | Quran 2:275–279 + 已核圣训编号 |
| `SH-PRINCIPLE-GHARAR-001` | 禁止 gharar | 共享 | 圣训等 |
| `SH-PRINCIPLE-MAYSIR-001` | 禁止 maysir | 共享 | Quran 5:90–91 等 |
| `SH-PRINCIPLE-SUKUK-001` | sukuk 教法基础 | 共享 | 经训锚定 |
| `SH-PRINCIPLE-TAKAFUL-001` | takaful 教法基础 | 共享 | 经训锚定 |
| `SH-PRINCIPLE-HALAL-HARAM-001` | halal/haram | 共享 | Quran 2:168/173、16:114 等 |
| `SH-PRINCIPLE-GOVERNANCE-001` | 沙里亚治理 / amanah | 共享 | Quran 4:58 |

原则侧 `country_rule_ids` 已挂回 MY/ID 实例（步骤 4.3）。`legal_effect=religious-guidance`，**不得单独作为某国合规结论**。

另有支撑包条款（CHAIN / Pasal / Section 级）随种子入库，见 `data/MY/*_rules.json`、`data/ID/id_*_rules.json`。

另有 **成文法原文层 1008 条**（`record_grade=support`，不是第 17 条以后的 formal）：

| 文件 | 条数 | 来源 |
| --- | --- | --- |
| `data/ID/statute_articles.json` | 618 | 本地 PDF：UU 33/2014、PP 42/2024、UU 21/2008、POJK 16/2022、POJK 18/2015，含非「Cukup jelas」的 Penjelasan |
| `data/MY/statute_articles.json` | 390 | 本地 PDF：IFSA 2013（2021 修订转载本）291 条、CBA 2009 99 条 |

由 `scripts/extract_statute_articles.py` 从 `sources/` 已有 PDF 切出，未逐条人工核验，`status=unknown`。正式合规结论仍只看上面 16 条 formal。重新切分：

```bash
.venv/bin/python -m RAG.islamic_law.scripts.extract_statute_articles
```

---

## 3. 待核验清单

| # | 事项 | 影响条目 / 层 | 建议动作 |
| --- | --- | --- | --- |
| 1 | 辞朝演说（Khutbat al-Wada'）废除利息圣训在 sunnah.com 的精确分条号 | `SH-PRINCIPLE-RIBA-001`、MY riba formal | 对照 sunnah.com；**禁止编造编号** |
| 2 | 阿语经训拉丁转写（transliteration） | 各原则与多数字段标「待核验」 | 专题补录或保持空+标注 |
| 3 | BNM SAC 2010 汇编长引文与现行官方 PDF 逐段复核 | MY sukuk/takaful/riba SAC | 用 bnm.gov.my 官方 PDF |
| 4 | 印尼 MUI/DSN-MUI **产品级** fatwa 编号（murabahah 等；清真 Keputusan 号） | ID finance / halal | 按产品专题采集 |
| 5 | UU 21/2008 经 UU 4/2023 (P2SK) 及后续修订后的**现行综合文本**（尤其 Pasal 68） | `ID-FIN-UU21-2008-001` | peraturan.go.id / 官方综合版 |
| 6 | peraturan.go.id 交叉链（采集环境曾不可达） | ID UU/PP | 可访问时补链 |
| 7 | PP 42/2024 Pasal 160(3) 进口品部长令具体日期 | ID halal | 跟进 Menteri 决定 |
| 8 | Fatwa MUI 1/2004 Google Drive 挂载 PDF 与 fatwamui.com 副本一致性 | `ID-FIN-MUI-BUNGA-2004-001` | 可访问时再核 MD5 |

字段层统一约定：凡未核验写清「待核验」，**不编造**。

---

## 4. 采集中遇到的问题与解决

| 问题 | 解决 |
| --- | --- |
| 伊斯兰字段与主库 `laws/articles` 模型不合 | **独立双层库** `islamic_rules.db`，检索外壳对齐主库（exact / semantic≈fuzzy / link），不硬塞主库 |
| IFSA 正文无 “riba” 字样 | 经 s.28/29/153/167–168 + SAC 间接禁止；正式条目写清转化链 |
| 法特瓦无 LN/TLN（如 Fatwa MUI 1/2004） | 标注「宗教裁决 + 被 POJK/UU 援引」；`legal_effect` 区分 binding / regulated-fatwa |
| Formal 条目 `exact_search` 误命中 Section 数字 | `article_key` 显式键（如 `MY-RIBA-FORMAL`）+ exact 候选键修复（5.1） |
| 共享层 `country_rule_ids` 仅内存写入 | 4.3 写回 `data/shared/*.json` + `rules_by_principle` 反查 + 校验 |
| 印尼 halal「是否延期」口径混乱 | 固化节点：**2026-10-18 全面强制、官方不再延期**（PP 160–161 + BPJPH） |
| POJK 18/2015 vs 18/2023 易混 | 文档与条目注明：2015=一般 sukuk；2023=可持续专项 |
| UU 21/2008 已被 P2SK 修订 | 入库保留 OJK 2008 原件溯源，注释要求引用前对现行综合文本 |
| 总装是否改 tools/mcps | **明确不改**；只提供 `INTERFACE.md` + `assembly_smoke_cases` |
| 数据库国家范围 | P1 **只做 MY+ID**；BN 等东盟档位仅元数据预留 |

---

## 5. 目录与交接路径（接手必读）

| 路径 | 作用 |
| --- | --- |
| `schema.sql` / `models.py` / `search.py` | 双层 schema、dataclass、三路检索 + 原则反查 |
| `data/shared/` | 共享原则 JSON |
| `data/MY/`、`data/ID/` | 国家 formal + 支撑包 |
| `sources/**/provenance*.json` | 采集溯源与 pending |
| `scripts/insert_riba_sample.py` | 种子入口 |
| `scripts/assembly_smoke_cases.py` | 总装 5 用例 |
| `INTERFACE.md` | 总装接口说明 |
| `sources/shared/verify_*` | 自测 / 跨国 / 挂回报告 |

验证命令速查：

```bash
.venv/bin/python -m RAG.islamic_law.scripts.verify_full_selftest
.venv/bin/python -m RAG.islamic_law.scripts.verify_cross_country
.venv/bin/python -m RAG.islamic_law.scripts.verify_principle_links
.venv/bin/python -m RAG.islamic_law.scripts.assembly_smoke_cases
```

---

## 6. P1 验收对照（截图目标）

| 目标 | 状态 |
| --- | --- |
| 首批约 15–20 条 MY/ID 金融+halal 正式条目 | ✅ **16 条 formal** |
| 共享原则 + 国家转化双向关联 | ✅ 4.3 |
| 跨国对比（同一原则 ≥2 国） | ✅ 4.4 |
| 全量自测 / 总装接口准备 | ✅ 5.1 / 5.2 |
| 建设文档可交接 | ✅ 本文档（5.3） |
| 里程碑 Git 提交 | ✅ 5.4（指定 message） |

下一步（非本里程碑）：BN 扩展、ID 产品级 DSN 法特瓦、总装接线 tools（由他人完成）。
