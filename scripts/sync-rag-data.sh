#!/usr/bin/env bash
# 从私有法库数据仓同步 RAG/data。
#
# 语料不随主仓分发（见 RAG/README.md）。首次开发、CI 或部署前运行：
#   LAWVER_RAG_DATA_REPO=git@github.com:Hill-1024/Lawyance-Law-Data.git \
#     scripts/sync-rag-data.sh v2026.10.17
#
# 没有 GitHub 凭证的机器可以先把数据仓打成 tar 或目录，再用：
#   LAWVER_RAG_DATA_DIR=/path/to/checkout scripts/sync-rag-data.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/RAG/data"
REF="${1:-${LAWVER_RAG_DATA_REF:-v2026.10.17}}"
REPO="${LAWVER_RAG_DATA_REPO:-https://github.com/Hill-1024/Lawyance-Law-Data.git}"
SOURCE_DIR="${LAWVER_RAG_DATA_DIR:-}"
TMP=""

cleanup() {
  if [[ -n "$TMP" && -d "$TMP" ]]; then rm -rf "$TMP"; fi
}
trap cleanup EXIT

if [[ -n "$SOURCE_DIR" ]]; then
  [[ -d "$SOURCE_DIR" ]] || { echo "语料目录不存在：$SOURCE_DIR" >&2; exit 2; }
  SRC="$(cd "$SOURCE_DIR" && pwd)"
else
  command -v git >/dev/null 2>&1 || { echo "需要 git 来拉取私有法库数据仓" >&2; exit 2; }
  TMP="$(mktemp -d)"
  git clone --quiet --no-checkout "$REPO" "$TMP/data"
  git -C "$TMP/data" checkout --quiet "$REF"
  SRC="$TMP/data"
fi

[[ -f "$SRC/manifest.sha256" ]] || { echo "数据源缺少 manifest.sha256：$SRC" >&2; exit 2; }
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$SRC" && sha256sum -c manifest.sha256 >/dev/null)
elif command -v shasum >/dev/null 2>&1; then
  (cd "$SRC" && shasum -a 256 -c manifest.sha256 >/dev/null)
else
  echo "需要 sha256sum 或 shasum 校验语料" >&2
  exit 2
fi

mkdir -p "$DEST"
# 只清空内容，保留 RAG/data 目录本身（容器/脚本按固定路径挂载）。
find "$DEST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
(cd "$SRC" && tar \
  --exclude='./.git' --exclude='./.git/*' \
  --exclude='./manifest.sha256' --exclude='./README.md' --exclude='./.gitattributes' \
  -cf - .) | (cd "$DEST" && tar -xf -)

COUNT="$(find "$DEST" -type f | wc -l | tr -d ' ')"
[[ "$COUNT" == "5237" ]] || { echo "语料文件数异常：$COUNT（期望 5237）" >&2; exit 1; }
echo "已同步法库语料：$COUNT 个文件 → $DEST (ref=$REF)"
