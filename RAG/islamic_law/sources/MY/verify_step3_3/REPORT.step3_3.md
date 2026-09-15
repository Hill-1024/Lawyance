# 3.3 批量验证报告

- 日期：2026-09-15
- Top-N：10
- 正式条目：8
- 结果：ALL PASS（8/8）
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
