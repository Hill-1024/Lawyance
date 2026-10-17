# RAG 法库语料

`RAG/data/` **不再随主仓分发**，也不进入容器镜像或客户部署物。它是私有资产，存放在：

- 私有数据仓：`Hill-1024/Lawyance-Law-Data`
- 版本标签：`v2026.10.17`
- 校验：仓内 `manifest.sha256`（5237 个文件）

## 首次拉取 / 更新

```bash
LAWVER_RAG_DATA_REPO=git@github.com:Hill-1024/Lawyance-Law-Data.git \
  ./scripts/sync-rag-data.sh v2026.10.17
```

没有数据仓访问权限的机器，先把数据仓检出或打包为目录，再：

```bash
LAWVER_RAG_DATA_DIR=/path/to/Lawyance-Law-Data ./scripts/sync-rag-data.sh
```

脚本会校验 `manifest.sha256` 后再替换 `RAG/data/`，校验失败不会动现有语料。`RAG/data/` 已加入 `.gitignore`，同步后也不会重新进入主仓。

## 说明

- `RAG/cache/` 是启动时构建的 SQLite 索引，同样不入库；语料更新后应用会按 manifest 增量重建。
- 数据源更新流程见私有数据仓 README：改语料 → 重新生成 manifest → 打新 tag → 更新本目录/部署文档中的默认 ref。
- 不要把语料复制回主仓、公开仓库或客户交付物；历史泄露风险见 issue #12。
