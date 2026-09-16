# 4.4 跨国对比验证

- verified_at: `2026-09-16`
- all_pass: **PASS**
- checks: 7/7
- 要求：同一原则下转化实例国家数 ≥ 2

## 核心场景：禁止 riba

- principle: `SH-PRINCIPLE-RIBA-001`
- `rules_by_principle` countries: `['ID', 'MY']`
- `semantic_search("禁止 riba")` countries: `['ID', 'MY']`
- `link_search("禁止 riba")` countries: `['ID', 'MY']`
- core_pass: **PASS**

## 按原则 ID 反查

| principle | label | countries | counts | pass |
| --- | --- | --- | --- | --- |
| `SH-PRINCIPLE-RIBA-001` | 禁止 riba | `['ID', 'MY']` | `{'ID': 11, 'MY': 26}` | PASS |
| `SH-PRINCIPLE-SUKUK-001` | sukuk | `['ID', 'MY']` | `{'ID': 4, 'MY': 10}` | PASS |
| `SH-PRINCIPLE-HALAL-HARAM-001` | halal/haram | `['ID', 'MY']` | `{'ID': 12, 'MY': 5}` | PASS |

## semantic / link 检索

| mode | query | countries | pass |
| --- | --- | --- | --- |
| semantic | `禁止 riba` | `['ID', 'MY']` | PASS |
| semantic | `riba 利息 马来西亚 印尼` | `['ID', 'MY']` | PASS |
| link | `禁止 riba` | `['ID', 'MY']` | PASS |
| link | `SH-PRINCIPLE-RIBA-001` | `['ID', 'MY']` | PASS |
