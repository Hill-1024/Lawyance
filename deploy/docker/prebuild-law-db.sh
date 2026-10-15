#!/usr/bin/env bash
# 预建法库索引：把 210MB 的 law.db + manifest 直接建进实例的命名卷。
#
# 用法（在 deploy/docker 下）：
#   ./prebuild-law-db.sh /srv/lawver-instances/lawver
#
# 为什么需要它：功能页首次启动会扫一遍语料（5237 个文件、约 46MB 全量 SHA256）再决定
# 是否重建；若索引不存在或 schema 版本对不上，就是分钟级的全量重建。放在"起容器"里做，
# 表现为"刚部署完页面半天不上线"。这里先用一次性容器把索引建好，正式起容器时那次扫描
# 会直接判定 unchanged。
#
# 用 docker compose run 而不是另起 docker run：这样卷、环境变量、挂载点全部取自实例
# 自己的 compose 定义，不会与运行期有任何偏差。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANCE_DIR="${1:-}"
[[ -n "$INSTANCE_DIR" ]] || { printf '用法：%s <实例目录（含 compose.env）>\n' "$(basename "$0")" >&2; exit 2; }
[[ -f "$INSTANCE_DIR/compose.env" ]] || { printf '%s 下没有 compose.env\n' "$INSTANCE_DIR" >&2; exit 2; }

command -v docker >/dev/null 2>&1 || { echo "需要 docker" >&2; exit 2; }

cd "$INSTANCE_DIR"
printf '\n\033[1m在实例 %s 的法库卷里构建索引（分钟级，请勿中断）\033[0m\n' "$(basename "$INSTANCE_DIR")"

# --no-deps：不拉起 router/intro，只借这个服务的卷与配置跑一次性命令
docker compose --env-file compose.env \
  -f "$HERE/compose.yml" -f "$HERE/compose.self-hosted.yml" \
  run --rm --no-deps app \
  python -c 'from RAG.law_data_search import ensure_law_database_ready as e; import json; print(json.dumps(e(), ensure_ascii=False, indent=2))'

printf '\n索引已就绪。正式启动时启动期扫描会判定 unchanged，不再重建。\n'
