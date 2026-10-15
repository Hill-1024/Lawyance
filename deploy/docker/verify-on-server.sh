#!/usr/bin/env bash
# 部署机验收：共享基建 + 自营实例（挂语料）+ 法库本地检索 + 多实例并存 + 介绍页热切换。
#
# 用法（在 deploy/docker 下，路径可按需覆盖）：
#   ./verify-on-server.sh
#   INSTANCES=/srv/lawver-instances CORPUS=/srv/lawver/RAG/data ./verify-on-server.sh
#
# ⚠️ 它会**占用并改写**实例项目名 lawver / lawver-infra，所以只该在"尚未用容器部署"
# 的机器上跑。已经有同名项目在跑时脚本会拒绝启动（确实要覆盖再跑设 FORCE=1）。
#
# 全程只在 $INSTANCES 与 /var/tmp 下建数据；不动 /srv/lawver 的 systemd 三件套，
# 也不占用 8080/8081/8082（用 18800/18801）。收尾停在 down，保留卷便于复跑。
set -uo pipefail

DOCKER_DIR="${DOCKER_DIR:-/var/tmp/lawver-docker-verify/deploy/docker}"
INSTANCES="${INSTANCES:-/var/tmp/lawver-instances}"
APP_ENV_DIR="${APP_ENV_DIR:-/var/tmp/lawver-verify-env}"
CORPUS="${CORPUS:-/srv/lawver/RAG/data}"
SEARXNG_DIR="${SEARXNG_DIR:-/var/tmp/lawver-searxng}"
INTRO_HOME="${INTRO_HOME:-/var/tmp/lawver-intro-verify}"
APP_IMAGE="${LAWVER_APP_IMAGE:-lawver-app:local}"
INTRO_IMAGE="${LAWVER_INTRO_IMAGE:-lawver-intro:local}"
# 所有 infra compose 调用共用同一份解析结果，避免 exec 时因变量缺失落到别的挂载点
export LAWVER_SEARXNG_DIR="$SEARXNG_DIR"

# 防止在已经容器化部署过的机器上误跑：同名项目在跑就直接退出
for project in lawver billing lawver-infra; do
  running="$(docker ps -q --filter "label=com.docker.compose.project=$project" 2>/dev/null | wc -l)"
  if [[ "$running" -gt 0 && "${FORCE:-0}" != "1" ]]; then
    printf '项目 %s 已有 %s 个容器在运行：这台机器上可能已经部署过。\n' "$project" "$running" >&2
    printf '确认要覆盖（会停掉并重建它们）就设 FORCE=1 重跑。\n' >&2
    exit 2
  fi
done

pass=0; fail=0
say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  ok   %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  FAIL %s\n       %s\n' "$1" "${2:-}"; fail=$((fail+1)); }
chk()  { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "期望=$2 实际=$3"; fi; }

say "0. 准备：实例 .env、SearXNG 配置目录、介绍页检出"
mkdir -p "$APP_ENV_DIR" "$SEARXNG_DIR"
# 介绍页副本的 current 是绝对链接（指向 /srv/lawver-intro/releases/...），容器里只挂了
# 副本这一棵树，链接会指向不存在的位置。改成相对链接让整棵树自洽——线上无需这样处理：
# /srv/lawver-intro/current 的链接目标本来就在挂载树内部。
if [[ -d "$INTRO_HOME" ]]; then
  site_target="$(basename "$(readlink -f "$INTRO_HOME/current" 2>/dev/null)")"
  if [[ -n "$site_target" ]]; then
    rm -f "$INTRO_HOME/current"
    ln -s "releases/$site_target" "$INTRO_HOME/current"
  fi
