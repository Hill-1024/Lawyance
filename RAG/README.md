# 本地法库语料

`RAG/` 保存检索引擎；`RAG/data/` 的语料从当前代码版本中取消跟踪，
由我方开发环境或自营服务器单独取得。客户部署使用远程法库，不同步语料。

## 数据来源与同步

数据源约定为私有仓 `Hill-1024/Lawyance-Law-Data`，默认版本为
`v2026.10.17`，清单为 `manifest.sha256`，该版本预期包含 5,237 个语料文件。
需要 Bash 4+、Git、GNU tar/coreutils、find 及 `sha256sum` 或 `shasum`。
Windows 开发环境可使用 Git Bash。

以下命令仅从获授权的开发环境、自营服务器的候选项目根目录执行。
目标固定为脚本所属项目的 `RAG/data/`，不是执行命令时任意工作目录下的 `RAG/data/`：

```bash
LAWVER_RAG_DATA_REPO=git@github.com:Hill-1024/Lawyance-Law-Data.git \
  bash scripts/sync-rag-data.sh v2026.10.17
```

也可以使用已经从私有仓取得的目录；目录根部须包含 `manifest.sha256`：

```bash
LAWVER_RAG_DATA_DIR=/absolute/path/to/Lawyance-Law-Data \
  bash scripts/sync-rag-data.sh
```

源目录必须与目标 `RAG/data/` 分开。脚本先校验清单约束的暂存副本及文件数量，
再备份旧目录并切入新目录；替换失败时尝试恢复旧目录。数据仓凭据留在机器的
凭据管理中，不写进仓库、命令 URL 或文档。该步骤不构建索引、不重启服务。

同步应在首次部署或未被运行服务使用的候选目录中进行。目录换名不保证并发查询
能跨换版保持一致；正在运行的独立法库按已验证 release 和 `current` 的流程换版。
验证数据版本与三个检索端点后，再按脚本输出处理保留的旧数据备份。
旧数据备份位于 `RAG/data.backup.*`；备份、同步暂存目录及同步锁均由 `.gitignore`
和 `.dockerignore` 排除，不提交到代码仓或加入镜像构建上下文。

## 分发与历史

- `RAG/data/`、`RAG/cache/` 均被忽略；当前 Git 索引应满足 `git ls-files RAG/data` 为空。
- 客户包与镜像排除本地法库；客户远程模式无需上述数据仓权限。
- 从当前版本取消跟踪不会清除旧 Git 提交中的语料。本次修复不重写历史，
  客户交付物检查与 Git 历史处理分别进行。
