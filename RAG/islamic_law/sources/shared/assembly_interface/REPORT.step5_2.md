# 5.2 总装接口冒烟报告

- verified_at: `2026-09-16`
- all_pass: **PASS** (5/5)
- 接口文档: `INTERFACE.md`

| # | 场景 | 结果 | 细节 |
| --- | --- | --- | --- |
| 01 | semantic_search 中文禁止 riba → MY+ID | PASS | `countries=['ID', 'MY'] returned=15` |
| 02 | exact_search MY riba formal | PASS | `hit='MY-RIBA-IFSA-2013-001' article_key=MY-RIBA-FORMAL` |
| 03 | link_search 禁止 riba → MY+ID + references | PASS | `countries=['ID', 'MY'] refs=15` |
| 04 | rules_by_principle RIBA country=ID | PASS | `total=11 has=['ID-FIN-MUI-BUNGA-2004-001', 'ID-FIN-UU21-2008-001']` |
| 05 | semantic_search 中文 2026-10-18 清真强制 | PASS | `hit=['ID-HALAL-BPJPH-2026-001', 'ID-HALAL-JPH-CORE-001', 'ID-HALAL-PP42-2024-001']` |
