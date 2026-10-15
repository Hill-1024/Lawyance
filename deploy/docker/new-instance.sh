#!/usr/bin/env bash
# 新建一个实例的脚手架：挑不冲突的端口与网段、建好目录、生成 compose.env 与 run.sh。
#
# 用法：
#   deploy/docker/new-instance.sh <实例名> [宿主端口]
#
# 例：
#   deploy/docker/new-instance.sh            # 列出现有实例
#   deploy/docker/new-instance.sh billing    # 自动挑端口与网段
#   deploy/docker/new-instance.sh billing 8081
#
# 为什么需要它：一台机器上跑多个实例时，宿主发布的端口、各实例的 docker 网段、
# 共享 Redis 的前缀三者都必须互不相同——手抄三样东西迟早会重。这里把它们一次性
# 校验并写进实例的 compose.env。
#
# 全程只读地探测现状 + 在实例目录里创建文件；不改动任何已有实例。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANCES_ROOT="${LAWVER_INSTANCES_ROOT:-/srv/lawver-instances}"
# 容器内运行用户必须与宿主持久化目录的属主一致，否则应用在 import 期就会
# os.chmod("/app/data") 失败并崩溃重启（[Errno 1] Operation not permitted），
# 分流核心也读不了维护开关目录。**不问镜像要 uid 就会猜错**——部署机上 lawver
# 是 996，不是 1000。顺序：显式变量 → 本地镜像里的实际用户 → lawver 用户 → 1000。
APP_UID="${LAWVER_APP_UID:-}"
APP_GID="${LAWVER_APP_GID:-}"
if [[ -z "$APP_UID" || -z "$APP_GID" ]]; then
  app_image="${LAWVER_APP_IMAGE:-ghcr.io/hill-1024/lawver-app:latest}"
  if docker image inspect "$app_image" >/dev/null 2>&1; then
    APP_UID="${APP_UID:-$(docker run --rm --entrypoint id "$app_image" -u 2>/dev/null)}"
    APP_GID="${APP_GID:-$(docker run --rm --entrypoint id "$app_image" -g 2>/dev/null)}"
  fi
fi
APP_UID="${APP_UID:-$(id -u lawver 2>/dev/null || echo 1000)}"
APP_GID="${APP_GID:-$(id -g lawver 2>/dev/null || echo 1000)}"
# 网段候选：10.42.<n>.0/24，n 从 0 试到 255。避开 docker 默认地址池
# （172.17–172.31），撞上别人项目的概率最低。
SUBNET_TEMPLATE="${LAWVER_SUBNET_TEMPLATE:-10.42.%d.0/24}"
# 端口候选：从 8080 起往上找。容器内部的 8080/8081/8082 不受影响，
# 这里挑的只是宿主发布端口。
PORT_START="${LAWVER_PORT_START:-8080}"

die() { printf '错误：%s\n' "$1" >&2; exit 1; }
say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

