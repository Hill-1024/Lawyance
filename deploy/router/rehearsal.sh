#!/usr/bin/env bash
# 分流核心的本机彩排：起一个隔离的功能页实例、一个介绍页静态服务、一个核心，
# 然后逐条验证「一侧下线不影响另一侧」、维护跳转、接口 503 与恢复。
#
# 用法（本仓库根目录）：
#   deploy/router/rehearsal.sh
#   INTRO_REPO=/srv/lawver-intro CORE_PORT=18080 deploy/router/rehearsal.sh
#   KEEP_RUNNING=1 deploy/router/rehearsal.sh   # 结束时保留进程，便于浏览器查看
#
# 全程使用临时数据目录与 18xxx 端口，不碰线上实例。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CORE_PORT="${CORE_PORT:-18080}"
APP_PORT="${APP_PORT:-18081}"
INTRO_PORT="${INTRO_PORT:-18082}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
INTRO_REPO="${INTRO_REPO:-$(cd "$ROOT/.." && pwd)/lawyance-intro}"
INTRO_ROOT="${INTRO_ROOT:-$INTRO_REPO/current}"
PROBE_WAIT="${PROBE_WAIT:-12}"
CORE="http://127.0.0.1:$CORE_PORT"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/lawver-rehearsal.XXXXXX")"

pass=0
fail=0
app_pid=""
intro_pid=""
core_pid=""

cleanup() {
  if [[ "${KEEP_RUNNING:-0}" == "1" ]]; then
    echo
    echo "保留进程：core=${core_pid:-?} app=${app_pid:-?} intro=${intro_pid:-?}（工作目录 $WORK）"
    echo "  浏览器打开 $CORE/ 与 $CORE/home"
    return
  fi
  [[ -n "$core_pid" ]] && kill "$core_pid" 2>/dev/null
  [[ -n "$app_pid" ]] && kill "$app_pid" 2>/dev/null
  [[ -n "$intro_pid" ]] && kill "$intro_pid" 2>/dev/null
  rm -f "$INTRO_ROOT/intro-assets/rehearsal.bin"
  rm -rf "$WORK"
}
trap cleanup EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
check() { # check <描述> <期望> <实际>
  if [[ "$2" == "$3" ]]; then
    printf '  ok   %s\n' "$1"
    pass=$((pass + 1))
  else
    printf '  FAIL %s\n       期望: %s\n       实际: %s\n' "$1" "$2" "$3"
    fail=$((fail + 1))
  fi
}
check_contains() { # check_contains <描述> <子串> <文本>
  if [[ "$3" == *"$2"* ]]; then
    printf '  ok   %s\n' "$1"
    pass=$((pass + 1))
  else
    printf '  FAIL %s\n       期望包含: %s\n       实际: %s\n' "$1" "$2" "${3:0:200}"
    fail=$((fail + 1))
  fi
}

status_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@"; }
location_of() { curl -s -o /dev/null -D - --max-time 20 "$@" | awk 'tolower($1)=="location:"{print $2}' | tr -d '\r'; }
side_up() { curl -s --max-time 5 "$CORE/__core/status" | "$PYTHON" -c "import json,sys;print(json.load(sys.stdin)['sides']['$1']['up'])" 2>/dev/null || echo unknown; }
wait_side() { # wait_side <side> <True|False>
  local deadline=$((SECONDS + PROBE_WAIT))
  while ((SECONDS < deadline)); do
    [[ "$(side_up "$1")" == "$2" ]] && return 0
    sleep 0.5
  done
  return 1
}
start_app() {
  # API_KEY/BASE_URL 显式指向一个不可达端点：仓库根的 .env 里是生产凭据，而应用会
  # load_dotenv(".env")——不覆盖的话，任何一次误发消息都会真的打到生产模型服务上。
  # 本脚本只验路径分派与维护兜底，不需要模型。
  LAWVER_DATA_DIR="$WORK/data" \
  LAWVER_WORKBENCH_TESTING=1 \
  LAWVER_RELEASE_SYNC_ON_STARTUP=0 \
  SECRET_KEY=rehearsal-secret-rehearsal-secret-32 \
  INITIAL_ADMIN_PASSWORD=rehearsal-admin \
  API_KEY=rehearsal-key \
  BASE_URL=http://127.0.0.1:9/v1 \
  LLM_MODEL=rehearsal-model \
  PORT="$APP_PORT" \
  "$PYTHON" "$ROOT/agent.py" >"$WORK/app.log" 2>&1 &
  app_pid=$!
}
start_intro() {
  "$PYTHON" "$INTRO_REPO/server/serve.py" --root "$INTRO_ROOT" --port "$INTRO_PORT" \
    >"$WORK/intro.log" 2>&1 &
  intro_pid=$!
}

