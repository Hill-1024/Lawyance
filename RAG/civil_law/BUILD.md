# 大陆法系库构建清单（BUILD）

对齐《Lawver 管辖库工作协调规范》v1.0 §4。记录语料清单、构建方式、待核验项与已知问题。

## 1. 语料清单

语料位于 `RAG/civil_law/data/<国家>/`，为统一 schema 的 JSONL，每行一条法条。

| 国家 | 目录 | 文件 | 条文 | 其中不可用 |
|---|---|---|---|---|
| 印度尼西亚 | `data/indonesia/` | 1,941 | 51,517 | 3,716 |
| 泰国 | `data/thailand/` | 8 | 3,493 | 0 |
| 越南 | `data/vietnam/` | 1,456 | 31,711 | 79 |
| **合计** | | **3,405** | **86,721** | **3,795** |

**全部 86,721 条都进了库，无跳过**。其中 82,926 条可检索；`usable = false` 的 3,795 条仍写入库表
但被 `usable = 1` 过滤，保留以便日后修复后重新启用。

### 1.1 核心法典

| 国家 | 法典 | 条数 |
|---|---|---|
| 印尼 | KUHPerdata 民法典 | 2,124 |
| 印尼 | KUHP 刑法典（UU 1/2023） | 624 |
| 印尼 | UU 13/2003 劳动法 | 193 |
| 泰国 | ประมวลกฎหมายแพ่งและพาณิชย์ 民商法典 | 1,841 |
| 泰国 | 民事诉讼法典 / 刑事诉讼法典 / 刑法典 | 437 / 304 / 446 |
| 泰国 | ประมวลรัษฎากร 税法典 | 298 |
| 越南 | BLDS 2015 民法典 | 689 |
| 越南 | BLTTDS 2015 民诉法典 | 517 |
| 越南 | BLTTHS 2015 刑诉法典 | 510 |
| 越南 | BLHS 2015 刑法典 | 427 |
| 越南 | Luật TTHC 2015 行政诉讼法 | 372 |
| 越南 | BLLĐ 2019 劳动法典 | 220 |

## 2. 构建

```bash
# 仓库根目录

# 预构建索引（部署时在拉起服务进程之前跑，把重建成本挪到发布阶段）
.venv/Scripts/python -m RAG.civil_law.scripts.warm_cache

# 冒烟
.venv/Scripts/python -m RAG.civil_law.scripts.assembly_smoke_cases

# 强制重建索引
.venv/Scripts/python -c "from RAG.civil_law import ensure_civil_law_database_ready as e; print(e(force_rebuild=True))"
```

### 2.00 语料随仓库走

语料（`data/**`，3,405 个 jsonl）已纳入版本控制，**服务端克隆仓库即可在启动时把索引建出来**，
不依赖任何外部目录。这与主库「语料进仓库、库文件由启动期构建」的做法一致。

- 被忽略、不入库的：`cache/`（SQLite 与指纹清单，可重建）、`__pycache__/`、`.mimosa/`
  —— 规则写在包内的 `.gitignore`，**没有改仓库根目录的 `.gitignore`**。
- `data/**` 在 `.gitattributes` 里标为 `-text`，禁止 git 做换行符归一化。
  原因：指纹是 `sha256(文件字节)`，而仓库开了 `core.autocrlf=true`，
  若不钉死，Windows 上索引存 LF、检出还原 CRLF 能往返，但 **Linux 服务器克隆出来是 LF，
  与开发机字节不同 → 指纹不同 → 部署后第一次启动白白多做一次整库重建**。
- 语料体积 234 MB（未压缩），仓库已有内容 111 MB；git 压缩后预计 `.git` 从 33 MB 增至约 100 MB。

- 产物：`cache/civil_law.db`（SQLite，实测约 250 MB）+ `cache/manifest.json`（指纹与文件清单）
- 指纹：`sha256(schema_version + 每个文件的 相对路径/大小/内容哈希)`
- 依赖：**仅 Python 标准库**（`sqlite3` / `json` / `re` / `hashlib`），无需装包

### 2.0 三种构建模式

| mode | 触发条件 | 实测耗时 |
|---|---|---|
| `reuse` | 语料指纹未变 | **0.08 秒** |
| `incremental` | 只有部分文件变了 | **0.2 秒** |
| `full` | 库缺失 / schema 版本升级 / `force_rebuild` | **约 6 秒** |

