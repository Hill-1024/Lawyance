# 普通法系库构建清单（BUILD）

## 1. 语料

| 国家 | 目录 | 内容 |
|---|---|---|
| 缅甸 `MM` | `data/MM/documents.jsonl` | 685 份 MOI 法律文件，含条款候选；`legal_system=common` |
| 新加坡 `SG` | `data/SG/official_seed.json` | 5 部 2026 公报成文法中的 10 个 section，不含判例 |

新加坡种子只用于接口和回归，不是现行法全集。公报文本不等于已汇总的现行法。

## 2. 构建

```bash
.venv/bin/python -m RAG.common_law.scripts.assembly_smoke_cases
.venv/bin/python -c "from RAG.common_law import ensure_common_law_database_ready as e; print(e(force_rebuild=True))"
```

缅甸语料若要从 OCR 流水线重做：

```bash
.venv/bin/python -m RAG.common_law.build_corpus \
  --metadata "<MOI metadata>/legal_metadata.json" \
  --relations "<MOI downloads>/document_file_relations.json" \
  --merged-root "<formal OCR output>" \
  --provision-root "<formal OCR output>"
```

默认写到 `data/MM/documents.jsonl`。

## 3. 缓存

- `cache/myanmar_law.db`
- `cache/singapore_law.db`

语料指纹变了会重建。`cache/` 不入库。
