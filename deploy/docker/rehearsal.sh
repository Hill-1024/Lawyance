#!/usr/bin/env bash
# 容器版彩排：用隔离的项目名与端口把整套 compose 起起来，跑与进程版**同一批断言**
# （deploy/router/rehearsal-lib.sh）。容器化之后"过没过"就是拿这个和进程版对比。
#
# 用法（在 deploy/docker 下）：
#   ./rehearsal.sh                    # 默认 frontier overlay：不带语料，起得快
#   ./rehearsal.sh --self-hosted      # 自营 overlay：挂语料，首次会建法库索引（分钟级）
#   KEEP_RUNNING=1 ./rehearsal.sh     # 结束时保留容器，便于浏览器查看
#   CORE_PORT=18090 ./rehearsal.sh    # 换一个宿主发布端口
#
# 隔离保证：
#   · 项目名 lawver-rehearsal-<时间戳>，卷与网络都带这个前缀，跑完 down -v 收干净；
#   · 只占一个宿主端口（默认 18080），容器内部的 8080/8081/8082 不往外发；
#   · 用临时 .env（假密钥 + 测试模式 + 关掉 APK 同步），**绝不挂生产 .env**——
#     否则任何一次误发请求都会真的打到生产模型服务上；
#   · 不依赖共享基建：走 LAWVER_WORKBENCH_TESTING 的 sqlite 兜底，不需要 Postgres。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

OVERLAY="frontier"
for arg in "$@"; do
  case "$arg" in
    --frontier) OVERLAY="frontier" ;;
    --self-hosted) OVERLAY="self-hosted" ;;
    *) printf '未知参数：%s\n' "$arg" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "需要 docker" >&2; exit 2; }

# ── 解释器（解析核心的 JSON 状态）──────────────────────────────────────────
if [[ -n "${PYTHON:-}" ]]; then
  :
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/.venv/Scripts/python.exe"
else
  PYTHON="python3"
fi

port_in_use() {
  "$PYTHON" -c "import socket,sys; s=socket.socket(); rc=s.connect_ex(('127.0.0.1',int(sys.argv[1]))); s.close(); sys.exit(0 if rc==0 else 1)" "$1"
}
pick_free_port() {
  "$PYTHON" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()"
}

CORE_PORT="${CORE_PORT:-18080}"
if port_in_use "$CORE_PORT"; then
  free="$(pick_free_port)"
  printf '端口 %s 已被占用（可能是上次残留），改用 %s\n' "$CORE_PORT" "$free" >&2
  CORE_PORT="$free"
fi
CORE="http://127.0.0.1:$CORE_PORT"
PROBE_WAIT="${PROBE_WAIT:-20}"
APP_WAIT="${APP_WAIT:-600}"

# 断言与计数来自与进程版共享的片段
. "$ROOT/deploy/router/rehearsal-lib.sh"

# ── 镜像 ───────────────────────────────────────────────────────────────────
APP_IMAGE="${LAWVER_APP_IMAGE:-lawver-app:local}"
INTRO_IMAGE="${LAWVER_INTRO_IMAGE:-lawver-intro:local}"
for img in "$APP_IMAGE" "$INTRO_IMAGE"; do
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    printf '缺少镜像 %s。先构建：%s/build.sh\n' "$img" "$HERE" >&2
    exit 2
  fi
done

# ── 介绍页检出（挂给 intro 容器；顺手做前置检查）───────────────────────────
INTRO_REPO="${INTRO_REPO:-}"
if [[ -z "$INTRO_REPO" ]]; then
  for candidate in "$ROOT/../Lawyance_Intro" "$ROOT/../lawyance-intro"; do
    if [[ -e "$candidate/server/serve.py" ]]; then
      INTRO_REPO="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi
if [[ -z "$INTRO_REPO" || ! -e "$INTRO_REPO/current/index.html" ]]; then
  for candidate in "$ROOT/../Lawyance_Intro" "$ROOT/../lawyance-intro"; do
    [[ -e "$candidate/dist/index.html" ]] || continue
    INTRO_REPO="$(cd "$candidate" && pwd)"
    break
  done
fi
INTRO_ROOT="${INTRO_ROOT:-$INTRO_REPO/current}"
[[ -e "$INTRO_ROOT/index.html" ]] || { printf '介绍页产物不存在：%s/index.html（先在介绍页仓跑 tools/build.sh）\n' "$INTRO_ROOT" >&2; exit 2; }

