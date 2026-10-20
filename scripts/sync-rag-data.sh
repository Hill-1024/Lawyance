#!/usr/bin/env bash
# 仅供我方开发机/自营法库服务使用；不要在客户机器同步私有语料。
# 在未被运行服务使用的候选代码目录中执行，验收后再切换服务配置。
#
# LAWVER_RAG_DATA_REPO=git@github.com:Hill-1024/Lawyance-Law-Data.git \
#   bash scripts/sync-rag-data.sh v2026.10.17
# LAWVER_RAG_DATA_DIR=/path/to/data-checkout bash scripts/sync-rag-data.sh
#
# 保留既有参数约定。成功后保留旧 RAG/data 的同级备份，不构建索引或重启服务。
set -euo pipefail

die() { printf '%s\n' "$*" >&2; exit 2; }

reject_symlink_components() {
  local path="$1" parent
  while [[ -n "$path" && "$path" != / && "$path" != . ]]; do
    [[ ! -L "$path" ]] || die "拒绝符号链接路径：$path"
    parent="$(dirname -- "$path")"
    [[ "$parent" != "$path" ]] || break
    path="$parent"
  done
}

reject_tree_links() {
  local link
  link="$(find "$1" -type l -print -quit)"
  [[ -z "$link" ]] || die "语料目录不能包含符号链接：$link"
}

reject_symlink_components "${BASH_SOURCE[0]}"
ROOT="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
RAG_DIR="$ROOT/RAG"
DEST="$RAG_DIR/data"
REF="${1:-${LAWVER_RAG_DATA_REF:-v2026.10.17}}"
REPO="${LAWVER_RAG_DATA_REPO:-https://github.com/Hill-1024/Lawyance-Law-Data.git}"
SOURCE_DIR="${LAWVER_RAG_DATA_DIR:-}"
EXPECTED_COUNT=5237
WORK_DIR=""
BACKUP=""
LOCKED=0
LOCK_DIR="$RAG_DIR/.data-sync.lock"

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  # 只在旧目录已备份、新目录尚未就位时恢复；绝不覆盖意外出现的目标。
  if [[ "$status" != 0 && -n "$BACKUP" && -d "$BACKUP" ]]; then
    if [[ ! -e "$DEST" && ! -L "$DEST" ]]; then
      if mv -T -- "$BACKUP" "$DEST"; then
        printf '同步失败，已恢复原语料目录。\n' >&2
      else
        printf '自动恢复失败；原语料备份仍在：%s\n' "$BACKUP" >&2
      fi
    else
      printf '原语料备份保留在：%s\n' "$BACKUP" >&2
    fi
  fi
  # 递归清理前，限定到本次在已校验 RAG 目录内创建的暂存路径。
  if [[ -n "$WORK_DIR" && "$WORK_DIR" == "$RAG_DIR"/.data-sync.* && ! -L "$WORK_DIR" ]]; then
    rm -rf -- "$WORK_DIR" || true
  fi
  if [[ "$LOCKED" == 1 ]]; then rmdir -- "$LOCK_DIR" || true; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

reject_symlink_components "$DEST"
[[ ! -e "$RAG_DIR" || -d "$RAG_DIR" ]] || die "RAG 不是目录：$RAG_DIR"
[[ ! -e "$DEST" || -d "$DEST" ]] || die "语料目标不是目录：$DEST"
if [[ -d "$DEST" ]]; then reject_tree_links "$DEST"; fi

# 先解析本地源并拒绝双向包含关系，再创建任何暂存目录。
if [[ -n "$SOURCE_DIR" ]]; then
  reject_symlink_components "$SOURCE_DIR"
  [[ -d "$SOURCE_DIR" ]] || die "语料目录不存在：$SOURCE_DIR"
  SRC="$(cd -P -- "$SOURCE_DIR" && pwd -P)"
  [[ "$SRC" != / ]] || die "语料源不能包含目标目录：$SRC / $DEST"
  source_compare="$SRC"
  dest_compare="$DEST"
  case "${OSTYPE:-}" in
    msys*|cygwin*) source_compare="${SRC,,}"; dest_compare="${DEST,,}" ;;
  esac
  if [[ "$source_compare" == "$dest_compare" || "$source_compare" == "$dest_compare/"* || "$dest_compare" == "$source_compare/"* ]]; then
    die "语料源与目标不能相同或互相包含：$SRC / $DEST"
  fi
fi

