# 3.3 批量验证报告

- 日期：2026-09-16
- Top-N：10
- 正式条目：16
- 结果：ALL PASS（16/16）
- 标准：每条正式条目至少被 1 个相关 query 在 semantic_search Top-N 命中

| 正式条目 | 原则 | 结果 | 最佳命中 |
| --- | --- | --- | --- |
| `MY-RIBA-IFSA-2013-001` | `SH-PRINCIPLE-RIBA-001` | PASS | #1 ← `马来西亚 riba 利息` |
| `MY-SUKUK-BNM-SAC-001` | `SH-PRINCIPLE-SUKUK-001` | PASS | #1 ← `马来西亚 sukuk 伊斯兰债券 SAC` |
| `MY-TAKAFUL-BNM-SAC-001` | `SH-PRINCIPLE-TAKAFUL-001` | PASS | #1 ← `马来西亚 takaful 伊斯兰保险` |
| `MY-IFSA-2013-GOV-S28-29-001` | `SH-PRINCIPLE-GOVERNANCE-001` | PASS | #2 ← `IFSA 沙里亚合规义务 section 28` |
| `MY-IFSA-2013-GOV-S30-38-001` | `SH-PRINCIPLE-GOVERNANCE-001` | PASS | #1 ← `沙里亚合规审计 section 37 38` |
| `MY-BNM-SGP-2019-FORMAL-001` | `SH-PRINCIPLE-GOVERNANCE-001` | PASS | #1 ← `Shariah Governance Policy Document` |
| `MY-HALAL-ACT730-FORMAL-001` | `SH-PRINCIPLE-HALAL-HARAM-001` | PASS | #1 ← `JAKIM halal 认证主管机关` |
| `MY-HALAL-MS1500-FORMAL-001` | `SH-PRINCIPLE-HALAL-HARAM-001` | PASS | #1 ← `MS 1500 halal 食品标准` |
| `ID-HALAL-UU33-2014-001` | `SH-PRINCIPLE-HALAL-HARAM-001` | PASS | #1 ← `Indonesia Jaminan Produk Halal Pasal 4` |
| `ID-HALAL-PP42-2024-001` | `SH-PRINCIPLE-HALAL-HARAM-001` | PASS | #1 ← `Peraturan Pemerintah 42 2024 Pasal 160 UMK` |
| `ID-HALAL-BPJPH-2026-001` | `SH-PRINCIPLE-HALAL-HARAM-001` | PASS | #2 ← `2026-10-18 全面强制 官方不再延期` |
| `ID-HALAL-JPH-CORE-001` | `SH-PRINCIPLE-HALAL-HARAM-001` | PASS | #1 ← `印尼 halal 核心制度 UU PP BPJPH` |
| `ID-FIN-MUI-BUNGA-2004-001` | `SH-PRINCIPLE-RIBA-001` | PASS | #1 ← `印尼 Fatwa MUI 1/2004 利息 riba haram` |
| `ID-FIN-UU21-2008-001` | `SH-PRINCIPLE-RIBA-001` | PASS | #1 ← `Perbankan Syariah Pasal 68 spin-off UUS` |
| `ID-FIN-POJK16-2022-001` | `SH-PRINCIPLE-RIBA-001` | PASS | #1 ← `印尼 POJK 16/2022 伊斯兰商业银行` |
| `ID-FIN-POJK18-2015-001` | `SH-PRINCIPLE-SUKUK-001` | PASS | #1 ← `印尼 POJK 18/2015 Sukuk 发行` |