# ── 隔离环境 ───────────────────────────────────────────────────────────────
PROJECT="lawver-rehearsal-$(date +%s)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/lawver-docker-rehearsal.XXXXXX")"
STATE_DIR="$WORK/state"
DATA_ROOT="$WORK/data"
mkdir -p "$STATE_DIR" "$DATA_ROOT"/{data,TEMP,Result}

cat >"$WORK/app.env" <<ENV
# 彩排专用：假密钥、测试模式（sqlite 兜底，不需要 Postgres）、关掉 APK 同步。
SECRET_KEY=rehearsal-secret-rehearsal-secret-32
INITIAL_ADMIN_PASSWORD=rehearsal-admin
API_KEY=rehearsal-key
BASE_URL=http://127.0.0.1:9/v1
LLM_MODEL=rehearsal-model
LAWVER_WORKBENCH_TESTING=1
LAWVER_RELEASE_SYNC_ON_STARTUP=0
ENV

cat >"$WORK/compose.env" <<ENV
COMPOSE_PROJECT_NAME=$PROJECT
LAWVER_ROUTER_PUBLISH_PORT=$CORE_PORT
LAWVER_ROUTER_PUBLISH_HOST=127.0.0.1
LAWVER_NETWORK_SUBNET=10.99.0.0/24
LAWVER_DATA_HOST_DIR=$DATA_ROOT
LAWVER_APP_ENV_FILE=$WORK/app.env
LAWVER_INTRO_HOME=$INTRO_REPO
LAWVER_ROUTER_STATE_DIR=$STATE_DIR
LAWVER_REDIS_PREFIX=$PROJECT
LAWVER_DATABASE_URL=sqlite:///$WORK/data/cloud.sqlite3
LAW_DATA_DIR=$DATA_ROOT/TEMP/unused
PKU_LAW_SOURCE=remote
ENV

files=(-f "$HERE/compose.yml")
if [[ "$OVERLAY" == "self-hosted" ]]; then
  files+=(-f "$HERE/compose.self-hosted.yml")
  # 语料必须显式给出；本 overlay 会真的建/加载索引
  LAW_DEFAULT="$ROOT/RAG/data"
  printf '\nLAWVER_LAW_DATA_DIR=%s\n' "${LAWVER_REHEARSAL_LAW_DATA:-$LAW_DEFAULT}" >>"$WORK/compose.env"
else
  files+=(-f "$HERE/compose.frontier.yml")
fi

compose() { (cd "$WORK" && docker compose --env-file "$WORK/compose.env" "${files[@]}" "$@"); }

# 共享基建网是 external，彩排不依赖它但 compose 会校验存在性；缺了就建一张空网
if ! docker network inspect lawver-infra >/dev/null 2>&1; then
  printf '提示：lawver-infra 网络不存在，彩排临时创建一张（正式部署请用 compose.infra.yml）\n' >&2
  docker network create lawver-infra >/dev/null
fi

cleanup() {
  if [[ "${KEEP_RUNNING:-0}" == "1" ]]; then
    printf '\n保留容器（项目 %s，工作目录 %s）\n  浏览器打开 %s/ 与 %s/home\n  收尾：cd %s && docker compose --env-file %s/compose.env %s down -v && rm -rf %s\n' \
      "$PROJECT" "$WORK" "$CORE" "$CORE" "$WORK" "$WORK" "${files[*]}" "$WORK"
    return
  fi
  compose down -v >/dev/null 2>&1
  rm -f "$INTRO_ROOT/intro-assets/rehearsal.bin"
  rm -rf "$WORK"
}
trap cleanup EXIT

say "1. 起整套（overlay=$OVERLAY，宿主端口=$CORE_PORT）"
compose up -d >/dev/null
# 功能页首次可能要建法库索引；核心先起、页面随探活自动可用
deadline=$((SECONDS + APP_WAIT))
while ((SECONDS < deadline)); do
  [[ "$(status_code "$CORE/__core/status")" == "200" ]] && break
  sleep 1
done
check "核心已就绪" "200" "$(status_code "$CORE/__core/status")"
wait_side app True || true
wait_side intro True || true
check "功能页在线" "True" "$(side_up app)"
check "介绍页在线" "True" "$(side_up intro)"
check "X-Core-Upstream 标记存在" "app" "$(upstream_of "$CORE/api/health")"

