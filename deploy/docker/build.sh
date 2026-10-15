#!/usr/bin/env bash
# 构建镜像。
#
# 用法（在 deploy/docker 下）：
#   ./build.sh                       # 本地标签 lawver-app:local / lawver-intro:local
#   ./build.sh --tag v0.1.22         # 本地标签 lawver-app:v0.1.22 ...
#   ./build.sh --tag v0.1.22 --push  # 另推到 GHCR（需先 docker login ghcr.io）
#   INTRO_REPO=/srv/lawver-intro ./build.sh
#
# 为什么构建与运行分开：交付给客户的形态是**只有 compose 文件 + 拉来的镜像**，
# 客户机器上既没有源码也没有语料。所以 compose 里只写 image:，构建单独一条路走。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

TAG="local"
PUSH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="${2:?--tag 需要值}"; shift 2 ;;
    --push) PUSH=1; shift ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "需要 docker" >&2; exit 2; }

REGISTRY="${LAWVER_REGISTRY:-ghcr.io/hill-1024}"
APP_IMAGE="$REGISTRY/lawver-app:$TAG"
INTRO_IMAGE="$REGISTRY/lawver-intro:$TAG"
# 本地构建时另外打一份 :local，compose 默认值（及彩排脚本）找的就是它
LOCAL_APP="lawver-app:local"
LOCAL_INTRO="lawver-intro:local"

INTRO_REPO="${INTRO_REPO:-}"
if [[ -z "$INTRO_REPO" ]]; then
  for candidate in "$ROOT/../Lawyance_Intro" "$ROOT/../lawyance-intro"; do
    if [[ -e "$candidate/server/serve.py" ]]; then
      INTRO_REPO="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi
[[ -n "$INTRO_REPO" && -e "$INTRO_REPO/server/serve.py" ]] \
  || { echo "找不到介绍页仓库（用 INTRO_REPO=/path/to/Lawyance_Intro 指定）" >&2; exit 2; }

# 容器内运行用户的 uid/gid 必须与宿主持久化目录的属主一致，否则 data/TEMP/Result
# 写不进去（症状是应用能启动但一保存就报权限错误）。默认取本机 lawver 用户的 uid——
# 部署机上它**不是** 1000（实测是 996/993），所以不能写死默认值。
if [[ -n "${LAWVER_APP_UID:-}" ]]; then
  APP_UID="$LAWVER_APP_UID"
else
  APP_UID="$(id -u lawver 2>/dev/null || echo 1000)"
fi
if [[ -n "${LAWVER_APP_GID:-}" ]]; then
  APP_GID="$LAWVER_APP_GID"
else
  APP_GID="$(id -g lawver 2>/dev/null || echo 1000)"
fi

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

say "构建 $LOCAL_APP（= $APP_IMAGE）"
docker build \
  -f "$HERE/Dockerfile" \
  --target runtime \
  --build-arg "APP_UID=$APP_UID" \
  --build-arg "APP_GID=$APP_GID" \
  -t "$LOCAL_APP" \
  -t "$APP_IMAGE" \
  "$ROOT"

say "构建 $LOCAL_INTRO（= $INTRO_IMAGE）"
docker build \
  -f "$INTRO_REPO/Dockerfile" \
  -t "$LOCAL_INTRO" \
  -t "$INTRO_IMAGE" \
  "$INTRO_REPO"

say "镜像就绪"
docker image ls --format '  {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -E 'lawver-(app|intro)' || true

if ((PUSH)); then
  say "推送到 $REGISTRY"
  docker push "$APP_IMAGE"
  docker push "$INTRO_IMAGE"
fi