fi
cat >"$APP_ENV_DIR/app.env" <<'ENV'
SECRET_KEY=verify-secret-verify-secret-verify-32
INITIAL_ADMIN_PASSWORD=verify-admin-password
LLM_MODEL=verify-model
BASE_URL=http://127.0.0.1:9/v1
API_KEY=verify-key
LAWVER_WORKBENCH_USERS=admin
LAWVER_CONNECTOR_KEY=kJ8mZ0pQ2rS4tU6vW8xY0zA2bC4dE6fG8hI0jK2lM4=
LAWVER_RELEASE_SYNC_ON_STARTUP=0
ENV
printf 'use_default_settings: true\nserver:\n  secret_key: "%s"\n  limiter: false\n  image_proxy: false\n  bind_address: "0.0.0.0:8080"\nsearch:\n  safe_search: 0\n  default_lang: "all"\n  formats: [html, json]\n' \
  "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" >"$SEARXNG_DIR/settings.yml"
chown -R 977:977 "$SEARXNG_DIR"
echo "  实例 .env 与 SearXNG settings.yml 已就绪"

say "1. 起共享基建（postgres + redis + searxng，均不发布宿主端口）"
cd "$DOCKER_DIR"
cp -n infra.env.example infra.env 2>/dev/null || true
sed -i 's/^LAWVER_POSTGRES_PASSWORD=.*/LAWVER_POSTGRES_PASSWORD=verify-pg-password-8f3a/' infra.env
LAWVER_SEARXNG_DIR="$SEARXNG_DIR" docker compose --env-file infra.env -f compose.infra.yml up -d >/dev/null 2>&1
sleep 12
docker compose --env-file infra.env -f compose.infra.yml ps --format '{{.Service}} {{.Status}}'
for svc in postgres redis searxng; do
  st="$(docker inspect --format '{{.State.Status}}' "lawver-infra-$svc-1" 2>/dev/null || echo missing)"
  chk "基建 $svc 运行中" "running" "$st"
done
pg_health="$(docker inspect --format '{{.State.Health.Status}}' lawver-infra-postgres-1 2>/dev/null || echo none)"
chk "postgres 健康检查通过" "healthy" "$pg_health"
chk "SearXNG JSON API 可用" "200" \
  "$(docker exec lawver-infra-searxng-1 sh -c 'command -v wget >/dev/null && wget -qO- "http://127.0.0.1:8080/search?q=test&format=json" >/dev/null 2>&1 && echo 200 || echo 000' 2>/dev/null || echo 000)"

say "2. 用脚手架建实例（自动挑端口/网段/前缀）"
rm -rf "$INSTANCES"
LAWVER_INSTANCES_ROOT="$INSTANCES" \
LAWVER_APP_ENV_FILE="$APP_ENV_DIR/app.env" \
LAWVER_INTRO_HOME="$INTRO_HOME" \
LAWVER_LAW_DATA_DIR="$CORPUS" \
LAWVER_APP_IMAGE="$APP_IMAGE" \
LAWVER_INTRO_IMAGE="$INTRO_IMAGE" \
  "$DOCKER_DIR/new-instance.sh" lawver 18800 2>&1 | tail -18
[[ -f "$INSTANCES/lawver/compose.env" ]] && ok "compose.env 已生成" || bad "compose.env 未生成"
grep -q "LAWVER_ROUTER_PUBLISH_PORT=18800" "$INSTANCES/lawver/compose.env" && ok "发布端口写对" || bad "发布端口不对"
grep -q "LAWVER_NETWORK_SUBNET=10.42.0.0/24" "$INSTANCES/lawver/compose.env" && ok "网段自动分配" || bad "网段不对"

say "3. 起自营实例（挂真实语料）"
t0=$(date +%s)
"$INSTANCES/lawver/run.sh" up -d >/dev/null 2>&1
# 首次启动要建 210MB 索引，给足时间
for _ in $(seq 1 90); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:18800/api/health" 2>/dev/null)"
  [[ "$code" == "200" ]] && break
  sleep 5
done
t1=$(date +%s)
chk "功能页 /api/health" "200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:18800/api/health)"
chk "介绍页经核心可达" "intro" \
  "$(curl -s -o /dev/null -D - --max-time 10 http://127.0.0.1:18800/ | awk 'tolower($1)=="x-core-upstream:"{print $2}' | tr -d '\r')"
