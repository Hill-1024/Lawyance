# 独立法库的 GitHub 协作与部署边界

源码以 CN Git 仓库为准。独立服务的发布目录是从仓库导出的运行副本，不需要再成为完整 Git 仓库。

| 内容 | 源码位置或运行位置 | 是否进入 Git |
| --- | --- | --- |
| 服务 API、主站适配器、测试 | `law_service/`、`backend/mcp/`、`tests/` | 是 |
| 部署工具、unit 模板、验收脚本和说明 | `scripts/deploy/`、`deploy/`、`docs/` | 是 |
| 当前已发布的服务代码副本 | `/srv/lawver-law/releases/`、`current` | 从已验证源码发布，不在此协作改代码 |
| 生产环境配置与真实密钥 | 主站 `.env`、`/etc/lawver-law/` | 否 |
| 原始语料、索引、审计、备份及构建产物 | 数据目录、`/var/lib/lawver-law/`、备份目录、`TEMP/`、`dist/` | 不作为部署工具源码提交 |

仓库中有文件不等于已同步 GitHub。`git status` 的 `M` 和 `??` 分别表示尚未提交的修改和未跟踪文件；需要检查、明确选择文件、提交、推送和审查后，团队才能从分支获得同一套实现。部署变更应在专用分支提交，不使用 `git add .` 混入服务器专用配置或数据。

基准 main@cf45e6a / af99528 仍跟踪 `RAG/data/`。本修复取消当前版本的语料跟踪并补回
私有数据源同步流程，见 [RAG/README.md](../RAG/README.md)。已有工作区语料保留，
旧 Git 提交仍含语料；不在本修复中重写历史。客户包与 Docker 无 Git 上下文的清洗
分别验收，不能仅凭取消跟踪宣称全部客户分发边界已完成。

## CN 检索配置准备脚本

`scripts/deploy/prepare_law_remote.py` 是部署配置工具，不是数据集构建脚本。它读取已存在的 CN 专用密钥，制作候选 `.env`，用真实服务账号调用三个工具，检查通过后保留私密备份并原子替换 `.env`。它不重启服务、不发布前端产物、不上传 GitHub。

脚本从自身路径推导项目根目录；提交号、前端暂存目录、unit、服务地址、密钥文件和备份目录可通过参数传入。提交代码会改变 HEAD，因此不要在脚本源码中固定其自身所需的提交 SHA。

在 CN 项目根目录执行。先选定并记录已经审查、测试的完整提交号：

```bash
git rev-parse HEAD
.uv_env/bin/python scripts/deploy/prepare_law_remote.py --help

sudo .uv_env/bin/python -B scripts/deploy/prepare_law_remote.py \
  --expected-head TESTED_FULL_COMMIT_SHA
```

`--expected-head` 必须填写完整的 40 位 SHA。法库配置准备不需要前端构建。可选的 `--frontend-staging` 只记录本项目 `TEMP/` 下已有产物的路径与校验值，不发布它。新提交后重新填写该 SHA；不要为绕过版本检查而改动脚本源码。

现有的一次性法库补丁尚未提交时，可以额外指定它的完整性清单：

```bash
  --patch-manifest /absolute/path/to/manifest.json \
  --patch-manifest-sha EXPECTED_MANIFEST_SHA256
```

两项必须一起提供。清单会核对已应用补丁的逐文件 SHA，不能替代 Git 提交、协作审查和当前环境验收。

默认读取 `/etc/lawver-law/keys.json` 中名为 `cn-main` 的密钥；真实值不作为命令行参数或终端输出。私密配置备份默认保存在服务账号家目录的 `lawver-backups/`，准备记录默认写入 `/etc/lawver-law/cn-prepared.json`。这些运行文件留在服务器。

## 后续发布

团队修改 `law_service/` 后，先提交、审查和测试，再把同一版本发布到新的服务 release 目录并切换 `current`。`git pull` 更新项目源码，不会自动更新 `/srv/lawver-law/current` 指向的副本。

主站的工作目录仍是 CN 项目；前端产物发布和主站重启也需要明确执行。一次配置准备完成，不能替代网页端、真实工具调用、密钥生命周期以及独立 HTTPS / 客户环境验收。ASEAN 的多法域远程适配另行完成。