增量重建（对齐中国法主库的做法）：

1. `changed_source_paths()` 逐文件比 `(size, sha256)`，得出「变了或新增」与「已消失」两组文件
2. 把这两组文件对应的条文**按文件作用域**删掉（`DELETE FROM articles WHERE source_file = ?`）
3. 只重新解析「变了」的那几个文件（入库走与全量**完全相同**的 `_insert_articles`）
4. 重算受影响法律的条数；清理已无条文的孤儿法律与其别名

**正确性保证**：多次增量后的库与强制全量重建后的库，把
`(law_key, article_number, article_key, content, source_file, usable)` 排序后求哈希，
两者**完全一致**（专项验证脚本覆盖 改内容 / 增条文 / 删条文 / 删整个文件 / 恢复 五个场景）。

删按**文件作用域**而不是按法律名——虽然当前语料是严格的文件↔法律 1:1（已实测 3,405 个文件
零例外），但按文件删不依赖这个假设，将来若把多部法合并进一个文件也不会误删。

### 2.1 表结构

| 表 | 用途 |
|---|---|
| `laws` | 法律级元数据（法名、国家、语言、来源、条数），`law_key` 唯一 |
| `articles` | 条文（条号、归一化条号键、正文、来源、`usable`、检索文本、`source_file`） |
| `aliases` | 法名别名 → 法律 ID，支持中文通称与简称召回 |

- `articles.article_key` 是跨语言归一化后的条号（见 INTERFACE §4.2），精确检索走它。
- `articles.source_file` 记住每条条文来自哪个 jsonl，**增量重建靠它界定删除范围**。
  schema 版本 2 引入；版本 1 的库会被指纹机制自动判定为需重建（`SCHEMA_VERSION` 参与指纹）。

## 3. 冒烟结果

`scripts/assembly_smoke_cases.py` 覆盖规范 §5 清单，退出码 0 = 通过。

| # | 用例 | 结果 |
|---|---|---|
| 1 | `ensure_civil_law_database_ready()` | PASS（mode=full/reuse） |
| 2 | `exact_search` 三国条号写法（Pasal / มาตรา / Điều） | PASS |
| 3 | 中文别名命中 + `semantic_search` 与 `fuzzy_search` 等价 | PASS |
| 4 | `link_search` 自然语言抽引用 | PASS |
| 5 | 国家过滤（本法系特有） | PASS |
| 6 | `usable=false` 记录已隔离 | PASS |
| 7 | 增量重建接线：清单比对方向正确（本法系特有） | PASS |

**7/7 ALL_PASS。**

另有专项增量验证（临时改动语料后全部还原，脚本在系统临时目录，未入库）：

| 场景 | 期望 | 结果 |
|---|---|---|
| 语料未变 | `reuse` | PASS |
| 改一个文件的内容 | `incremental`，新旧正文正确替换 | PASS |
| 追加一条条文 | `incremental`，新条文可精确检索 | PASS |
| 删掉该条文 | `incremental`，检索不到 | PASS |
| 删掉整个文件 | `incremental`，该文件条文清零、孤儿法律被移除 | PASS |
| 恢复文件 | `incremental`，条文回来 | PASS |
| **增量结果 vs 全量重建** | **内容哈希完全一致** | PASS |

原语料文件在验证后已还原，与主库（`E:\Code\大陆法系数据存储`）字节一致。

## 3.1 交给总装的接线（未完成）

三国库的索引准备接口已就绪，但**应用启动时不会触发它**——启动链
`app_factory.py → services/law_cache.py → mcps.ensure_law_database_ready()` 只调了主库。
要让"服务起来索引就已建好"，需要总装在 `mcps.py` 加一行转发、在
`services/law_cache.py` 的 `prepare_on_startup` 里调用。

**这两处管辖库侧不能动**：架构护栏 I4 规定 `services/**` 不得 import `RAG`，
合规写法必须经 `mcps.py`；而 `mcps.py` 是协调规范 §2.3 的红线文件。

完整的改动代码、设计说明与验收步骤见 **[INTERFACE.md §6](INTERFACE.md)**。
部署前的临时替代方案：跑 `python -m RAG.civil_law.scripts.warm_cache` 预热。

## 4. 待核验 / 待补

