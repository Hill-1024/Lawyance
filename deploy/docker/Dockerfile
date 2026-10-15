# 功能页（lawver-app）与分流核心（lawver-router）共用同一个镜像。
#
# 为什么不是两个镜像：核心只依赖 starlette/httpx/uvicorn，看着可以单独做个瘦镜像，
# 但那三个包已经在应用的依赖集里——单独装就得再维护一份版本来源，反而违背"依赖只认
# uv.lock"的约定；而且两个镜像的体量差不出量级（大头是 Python 依赖），多一个镜像只多一条
# 构建/推送/拉取链路。这里改成**一个镜像、两个 command**，核心服务用
# `command: ["python", "deploy/router/router.py"]` 覆盖启动命令（见 compose.yml）。
#
# 关键约束：
#   · `pnpm exec vite build` 而不是 `pnpm run build`：后者先跑 sync-android-config，
#     那是给 Capacitor 写 android/ 用的，Web 部署不需要，镜像里也不拷 android/。
#   · 语料不入镜像（.dockerignore 排除 RAG/data），RAG/cache 走命名卷。
#   · 容器内必须 LAWVER_HOST=0.0.0.0（systemd 那份 127.0.0.1 会不可达）。

# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.13-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim

########## 1. 前端产物 ##########
FROM ${NODE_IMAGE} AS web
WORKDIR /src
# 先只拷清单装依赖，源码改动不会打掉这一层缓存
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# 与 android-release.yml 同一套安装口径（锁定、不跑 postinstall）
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate \
 && pnpm install --frozen-lockfile --ignore-scripts
COPY vite.config.ts tsconfig.json ./
COPY frontend ./frontend
RUN pnpm exec vite build

########## 2. Python 依赖 ##########
FROM ${PYTHON_IMAGE} AS deps
# uv 官方镜像，版本钉死（不用 ARG 做 --from 取值：那里的变量展开不如 FROM 里可靠）
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
# 依赖装进独立 venv，运行镜像整份拷过去，避免把构建期的 pip/uv 留进运行镜像
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
# --frozen：绝不改动锁文件（锁文件只随 git 更新）；--no-dev：运行镜像不带 pytest
RUN uv sync --frozen --no-dev --no-install-project

########## 3. 运行镜像 ##########
FROM ${PYTHON_IMAGE} AS runtime

# UID/GID 要与宿主持久化目录的属主一致，否则 data/、TEMP/、Result/ 写不进去。
# 注意部署机上的 lawver 用户**不是** 1000（实测 996/993），所以默认值只是兜底：
# 用 deploy/docker/build.sh 构建时它会自动取 `id -u lawver`，或显式传
# --build-arg APP_UID=996 --build-arg APP_GID=993。
ARG APP_UID=1000
ARG APP_GID=1000

# postgresql-client：备份链路（python -m workbench.maintenance backup 内部调 pg_dump）
# 需要它。基建容器不再往宿主发布 5432，所以备份只能在容器内执行。
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${APP_GID}" lawver \
 && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin lawver

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LAWVER_HOST=0.0.0.0 \
    LAWVER_DATA_DIR=/app/data

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
# 代码进镜像（多实例共享同一份镜像，不再需要每实例一套源码树）
COPY . .
COPY --from=web /src/dist ./dist

# 可写目录先在镜像里建好并交给 lawver：挂命名卷时 Docker 会把这里的属主带进新卷
RUN mkdir -p /app/data /app/TEMP /app/Result /app/RAG/cache \
 && chown -R lawver:lawver /app/data /app/TEMP /app/Result /app/RAG/cache

USER lawver

# 8081 功能页 / 8080 分流核心：两个 port 都声明，实际由 command 决定监听哪个
EXPOSE 8080 8081

# 默认起功能页；核心服务在 compose 里覆盖 command
CMD ["python", "agent.py"]