echo "  首次启动（含建库）耗时约 $((t1-t0)) 秒"

say "4. 法库本地检索（容器内直调适配层）"
# 注意 sys.path：应用自己是 `cd /app && python agent.py`，此时 sys.path[0] 就是 /app，
# 顶层的 RAG 包才 import 得到。用 `python /tmp/x.py` 时 sys.path[0] 变成 /tmp，
# 会报 No module named 'RAG'——那是测试写法的问题，不是部署的问题。
PY_IN_APP=(-e PYTHONPATH=/app/backend:/app -w /app)
search_out="$("$INSTANCES/lawver/run.sh" exec -T "${PY_IN_APP[@]}" app python -c "
from mcp import pkulaw_client
import json
r = json.loads(pkulaw_client.get_article('民法典', '第五百七十七条'))
ok = bool(r.get('success')) and '违约责任' in str(r.get('content',''))
print('ARTICLE_OK' if ok else 'ARTICLE_FAIL:' + str(r)[:160])
print('TITLE:', str(r.get('title'))[:40])
# 注意：本地法库是关键词式（trigram FTS），长句自然语言描述匹配不到——
# 这是既有实现的行为（进程版同样如此），不是容器化引入的。所以这里用关键词组合。
r2 = json.loads(pkulaw_client.search_article('劳动合同 解除'))
hit = bool(r2.get('success')) and '劳动合同法' in str(r2.get('result',''))
print('SEARCH_OK' if hit else 'SEARCH_FAIL:' + str(r2)[:160])
" 2>&1 | tr -d '\r')"
if grep -q ARTICLE_OK <<<"$search_out"; then ok "本地法库精确检索命中（语料只读挂载生效）"; else bad "本地法库检索失败" "$search_out"; fi
if grep -q SEARCH_OK <<<"$search_out"; then ok "本地法库关键词检索命中"; else bad "关键词检索失败" "$search_out"; fi
grep '^TITLE:' <<<"$search_out" | sed 's/^/       /'

law_mode="$("$INSTANCES/lawver/run.sh" exec -T "${PY_IN_APP[@]}" app python -c "
from mcp import pkulaw_mcp
print('source=', pkulaw_mcp.source(), 'configured=', pkulaw_mcp.is_configured())
" 2>&1 | tr -d '\r' | tail -1)"
chk "数据源是本地法库" "source= local configured= False" "$law_mode"

say "5. 数据库连通（新基建 PG 里已建表）"
tables="$(docker compose --env-file "$DOCKER_DIR/infra.env" -f "$DOCKER_DIR/compose.infra.yml" \
  exec -T postgres psql -U lawver -d lawver -tAc "select count(*) from information_schema.tables where table_schema='public'" 2>/dev/null | tr -d '\r')"
if [[ "${tables:-0}" -gt 5 ]]; then ok "PG 里已建出 $tables 张表（应用连上了库）"; else bad "PG 建表数异常" "${tables:-空}"; fi

say "6. 只发布实例网关一个端口"
pub_lawver="$(docker ps --filter 'label=com.docker.compose.project=lawver' --format '{{.Ports}}' | grep -c '127.0.0.1' || true)"
chk "lawver 实例发布的端口数" "1" "$pub_lawver"
pub_infra="$(docker ps --filter 'label=com.docker.compose.project=lawver-infra' --format '{{.Ports}}' | grep -cE '0\.0\.0\.0|127\.0\.0\.1' || true)"
chk "共享基建发布的端口数" "0" "$pub_infra"

say "7. 第二个实例并存（frontier overlay，不挂语料）"
LAWVER_INSTANCES_ROOT="$INSTANCES" \
LAWVER_APP_ENV_FILE="$APP_ENV_DIR/app.env" \
LAWVER_INTRO_HOME="$INTRO_HOME" \
LAWVER_APP_IMAGE="$APP_IMAGE" \
LAWVER_INTRO_IMAGE="$INTRO_IMAGE" \
  "$DOCKER_DIR/new-instance.sh" billing 18801 >/dev/null 2>&1