mkdir -p -- "$RAG_DIR"
reject_symlink_components "$LOCK_DIR"
mkdir -- "$LOCK_DIR" 2>/dev/null || die "已有语料同步锁：$LOCK_DIR（确认无同步进程后再处理）"
LOCKED=1
WORK_DIR="$(mktemp -d "$RAG_DIR/.data-sync.XXXXXXXX")"
if [[ -z "$SOURCE_DIR" ]]; then
  command -v git >/dev/null 2>&1 || die "需要 git 来拉取私有法库数据仓"
  git clone --quiet --no-checkout -- "$REPO" "$WORK_DIR/source"
  git -C "$WORK_DIR/source" checkout --quiet "$REF"
  SRC="$WORK_DIR/source"
fi
reject_tree_links "$SRC"
[[ -f "$SRC/manifest.sha256" && ! -L "$SRC/manifest.sha256" ]] || die "数据源缺少普通文件 manifest.sha256：$SRC"

if command -v sha256sum >/dev/null 2>&1; then
  HASHER=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASHER=(shasum -a 256)
else
  die "需要 sha256sum 或 shasum 校验语料"
fi

# 只归档 manifest 中的普通文件，不把数据仓的其它文件带入语料目录。
# 不接受 checksum 转义行或路径穿越；归一化后同时拒绝重复项。
manifest_pattern='^([[:xdigit:]]{64}) [ *](.+)$'
declare -A seen=()
count=0
: > "$WORK_DIR/manifest.sha256"
: > "$WORK_DIR/paths"
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ "$line" =~ $manifest_pattern ]] || die "manifest.sha256 行格式无效"
  digest="${BASH_REMATCH[1]}"
  name="${BASH_REMATCH[2]}"
  name="${name#./}"
  [[ -n "$name" && "$name" != /* && "$name" != *\\* && "$name" != *:* && "$name" != *$'\r'* && "$name" != *$'\t'* ]] || die "manifest 包含危险路径：$name"
  case "/${name,,}/" in
    *'//'*|*'/./'*|*'/../'*|*'/.git/'*) die "manifest 包含危险路径：$name" ;;
  esac
  [[ "$name" != manifest.sha256 ]] || die "manifest 不能包含自身"
  key="$name"
  case "${OSTYPE:-}" in msys*|cygwin*) key="${name,,}" ;; esac
  [[ -z "${seen[$key]+present}" ]] || die "manifest 包含重复路径：$name"
  [[ -f "$SRC/$name" && ! -L "$SRC/$name" ]] || die "manifest 文件缺失或不是普通文件：$name"
  seen["$key"]=1
  count=$((count + 1))
  [[ "$count" -le "$EXPECTED_COUNT" ]] || die "manifest 文件数超过期望 $EXPECTED_COUNT"
  printf '%s  %s\n' "$digest" "$name" >> "$WORK_DIR/manifest.sha256"
  printf '%s\0' "$name" >> "$WORK_DIR/paths"
done < "$SRC/manifest.sha256"
[[ "$count" == "$EXPECTED_COUNT" ]] || die "语料文件数异常：$count（期望 $EXPECTED_COUNT）"

# 先检查归档类型，确保解包到空暂存目录时没有符号链接、硬链接或特殊文件。
tar -C "$SRC" --no-recursion --hard-dereference --null -T "$WORK_DIR/paths" -cf "$WORK_DIR/payload.tar"
tar -tvf "$WORK_DIR/payload.tar" > "$WORK_DIR/archive-list"
while IFS= read -r entry; do
  [[ "$entry" == -* ]] || die "语料归档包含非普通文件"
done < "$WORK_DIR/archive-list"
mkdir -- "$WORK_DIR/candidate"
tar -C "$WORK_DIR/candidate" --no-same-owner --no-same-permissions -xf "$WORK_DIR/payload.tar"
reject_tree_links "$WORK_DIR/candidate"
(cd -- "$WORK_DIR/candidate" && "${HASHER[@]}" -c ../manifest.sha256 >/dev/null)
count="$(find "$WORK_DIR/candidate" -type f -print | wc -l | tr -d '[:space:]')"
[[ "$count" == "$EXPECTED_COUNT" ]] || die "暂存语料文件数异常：$count（期望 $EXPECTED_COUNT）"

# 全部校验通过后才切换。同文件系统改名；保留旧目录备份供验收/回滚。
reject_symlink_components "$DEST"
if [[ -e "$DEST" ]]; then
  [[ -d "$DEST" ]] || die "语料目标不是目录：$DEST"
  reject_tree_links "$DEST"
  BACKUP="$(mktemp -d "$RAG_DIR/data.backup.XXXXXXXX")"
  rmdir -- "$BACKUP"
  mv -T -- "$DEST" "$BACKUP"
fi
mv -T -- "$WORK_DIR/candidate" "$DEST"
printf '已同步法库语料：%s 个文件 → %s (ref=%s)\n' "$count" "$DEST" "$REF"
if [[ -n "$BACKUP" ]]; then printf '原语料备份（验收后另行处理）：%s\n' "$BACKUP"; fi