say "0. 前置检查"
for path in "$INTRO_REPO/server/serve.py" "$INTRO_ROOT/index.html"; do
  if [[ -e "$path" ]]; then printf '  ok   %s\n' "$path"; else printf '  FAIL 缺少 %s（先跑介绍页仓的 tools/build.sh）\n' "$path"; exit 2; fi
done

mkdir -p "$WORK/data" "$WORK/state"
cat >"$WORK/config.json" <<JSON
{
  "host": "127.0.0.1",
  "port": $CORE_PORT,
  "app_upstream": "http://127.0.0.1:$APP_PORT",
  "intro_upstream": "http://127.0.0.1:$INTRO_PORT",
  "state_dir": "$WORK/state",
  "probe_interval": 2,
  "probe_timeout": 2,
  "retry_after": 30,
  "log_level": "info"
}
JSON

say "1. 起三件套"
start_app
start_intro
"$PYTHON" "$ROOT/deploy/router/router.py" --config "$WORK/config.json" >"$WORK/core.log" 2>&1 &
core_pid=$!
for _ in $(seq 1 60); do
  [[ "$(status_code "$CORE/__core/status")" == "200" ]] && break
  sleep 0.5
done
check "核心已就绪" "200" "$(status_code "$CORE/__core/status")"
wait_side app True || true
wait_side intro True || true
check "功能页在线" "True" "$(side_up app)"
check "介绍页在线" "True" "$(side_up intro)"

say "2. 路径分派"
check "GET / → 介绍页" "200" "$(status_code "$CORE/")"
check "/ 来自介绍页进程" "intro" "$(curl -s -o /dev/null -D - "$CORE/" | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
check "GET /design → 介绍页" "intro" "$(curl -s -o /dev/null -D - "$CORE/design" | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
check "GET /home → 功能页" "app" "$(curl -s -o /dev/null -D - "$CORE/home" | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
check "GET /api/plans → 功能页" "app" "$(curl -s -o /dev/null -D - "$CORE/api/plans" | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
check_contains "GET /robots.txt 是介绍页的 robots" "Sitemap:" "$(curl -s --max-time 10 "$CORE/robots.txt")"
check_contains "GET /api/plans 返回套餐目录" '"plans"' "$(curl -s --max-time 10 "$CORE/api/plans")"
check "GET /api/health 免鉴权可用" "200" "$(status_code "$CORE/api/health")"
# 内容类型必须逐个对：HTML 被当成 application/octet-stream 时 curl 看不出任何问题，
# 浏览器却只会把页面下载下来——整套界面白屏。
check "首页是 text/html" "text/html; charset=utf-8" "$(curl -s -o /dev/null -D - --max-time 10 "$CORE/" | awk 'tolower($1)=="content-type:"{$1="";sub(/^ +/,"");print}' | tr -d '\r')"
check "JS 产物是 text/javascript" "text/javascript; charset=utf-8" "$(curl -s -o /dev/null -D - --max-time 10 "$CORE/intro-assets/$(ls "$INTRO_ROOT/intro-assets" | grep -E '\.js$' | head -1)" | awk 'tolower($1)=="content-type:"{$1="";sub(/^ +/,"");print}' | tr -d '\r')"

