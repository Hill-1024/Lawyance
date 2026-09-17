# 大陆法系管辖库（RAG/civil_law）

印度尼西亚 / 泰国 / 越南三国法律检索库，按《Lawyance 管辖库工作协调规范》v1.0 建设。

## 职责边界

本包**只负责自己法域**的语料清洗、索引和检索。以下文件一行不改，也不自行注册 LLM Tool：

- `tools/__init__.py`、`tools/registry.py`
- `mcps.py`、`function_calling.py`
- `mcp/pkulaw_client.py`
- `ocp.py`、`RAG/law_data_search.py`

与总装的接线由总装负责，本包只保证 API 与 envelope 可对接。**接线清单见
[INTERFACE.md §6](INTERFACE.md#6-总装接线清单需总装执行管辖库侧不得自行修改这些文件)**，
包含启动期建库（`mcps.py` + `services/law_cache.py` 两处改动，含可直接采用的代码）
与工具面的 `jurisdiction` 参数、`mcp/legal_search_router.py`。

那两处必须由总装落，是因为架构护栏 `tests/test_architecture_boundaries.py` 的 I4 规定
`services/**` 不得 import `RAG`，合规写法只能经 `mcps.py` 转发；而 `mcps.py` 是协调规范
§2.3 的红线文件，管辖库侧不擅自改。

## 目录

```
RAG/civil_law/
├── __init__.py                  re-export 六个函数
├── search.py                    引擎：索引构建 + 检索
├── data/                        语料（3,405 个 JSONL，86,721 条）
│   ├── indonesia/
│   ├── thailand/
│   └── vietnam/
├── cache/                       构建产物（可删，会自动重建）
│   ├── civil_law.db
│   └── manifest.json
├── scripts/
│   └── assembly_smoke_cases.py  对接冒烟（退出码 0 = 通过）
├── INTERFACE.md                 接口与字段协议
└── BUILD.md                     语料清单、构建方式、待核验项
```

## 常用命令

```bash
# 预构建索引（部署时在拉起服务进程之前跑；已建好则 0.1 秒返回）
.venv/Scripts/python -m RAG.civil_law.scripts.warm_cache

# 冒烟（首次会自动建索引，约 7 秒）
.venv/Scripts/python -m RAG.civil_law.scripts.assembly_smoke_cases

# 快速试一下检索
.venv/Scripts/python -c "from RAG.civil_law import exact_search; print(exact_search('印尼民法典','第1条'))"

# 语料变了之后强制重建
.venv/Scripts/python -c "from RAG.civil_law import ensure_civil_law_database_ready as e; print(e(force_rebuild=True))"
```

## 数据来源与合规

- 语料来自三国官方或公开站点：印尼 `jdih.setneg.go.id`、泰国 `krisdika.go.th` /
  `rd.go.th` / `searchlaw.ocs.go.th`、越南 `datafiles.chinhphu.vn` / `vbpl.vn`，
  部分来自 wikisource（社区转录，非官方，已在记录 `note` 中标注）。
- 三国法律文本本身不受版权保护（见数据存储目录的 `README.md`）。
- **未核验的一律不推测**：`url` 拿不到就留空串，`effective_date` 不知道就留空，
  绝不编造链接或日期（规范 §2.3）。

## 相关文档

- 语料主库与质检清单：`E:\Code\大陆法系数据存储\`（数据以此为准，本包 `data/` 是其副本）
- 接口协议：[INTERFACE.md](INTERFACE.md)
- 构建与待办：[BUILD.md](BUILD.md)
