#!/usr/bin/env bash
# 从 Git 已跟踪文件准备受控上下文，只构建本地客户镜像，不推送。
# 用法：bash deploy/docker/build-customer.sh --tag RELEASE_TAG
# LAWVER_BUILD_PYTHON 可指定本机 Python 3.9+（应用运行仍需 Python 3.13+）。
set -euo pipefail

HERE="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -P -- "$HERE/../.." && pwd -P)"
PYTHON="${LAWVER_BUILD_PYTHON:-python3}"
TAG=local
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="${2:?--tag 需要镜像版本}"; shift 2 ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ "$TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo '镜像版本格式无效' >&2; exit 2; }
command -v "$PYTHON" >/dev/null 2>&1 || { echo '需要 Python（可设置 LAWVER_BUILD_PYTHON）' >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo '需要 Docker' >&2; exit 2; }

APP_UID="${LAWVER_APP_UID:-$(id -u lawver 2>/dev/null || echo 1000)}"
APP_GID="${LAWVER_APP_GID:-$(id -g lawver 2>/dev/null || echo 1000)}"
[[ "$APP_UID" =~ ^[0-9]+$ && "$APP_GID" =~ ^[0-9]+$ ]] || { echo 'UID/GID 必须为数字' >&2; exit 2; }

# mktemp 创建独立目录；递归清理仅限此次在解析后的临时目录中创建的路径。
TEMP_BASE="$(cd -P -- "${TMPDIR:-/tmp}" && pwd -P)"
CONTEXT="$(mktemp -d "$TEMP_BASE/lawver-customer.XXXXXXXX")"
cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$CONTEXT" == "$TEMP_BASE"/lawver-customer.* && ! -L "$CONTEXT" ]]; then
    rm -rf -- "$CONTEXT" || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$PYTHON" "$ROOT/scripts/package-customer.py" --build-context "$CONTEXT"
docker build \
  --file "$CONTEXT/deploy/docker/Dockerfile" \
  --target customer \
  --build-arg "APP_UID=$APP_UID" \
  --build-arg "APP_GID=$APP_GID" \
  --tag "lawver-customer:$TAG" \
  "$CONTEXT"
