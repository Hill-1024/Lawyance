#!/usr/bin/env bash
# 彩排断言片段：deploy/router/rehearsal.sh（进程版）与 deploy/docker/rehearsal.sh
# （容器版）共用，确保两种拓扑验的是**同一批断言**——否则容器化之后"过没过"就没有
# 可比性了。
#
# 调用方必须先设好：
#   CORE        分流核心基址，如 http://127.0.0.1:18080
#   PYTHON      用来解析 JSON 的解释器（Windows 检出是 .venv/Scripts/python.exe）
#   PROBE_WAIT  等探活翻转的秒数，默认 12
#
# 提供：say / check / check_contains / status_code / location_of / upstream_of /
#       content_type_of / cache_control_of / side_up / wait_side / report
# 计数变量 pass / fail 由本片段维护，调用方在末尾调 report 取结论。

PROBE_WAIT="${PROBE_WAIT:-12}"
pass=0
fail=0

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

# 核心给每个响应打的来源标记：app | intro
upstream_of() { curl -s -o /dev/null -D - --max-time 20 "$@" | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r'; }

# 头字段取值（Content-Type 被当成 octet-stream 时 curl 看不出问题，浏览器却只会下载页面）
header_of() { # header_of <头名> <curl 参数...>
  local name="$1"; shift
  curl -s -o /dev/null -D - --max-time 20 "$@" \
    | awk -v want="$(printf '%s' "$name" | tr 'A-Z' 'a-z')" \
        'tolower($1)==want":"{$1="";sub(/^ /,"");print}' | tr -d '\r'
}

content_type_of() { header_of 'Content-Type' "$@"; }
cache_control_of() { header_of 'Cache-Control' "$@"; }

side_up() { curl -s --max-time 5 "$CORE/__core/status" | "$PYTHON" -c "import json,sys;print(json.load(sys.stdin)['sides']['$1']['up'])" 2>/dev/null || echo unknown; }

wait_side() { # wait_side <side> <True|False>
  local deadline=$((SECONDS + PROBE_WAIT))
  while ((SECONDS < deadline)); do
    [[ "$(side_up "$1")" == "$2" ]] && return 0
    sleep 0.5
  done
  return 1
}

report() { # report  返回非零表示有失败
  say "结果"
  printf '  通过 %d，失败 %d\n' "$pass" "$fail"
  ((fail == 0))
}