1. **泰国 2,583 条无 `url`**（民商法典 1,841、民诉法典 437、刑诉法典 304、第 54 号修正法 1）。
   这些条文来自本地 PDF，记录里只有文件名。需到 `krisdika.go.th` 核实对应页面地址后回填；
   **在补上之前，这些条文的引用无法生成可点击信源**。
2. **泰国刑法典 446 条的正文尚未与官方页面核对**。`url` 已指向
   `searchlaw.ocs.go.th`（泰国国务院官方法律检索站）的刑法典页面，但正文仍取自非官方编校本
   `xinsong.pdf`，有字形伪影，其中 10 条被标注「疑被相邻条号截断」。
3. **越南 74 条三位数断裂条号**（真假混杂）列在
   `E:\Code\大陆法系数据存储\_说明文档\质检清单-2026-09-17.md` 第三节，尚未处理。
4. **印尼 143 条空 `url`**（UUD 1945 合并本 73、UU 5/1960 共 58、其余 12）。
5. `status` / `effective_date` 大面积为 `unknown`：印尼仅 1.9% 有条文级生效日期、
   越南 8.6%、泰国 0%。需三国官方源提供逐条效力信息才能补齐。

## 5. 已知问题

1. **`fuzzy_search` 是关键词检索不是向量检索**。当前实现是 `instr` 包含判断 + 打分排序，
   跨语言（中文提问 vs 三国原文）只能靠法名别名召回，无法做真正的语义匹配。
   要上向量检索需先配 embedding 服务。
2. **空 `url` 的条文不生成信源链接**。OCP 会对这些条目写「该条缺少可核验链接」，
   这是符合规范的处理（§6.2 禁止编造），但会降低该条回答的可溯源性。
3. **条号归一化会合并同号的字母插入条**。例如 `Pasal 131` 与 `Pasal 131a` 归一化为
   `131` 与 `131a`，两者不同键，但若语料里同一法出现两个 `Pasal 131`，精确检索只返回第一条
   （`ORDER BY a.id LIMIT 1`）。
4. **印尼语料的效力状态几乎全为 `unknown`**，若下游按 `status` 做时效过滤，印尼条文会被大量过滤掉。

## 6. 构建期踩过的坑（留给后来人）

1. **不要在插入条文后回填条数**：`UPDATE laws SET article_count = (SELECT COUNT(*) …)` 会让
   SQLite 对每部法全表扫一遍 articles，建库从 8 秒变 420 秒。条数在插入时用 Python 计好，
   最后 `executemany` 一次性更新。
2. **不要在插入后用 UPDATE 回填法名别名到 `search_blob`**：3,200 余次全行重写同样很慢。
   别名要在第一趟就算好，插入条文时直接写进检索文本。
3. **SQL 语句要写在 `conn.execute()` 调用点**（项目安全钩子只放行内联字面量，
   经变量传入的 SQL 会被判为 SQL 注入风险）。外部输入一律走 `?` 占位符，
   包含匹配用 SQLite 的 `instr()`，不构造通配符、不拼接 SQL 文本。
4. **印尼总统决定书用罗马数字条号**（`Pasal I`、`Pasal II`）。条号归一化若不认罗马数字，
   380 条 KEPPRES/INPRES 条文会被整批静默丢弃（实测「跳过 380 条」）。
   `_roman_to_int` 限定 1..50 且要求反向回写一致，避免把正文里的 MIX、DIV 当数字。
5. **`executemany` 的参数顺序要和 SQL 占位符一一对应**。曾把
   `UPDATE laws SET article_count = ? WHERE id = ?` 传成 `(law_id, count)`，
   结果 `article_count` 全库错乱，还连带让按条数排序的法名别名解析选错了法律
   （问「泰国税法典」返回了修正法而非法典本体）。
6. **增量是就地改库，必须开日志模式**。全量重建写的是临时文件、可以
   `PRAGMA journal_mode = OFF`（快很多）；而 `journal_mode` 是**写进库头、持久生效**的，
   所以全量建完要显式回落成 `DELETE`，否则后续增量写入遇到崩溃无法回滚。
7. **增量必须持跨进程文件锁**。线程锁只管得住本进程；多 worker 下两个进程同时增量写
   同一个库会互相破坏。`_build_file_lock()` 在 POSIX 用 `fcntl.flock`、
   Windows 用 `msvcrt.locking`。
8. **`Path.replace()` 本身就是原子覆盖，不要先 `unlink()`**。先删会制造一个
   「库不存在」的窗口，并发读者可能正好撞上。