list_instances() {
  [[ -d "$INSTANCES_ROOT" ]] || return 0
  local found=0
  for dir in "$INSTANCES_ROOT"/*/; do
    [[ -f "${dir}compose.env" ]] || continue
    found=1
    local name port subnet prefix
    name="$(basename "$dir")"
    port="$(sed -n 's/^LAWVER_ROUTER_PUBLISH_PORT=//p' "${dir}compose.env" | head -1)"
    subnet="$(sed -n 's/^LAWVER_NETWORK_SUBNET=//p' "${dir}compose.env" | head -1)"
    prefix="$(sed -n 's/^LAWVER_REDIS_PREFIX=//p' "${dir}compose.env" | head -1)"
    printf '  %-16s 端口 %-6s 网段 %-16s redis 前缀 %s\n' "$name" "${port:-?}" "${subnet:-?}" "${prefix:-?}"
  done
  ((found)) || printf '  （%s 下还没有实例）\n' "$INSTANCES_ROOT"
}

[[ $# -ge 1 ]] || { say "现有实例"; list_instances; printf '\n用法：%s <实例名> [宿主端口]\n' "$(basename "$0")"; exit 0; }

NAME="$1"
REQUESTED_PORT="${2:-}"

[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]] || die "实例名只能是小写字母、数字与连字符（≤31 字符），收到：$NAME"
[[ "$NAME" != "infra" ]] || die "infra 是共享基建保留名"
[[ -z "$REQUESTED_PORT" || "$REQUESTED_PORT" =~ ^[0-9]+$ ]] || die "端口必须是数字：$REQUESTED_PORT"

INSTANCE_DIR="$INSTANCES_ROOT/$NAME"
[[ -e "$INSTANCE_DIR" ]] && die "实例目录已存在：$INSTANCE_DIR（先删掉或换个名字）"

command -v docker >/dev/null 2>&1 || die "需要 docker"

# ── 收集现状：已被别的实例占用的端口/网段/前缀 ─────────────────────────────
used_ports=()
used_subnets=()
used_prefixes=()
if [[ -d "$INSTANCES_ROOT" ]]; then
  while IFS= read -r env_file; do
    p="$(sed -n 's/^LAWVER_ROUTER_PUBLISH_PORT=//p' "$env_file" | head -1)"
    s="$(sed -n 's/^LAWVER_NETWORK_SUBNET=//p' "$env_file" | head -1)"
    r="$(sed -n 's/^LAWVER_REDIS_PREFIX=//p' "$env_file" | head -1)"
    [[ -n "$p" ]] && used_ports+=("$p")
    [[ -n "$s" ]] && used_subnets+=("$s")
    [[ -n "$r" ]] && used_prefixes+=("$r")
  done < <(find "$INSTANCES_ROOT" -mindepth 2 -maxdepth 2 -name compose.env 2>/dev/null | sort)
fi

# docker 里已存在的网段（别的项目、别的 compose 都算，避免 ipam 冲突起不来）
docker_subnets="$(docker network ls --format '{{.Name}}' 2>/dev/null \
  | while read -r net; do
      docker network inspect "$net" --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null
    done | tr ' ' '\n' | grep -E '^[0-9]' || true)"

port_free_on_host() { # <port>  宿主上没有监听则为真
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    # 解析本地地址列：127.0.0.1:8080 / [::]:8080 / *:8080 都能匹配上
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$"; then
      return 1
    fi
  elif (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    return 1
  fi
  return 0
}

port_claimed_by_instance() { # <port>
  local candidate="$1" p
  for p in ${used_ports+"${used_ports[@]}"}; do
    [[ "$p" == "$candidate" ]] && return 0
  done
  return 1
}

subnet_overlaps() { # <cidr>  与现有 docker 网段或其它实例网段重叠则为真
  local candidate="$1" all
  all="$(printf '%s\n' ${used_subnets+"${used_subnets[@]}"} ${docker_subnets})"
  [[ -n "${all//[[:space:]]/}" ]] || return 1
  python3 - "$candidate" "$all" <<'PY'
import ipaddress, sys

candidate = ipaddress.ip_network(sys.argv[1], strict=False)
for token in sys.argv[2].split():
    try:
        other = ipaddress.ip_network(token, strict=False)
    except ValueError:
        continue
    if candidate.overlaps(other):
        sys.exit(0)
sys.exit(1)
PY
}

# ── 挑宿主端口 ─────────────────────────────────────────────────────────────
if [[ -n "$REQUESTED_PORT" ]]; then
  PORT="$REQUESTED_PORT"
  port_claimed_by_instance "$PORT" && die "端口 $PORT 已被本机另一个实例占用（见上面列表）"
  port_free_on_host "$PORT" || die "端口 $PORT 在宿主上已被占用"
else
  PORT=""
  for ((p = PORT_START; p < PORT_START + 200; p++)); do
    port_claimed_by_instance "$p" && continue
    port_free_on_host "$p" || continue
    PORT="$p"
    break
  done
  [[ -n "$PORT" ]] || die "从 $PORT_START 起没找到空闲端口，请显式指定"
fi

# ── 挑实例网段 ─────────────────────────────────────────────────────────────
SUBNET=""
for n in $(seq 0 255); do
  # shellcheck disable=SC2059
  candidate="$(printf "$SUBNET_TEMPLATE" "$n")"
  if ! subnet_overlaps "$candidate"; then
    SUBNET="$candidate"
    break
  fi
done
[[ -n "$SUBNET" ]] || die "10.42.0.0/24–10.42.255.0/24 都被占用了，设置 LAWVER_SUBNET_TEMPLATE 换一段"

# ── 挑 Redis 前缀 ──────────────────────────────────────────────────────────
PREFIX="$NAME"
for p in ${used_prefixes+"${used_prefixes[@]}"}; do
  [[ "$p" == "$PREFIX" ]] && die "redis 前缀 $PREFIX 已被另一个实例占用"
done

# ── 建目录 ─────────────────────────────────────────────────────────────────
DATA_ROOT="$INSTANCE_DIR/data"
STATE_DIR="$INSTANCE_DIR/state/router"
mkdir -p "$DATA_ROOT"/{data,TEMP,Result} "$STATE_DIR"

# 以 root 运行时装好属主：容器内以镜像里的用户跑，宿主目录属主不对就写不进去——
# 症状是应用在 import 期就 os.chmod("/app/data") 失败并崩溃重启（[Errno 1]）。
if [[ "$(id -u)" == "0" ]]; then
  chown -R "$APP_UID:$APP_GID" "$DATA_ROOT" "$STATE_DIR"
  chmod 750 "$DATA_ROOT" "$STATE_DIR"
else
  printf '注意：当前不是 root，请确认 %s 的属主是容器内用户（uid %s）：\n      sudo chown -R %s:%s %s\n' \
    "$DATA_ROOT" "$APP_UID" "$APP_UID" "$APP_GID" "$INSTANCE_DIR" >&2
fi

# ── 写 compose.env ─────────────────────────────────────────────────────────
APP_ENV_FILE="${LAWVER_APP_ENV_FILE:-/srv/lawver/.env}"
INTRO_HOME="${LAWVER_INTRO_HOME:-/srv/lawver-intro}"
LAW_DATA_DIR="${LAWVER_LAW_DATA_DIR:-/srv/lawver/RAG/data}"

# 数据库口令直接继承共享基建那份（infra.env），避免在两处各写一个明文口令后
# 忘同步——实例连不上库的典型症状就是"改了口令只改了一边"。
PG_PASSWORD="REPLACE_WITH_STRONG_PASSWORD"
if [[ -f "$HERE/infra.env" ]]; then
  found="$(sed -n 's/^LAWVER_POSTGRES_PASSWORD=//p' "$HERE/infra.env" | head -1)"
  [[ -n "$found" ]] && PG_PASSWORD="$found"
else
  printf '提示：%s/infra.env 还不存在，compose.env 里的数据库口令先留占位符，起基建后记得同步。\n' "$HERE" >&2
fi

cat >"$INSTANCE_DIR/compose.env" <<ENV
# 由 new-instance.sh 生成于 $(date -Iseconds)。改完记得同步 run.sh 的用途说明。
# 应用业务配置在 $APP_ENV_FILE，与本文件无关。

COMPOSE_PROJECT_NAME=$NAME

# 对外唯一端口（隧道指向这里）
LAWVER_ROUTER_PUBLISH_PORT=$PORT
LAWVER_ROUTER_PUBLISH_HOST=127.0.0.1

# 实例网段：同一值喂给 LAWVER_TRUSTED_PROXY_CIDRS，保证核心落在可信段内
LAWVER_NETWORK_SUBNET=$SUBNET

# 挂载路径
LAWVER_DATA_HOST_DIR=$DATA_ROOT
LAWVER_APP_ENV_FILE=$APP_ENV_FILE
LAWVER_INTRO_HOME=$INTRO_HOME
LAWVER_ROUTER_STATE_DIR=$STATE_DIR

# 共享基建（服务名由 lawver-infra 网络解析）
LAWVER_DATABASE_URL=postgresql+psycopg://lawver:${PG_PASSWORD}@postgres:5432/lawver
LAWVER_REDIS_URL=redis://redis:6379/0
SEARXNG_BASE_URL=http://searxng:8080/

# 共享 Redis 的前缀：每实例必须不同
LAWVER_REDIS_PREFIX=$PREFIX

# 镜像：默认拉 GHCR 上的版本化镜像（2B 交付就是这种形态，客户机上没有源码）。
# 本地构建过的话改成 lawver-app:local / lawver-intro:local，免得 compose 去拉私有仓库。
LAWVER_APP_IMAGE=${LAWVER_APP_IMAGE:-ghcr.io/hill-1024/lawver-app:latest}
LAWVER_INTRO_IMAGE=${LAWVER_INTRO_IMAGE:-ghcr.io/hill-1024/lawver-intro:latest}

# self-hosted overlay 用（frontier 实例不挂语料，改用 compose.frontier.yml）
LAWVER_LAW_DATA_DIR=$LAW_DATA_DIR
ENV
chmod 600 "$INSTANCE_DIR/compose.env"

# ── 写 run.sh ──────────────────────────────────────────────────────────────
cat >"$INSTANCE_DIR/run.sh" <<RUN
#!/usr/bin/env bash
# 实例 $NAME 的起停入口。等价于在 $HERE 下：
#   docker compose --env-file compose.env -f $HERE/compose.yml \\
#     [-f $HERE/compose.self-hosted.yml | -f $HERE/compose.frontier.yml] "\$@"
#
# 用法：
#   ./run.sh up -d            自营实例（挂语料，本地法库）
#   ./run.sh up -d --frontier 前沿实例（不带语料，远程法库）
#   ./run.sh ps / logs -f app / down
set -euo pipefail
HERE_DOCKER=$HERE
INSTANCE_DIR=\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)

overlays=()
args=()
for arg in "\$@"; do
  if [[ "\$arg" == "--frontier" ]]; then
    overlays=(-f "\$HERE_DOCKER/compose.frontier.yml")
  elif [[ "\$arg" == "--self-hosted" ]]; then
    overlays=(-f "\$HERE_DOCKER/compose.self-hosted.yml")
  else
    args+=("\$arg")
  fi
done
if [[ \${#overlays[@]} -eq 0 ]]; then
  overlays=(-f "\$HERE_DOCKER/compose.self-hosted.yml")
fi

cd "\$INSTANCE_DIR"
exec docker compose --env-file compose.env -f "\$HERE_DOCKER/compose.yml" "\${overlays[@]}" "\${args[@]}"
RUN
chmod +x "$INSTANCE_DIR/run.sh"

say "实例 $NAME 已就绪"
cat <<EOF
  目录      $INSTANCE_DIR
  发布端口  $PORT        ← 隧道/反代指向 127.0.0.1:$PORT
  实例网段  $SUBNET
  redis 前缀 $PREFIX
  数据根    $DATA_ROOT
  维护开关  $STATE_DIR（touch app.maintenance / intro.maintenance）

下一步：
  1. 先把共享基建起起来（若还没起）：
       cd $HERE && cp -n infra.env.example infra.env && 改口令
       docker compose --env-file infra.env -f compose.infra.yml up -d
  2. 确认 $INSTANCE_DIR/compose.env 里的数据库口令与 infra.env 一致。
  3. 起实例：
       $INSTANCE_DIR/run.sh up -d
  4. 验收：
       curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:$PORT/__core/status
EOF