say "2. 路径分派"
check "GET / → 介绍页" "200" "$(status_code "$CORE/")"
check "/ 来自介绍页容器" "intro" "$(upstream_of "$CORE/")"
check "GET /design → 介绍页" "intro" "$(upstream_of "$CORE/design")"
check "GET /home → 功能页" "app" "$(upstream_of "$CORE/home")"
check "GET /api/plans → 功能页" "app" "$(upstream_of "$CORE/api/plans")"
check_contains "GET /robots.txt 是介绍页的 robots" "Sitemap:" "$(curl -s --max-time 10 "$CORE/robots.txt")"
check_contains "GET /api/plans 返回套餐目录" '"plans"' "$(curl -s --max-time 10 "$CORE/api/plans")"
check "GET /api/health 免鉴权可用" "200" "$(status_code "$CORE/api/health")"
check "首页是 text/html" "text/html; charset=utf-8" "$(content_type_of --max-time 10 "$CORE/")"
check "JS 产物是 text/javascript" "text/javascript; charset=utf-8" "$(content_type_of --max-time 10 "$CORE/intro-assets/$(ls "$INTRO_ROOT/intro-assets" | grep -E '\.js$' | head -1)")"

say "3. 大文件穿透（介绍页 8MB 产物）"
asset="$(ls "$INTRO_ROOT/intro-assets" | grep -E '\.js$' | head -1)"
head -c 8388608 /dev/urandom >"$INTRO_ROOT/intro-assets/rehearsal.bin"
expected="$(shasum -a 256 "$INTRO_ROOT/intro-assets/rehearsal.bin" | awk '{print $1}')"
got="$(curl -s --max-time 60 "$CORE/intro-assets/rehearsal.bin" | shasum -a 256 | awk '{print $1}')"
check "8MB 资源经核心逐字节一致" "$expected" "$got"
check "静态资源带长缓存" "public, max-age=31536000, immutable" "$(cache_control_of "$CORE/intro-assets/$asset")"
rm -f "$INTRO_ROOT/intro-assets/rehearsal.bin"

say "4. 功能页下线：介绍页不受影响"
compose stop app >/dev/null
wait_side app False || true
check "功能页被判定下线" "False" "$(side_up app)"
check "导航 /home → 302" "302" "$(status_code -H 'Sec-Fetch-Mode: navigate' "$CORE/home")"
check "跳转目标带原路径" "/under_maintenance?from=%2Fhome" "$(location_of -H 'Sec-Fetch-Mode: navigate' "$CORE/home")"
check "接口 /api/plans → 503" "503" "$(status_code -H 'Sec-Fetch-Mode: cors' -H 'Accept: application/json' "$CORE/api/plans")"
check_contains "接口 503 是 JSON" '"status":"maintenance"' "$(curl -s --max-time 10 -H 'Sec-Fetch-Mode: cors' "$CORE/api/plans")"
check "维护页可打开" "200" "$(status_code "$CORE/under_maintenance")"
check_contains "维护页文案" "我们很快就会回来" "$(curl -s --max-time 10 "$CORE/under_maintenance")"
check "介绍页 / 仍然 200" "200" "$(status_code "$CORE/")"
check "介绍页容器未被波及" "True" "$(side_up intro)"

say "5. 功能页恢复：自动回到可用"
compose start app >/dev/null
wait_side app True || true
check "功能页恢复上线" "True" "$(side_up app)"
check "GET /home 恢复 200" "200" "$(status_code "$CORE/home")"

say "6. 介绍页下线：功能页不受影响"
compose stop intro >/dev/null
wait_side intro False || true
check "介绍页被判定下线" "False" "$(side_up intro)"
check "导航 / → 302" "302" "$(status_code -H 'Sec-Fetch-Mode: navigate' "$CORE/")"
check "GET /home 仍然 200" "200" "$(status_code "$CORE/home")"
check "功能页容器未被波及" "True" "$(side_up app)"
compose start intro >/dev/null
wait_side intro True || true
check "介绍页恢复上线" "True" "$(side_up intro)"
check "GET / 恢复 200" "200" "$(status_code "$CORE/")"

say "7. 计划维护开关（不重启容器）"
touch "$STATE_DIR/app.maintenance"
wait_side app False || true
check "开关生效：功能页判为维护" "False" "$(side_up app)"
check "导航 /home → 302" "302" "$(status_code -H 'Sec-Fetch-Mode: navigate' "$CORE/home")"
rm -f "$STATE_DIR/app.maintenance"
wait_side app True || true
check "撤销开关后恢复" "True" "$(side_up app)"

say "8. 只发布一个宿主端口"
published="$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Ports}}' | tr ',' '\n' | grep -c '0.0.0.0\|127.0.0.1' || true)"
check "本实例发布的端口数为 1" "1" "$published"

if report; then
  exit 0
fi
printf '\n最近的核心日志：\n'
compose logs --tail 30 router
printf '\n最近的功能页日志：\n'
compose logs --tail 30 app
exit 1