say "3. 大文件穿透（介绍页 8MB 产物）"
asset="$(ls "$INTRO_ROOT/intro-assets" | grep -E '\.js$' | head -1)"
head -c 8388608 /dev/urandom >"$INTRO_ROOT/intro-assets/rehearsal.bin"
expected="$(shasum -a 256 "$INTRO_ROOT/intro-assets/rehearsal.bin" | awk '{print $1}')"
got="$(curl -s --max-time 60 "$CORE/intro-assets/rehearsal.bin" | shasum -a 256 | awk '{print $1}')"
check "8MB 资源经核心逐字节一致" "$expected" "$got"
check "静态资源带长缓存" "public, max-age=31536000, immutable" "$(curl -s -o /dev/null -D - "$CORE/intro-assets/$asset" | awk 'tolower($1)=="cache-control:"{$1="";sub(/^ /,"");print}' | tr -d '\r')"
rm -f "$INTRO_ROOT/intro-assets/rehearsal.bin"

say "4. 功能页下线：介绍页不受影响"
kill "$app_pid" 2>/dev/null
wait_side app False || true
check "功能页被判定下线" "False" "$(side_up app)"
check "导航 /home → 302" "302" "$(status_code -H 'Sec-Fetch-Mode: navigate' "$CORE/home")"
check "跳转目标带原路径" "/under_maintenance?from=%2Fhome" "$(location_of -H 'Sec-Fetch-Mode: navigate' "$CORE/home")"
check "接口 /api/plans → 503" "503" "$(status_code -H 'Sec-Fetch-Mode: cors' -H 'Accept: application/json' "$CORE/api/plans")"
check_contains "接口 503 是 JSON" '"status":"maintenance"' "$(curl -s --max-time 10 -H 'Sec-Fetch-Mode: cors' "$CORE/api/plans")"
check "维护页可打开" "200" "$(status_code "$CORE/under_maintenance")"
check_contains "维护页文案" "我们很快就会回来" "$(curl -s --max-time 10 "$CORE/under_maintenance")"
check "介绍页 / 仍然 200" "200" "$(status_code "$CORE/")"
check "介绍页进程未被波及" "True" "$(side_up intro)"

say "5. 功能页恢复：自动回到可用"
start_app
wait_side app True || true
check "功能页恢复上线" "True" "$(side_up app)"
check "GET /home 恢复 200" "200" "$(status_code "$CORE/home")"

say "6. 介绍页下线：功能页不受影响"
kill "$intro_pid" 2>/dev/null
wait_side intro False || true
check "介绍页被判定下线" "False" "$(side_up intro)"
check "导航 / → 302" "302" "$(status_code -H 'Sec-Fetch-Mode: navigate' "$CORE/")"
check "GET /home 仍然 200" "200" "$(status_code "$CORE/home")"
check "功能页进程未被波及" "True" "$(side_up app)"
start_intro
wait_side intro True || true
check "介绍页恢复上线" "True" "$(side_up intro)"
check "GET / 恢复 200" "200" "$(status_code "$CORE/")"

say "7. 计划维护开关（不杀进程）"
touch "$WORK/state/app.maintenance"
wait_side app False || true
check "开关生效：功能页判为维护" "False" "$(side_up app)"
check "导航 /home → 302" "302" "$(status_code -H 'Sec-Fetch-Mode: navigate' "$CORE/home")"
rm -f "$WORK/state/app.maintenance"
wait_side app True || true
check "撤销开关后恢复" "True" "$(side_up app)"

say "结果"
printf '  通过 %d，失败 %d\n' "$pass" "$fail"
if ((fail > 0)); then
  printf '\n最近的核心日志：\n'
  tail -20 "$WORK/core.log"
  printf '\n最近的功能页日志：\n'
  tail -20 "$WORK/app.log"
  exit 1
fi
