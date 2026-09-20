# 普通法系管辖库（RAG/common_law）

缅甸 / 新加坡法律检索库，目录形态对齐 `RAG/civil_law` 与 `RAG/islamic_law`：一个法系一个包，国家语料放在 `data/<国家码>/`。

## 职责边界

本包只负责普通法系这两个国家的语料和检索，不注册 LLM Tool，也不改 `tools/`、`mcps.py`、`function_calling.py`。与总装的接线由总装按管辖路由完成。

## 目录

```
RAG/common_law/
├── __init__.py                  re-export 检索接口
├── search.py                    门面：按国家路由，未指明时合并两边结果
├── myanmar.py                   缅甸引擎
├── singapore.py                 新加坡引擎
├── build_corpus.py              缅甸语料重建（需要外部 OCR 输入）
├── data/
│   ├── MM/                      缅甸 MOI 语料（documents.jsonl）
│   └── SG/                      新加坡成文法种子（official_seed.json）
├── cache/                       构建产物，可删，会自动重建
│   ├── myanmar_law.db
│   └── singapore_law.db
├── scripts/
│   └── assembly_smoke_cases.py
├── INTERFACE.md
└── BUILD.md
```

两国索引仍是两个 SQLite 文件。缅甸按整份文件加条款候选入库，新加坡按成文法 section 入库，不并成一张表。

## 常用命令

```bash
.venv/bin/python -m RAG.common_law.scripts.assembly_smoke_cases
.venv/bin/python -c "from RAG.common_law import exact_search; print(exact_search('Central Provident Fund (Amendment) Act 2026','第1条'))"
```