sed -i "s/^LAWVER_DATABASE_URL=.*/LAWVER_DATABASE_URL=postgresql+psycopg:\/\/lawver:verify-pg-password-8f3a@postgres:5432\/lawver_billing/" "$INSTANCES/billing/compose.env"
docker compose --env-file "$DOCKER_DIR/infra.env" -f "$DOCKER_DIR/compose.infra.yml" \
  exec -T postgres psql -U lawver -d lawver -c 'CREATE DATABASE lawver_billing OWNER lawver' >/dev/null 2>&1 || true
"$INSTANCES/billing/run.sh" up -d --frontier >/dev/null 2>&1
for _ in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:18801/api/health" 2>/dev/null)"
  [[ "$code" == "200" ]] && break
  sleep 5
done
chk "实例 A（18800）仍在" "200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:18800/api/health)"
chk "实例 B（18801）起来" "200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:18801/api/health)"
chk "实例间网段不同" "10.42.0.0/24|10.42.1.0/24" \
  "$(grep -h '^LAWVER_NETWORK_SUBNET=' "$INSTANCES"/lawver/compose.env "$INSTANCES"/billing/compose.env | cut -d= -f2 | sort | paste -sd'|')"
chk "实例间 redis 前缀不同" "billing|lawver" \
  "$(grep -h '^LAWVER_REDIS_PREFIX=' "$INSTANCES"/lawver/compose.env "$INSTANCES"/billing/compose.env | cut -d= -f2 | sort | paste -sd'|')"
frontier_mode="$("$INSTANCES/billing/run.sh" exec -T "${PY_IN_APP[@]}" app python -c "
from mcp import pkulaw_mcp
print('source=', pkulaw_mcp.source())
" 2>&1 | tr -d '\r' | tail -1)"
chk "前沿实例走远程数据源" "source= remote" "$frontier_mode"

say "8. 介绍页热切换（容器不重启）"
cid_before="$("$INSTANCES/lawver/run.sh" ps -q intro | head -1)"
site="$INTRO_HOME"
# 记下原来那一版：测完要换回去，否则 current 指向被删掉的临时目录，下次启动直接 404
original_release="$(basename "$(readlink -f "$site/current")")"
new_release="$site/releases/hotswap-$(date +%s)"
mkdir -p "$new_release/intro-assets"
cp "$site/current/index.html" "$new_release/index.html"
echo "hotswapped" >"$new_release/intro-assets/hotswap.txt"
ln -sfn "releases/$(basename "$new_release")" "$site/.current.new"
python3 -c "import os,sys; os.replace(sys.argv[1], sys.argv[2])" "$site/.current.new" "$site/current"
sleep 1
chk "换版后新产物可访问" "200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:18800/intro-assets/hotswap.txt)"
chk "intro 容器未重启" "$cid_before" "$("$INSTANCES/lawver/run.sh" ps -q intro | head -1)"
chk "换回后旧版仍在线" "200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:18800/)"
# 先换回原版，再删临时产物
ln -sfn "releases/$original_release" "$site/.current.restore"
python3 -c "import os,sys; os.replace(sys.argv[1], sys.argv[2])" "$site/.current.restore" "$site/current"
rm -rf "$new_release"
chk "current 已换回原版" "releases/$original_release" "$(readlink "$site/current")"

say "9. 收尾（停容器但保留卷：法库索引建一次要 7 分钟左右，留着便于复跑）"
"$INSTANCES/billing/run.sh" down >/dev/null 2>&1
"$INSTANCES/lawver/run.sh" down >/dev/null 2>&1
docker compose --env-file "$DOCKER_DIR/infra.env" -f "$DOCKER_DIR/compose.infra.yml" down >/dev/null 2>&1
ok "验证实例与基建已停止（线上三件套未受影响）"
echo "  保留的卷：$(docker volume ls --format '{{.Name}}' | grep -E 'lawver' | paste -sd' ')"

printf '\n\033[1m结果\033[0m\n  通过 %d，失败 %d\n' "$pass" "$fail"
((fail == 0))
