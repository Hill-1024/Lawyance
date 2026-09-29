# 分流核心（deploy/router）

一台机器上两个后端的唯一入口，监听**稳定端口 8080**：隧道指向这里，之后功能页与介绍页怎么重启换代，入口配置都不用动。

```
lawver.dev / global.lawver.dev
  → 隧道 → 127.0.0.1:8080  分流核心（本目录）
       ├─ /、/design、/download、/pricing、/robots.txt、/sitemap.xml、/intro-assets/*  → 介绍页进程 8082
       ├─ /under_maintenance、/__core/*                                            → 核心自答
       └─ 其余（/home、/login、/settings/*、/admin、/business、/court/*、/project/*、
          /conversation/*、/api/*、/sw.js、/manifest.webmanifest…）                  → 功能页进程 8081
```

两台机器各跑一份（`lawver.dev` 国内、`global.lawver.dev` 海外）：核心代码与配置相同，差异只有主机名与数据源。跨机分流由 DNS/隧道按主机名完成，核心只关心本机路径。

## 跑起来

```bash
# 本机彩排
.venv/bin/python deploy/router/router.py --config deploy/router/config.example.json
# 只探活一次并打印状态
.venv/bin/python deploy/router/router.py --config deploy/router/config.example.json --check
```

常驻：`systemd/lawver-router.service`（部署机）、`launchd/com.lawver.router.plist`（本机彩排，路径按需改）。核心必须能自己爬起来——它是整站入口，它挂了整站只剩 Cloudflare 的错误页。

配置查找顺序：默认值 → `--config` 指定的 JSON → 环境变量（`LAWVER_ROUTER_HOST/PORT/APP_UPSTREAM/INTRO_UPSTREAM/STATE_DIR/PROBE_INTERVAL`）。

## 维护：两种触发方式

1. **被动**：转发时连不上（进程没起、端口不通）→ 立刻判该侧下线，这一次请求就拿到维护页，同时后台每 5s 探活等待恢复。
2. **计划维护**（不杀进程）：

```bash
touch deploy/router/state/app.maintenance     # 功能页进入维护
rm    deploy/router/state/app.maintenance     # 恢复
```

文件在即视为该侧不在服务，探活不再覆盖这个判断。

## 维护时用户看到什么

| 请求类型 | 响应 |
|---|---|
| 页面导航（`Sec-Fetch-Mode: navigate`） | `302 → /under_maintenance?from=<原路径>`，恢复后自动跳回 |
| 接口与静态资源（fetch / XHR / `assets/*`） | `503` JSON + `Retry-After: 30` |

接口一律不重定向：fetch 跟着 302 拿到 HTML 是最难排查的一类故障。

维护页（`maintenance.html`）由核心自己回答，不依赖任何一侧，文案「维护中／我们很快就会回来。」，每 5s 轮询 `/__core/status`，两侧都恢复后自动返回原路径。

## 观测

```bash
curl -s 127.0.0.1:8080/__core/status | jq
```

返回两侧的 `up / planned / reason / since / upstream / probe`。适合挂到监控上（Komari 之类）直接打这个地址。响应头里的 `X-Core-Upstream: app|intro` 便于确认某个请求被分到哪一侧。

## 行为约定

- **路径表要和介绍页仓对齐**：`intro_exact` / `intro_prefixes` 改了，介绍页仓 README 里的表格也要改；`/intro-assets/*` 这个前缀是硬约定——功能页占着 `/assets/*`，同域下不分开就无法按路径判定归属。
- **转发是流式的**：SSE（`/api/court/turn`）与几十 MB 的上传都不缓冲；代理请求不设读超时，模型调用跑几分钟不会被误判成故障。
- **探活只看进程**：`/api/health` 不碰数据库。数据库抖动应该由具体接口报错，不该让整个功能页进维护态。
- **真实 IP 透传**：`CF-Connecting-IP` / `X-Forwarded-For` / cookie 原样转发；核心在回环上，正好落在功能页 `LAWVER_TRUSTED_PROXY_CIDRS` 的默认信任段，限流与日志看得到真实来源。
- `/api/health` 不写访问日志（`app_security.should_record_usage_log` 里排除），否则每 5s 一条探活会把真实用户行为淹掉。
