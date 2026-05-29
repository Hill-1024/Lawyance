# 断线续传 / 后台稳定接收 — 实现计划（交接文档）

> 本文档面向**没有参与前期讨论的实现 agent**。请先完整读完第 0~4 章再动代码。
> 所有设计决策已与产品负责人锁定（见第 2 章），**不要擅自更改这些决策**；
> 如实现中发现决策有硬冲突，停下来在文档"开放问题"区记录并上报，不要自行拍板。

文档版本：v1（2026-05-29 锁定）
代码基线：分支 `lawver`，commit `1b796c5`（WebDAV 同步已落地）

---

## 0. 这份计划解决什么问题

### 0.1 现象
单用户发起一次聊天响应（SSE 流式）时，只要用户把浏览器/App 挂到后台、熄屏、或网络抖动，
**整条响应就断掉且无法续传**，已生成的内容和服务端副作用（记忆写回）一起丢失。

### 0.2 现状关键事实（实现前必须理解）

**后端流式链路**
- `POST /api/chat`（[routes/chat.py](../routes/chat.py) `chat_endpoint`，第 39-66 行）：`stream=true` 时返回
  `StreamingResponse`，`media_type="text/event-stream"`。
- 生成器 `generate_agent()` 迭代 `run_agent_stream(prepared)`（[services/chat_pipeline.py](../services/chat_pipeline.py) 第 168-227 行），
  把每个事件 dict 序列化成 `data: {json}\n\n`，流尾发 `data: [DONE]\n\n`。
- **生成跑在 `StreamingResponse` 生成器内部，和 HTTP 连接绑死**：客户端一断，Starlette 取消该 task，
  `run_agent_stream` 当场停止，`full_result` 丢失，连 `persist_turn`（记忆写回，第 213-218 行）也不执行。
- `turn_id` 已在 `prepare_chat_turn` 生成（[chat_pipeline.py](../services/chat_pipeline.py) 第 130 行：`turn_id = f"turn_{uuid4().hex}"`）。本方案直接复用它作为 `stream_id`。
- 鉴权依赖 `get_current_user`（[services/auth_dependencies.py](../services/auth_dependencies.py)）：`Authorization: Bearer <token>` 优先，否则 cookie `auth_token`。
- 生命周期任务注册在 [app_factory.py](../app_factory.py) 的 `lifespan`（已有 `workspace_cleanup.start/stop` 范例）。
- 当前部署：**单 worker、单实例**（决策前提，见 2.1）。

**前端流式消费**（[src/hooks/useChat.ts](../src/hooks/useChat.ts)）
- `processStream`（第 428-576 行）用 `response.body.getReader()` 逐行解析 `data: {json}`，按 `data.type` 分发，
  调 `commitAssistantState()` 把累积的 `bodyText`/`thoughtBlocks` 等写进 React 消息对象。
- **`content` 是累加型**：`bodyText += data.content`（第 455-456 行）。续传重发已应用过的 `content` 会导致正文重复 → 必须按序号门控。
- 会话变化即写 IndexedDB：`fileDB.saveConversations(conversations)`（第 261-267 行的 effect）。**这是"设备已持久化"的天然信号**。
- **原生端切后台会主动 abort**：`appStateChange` 监听 `!isActive → abortActiveRequest()`（第 185-198 行）。
  即"挂后台就断"在原生端是**我们自己写的策略**，不是不可抗力。
- 事件类型（`handleStreamData`，第 453-494 行）：`content`/`content_replace`/`thought`/`thought_signature`/
  `download_path`/`memory_sync`/`context_usage`/`history_trace`/`error`。

**前端 API 客户端**（[src/services/api.ts](../src/services/api.ts)）
- `apiFetch`：原生加 `Authorization: Bearer` + `X-Lawver-Client: capacitor`、`credentials:'omit'`；Web 用 `credentials:'include'`（cookie）。
- `API_BASE`：原生 = `env.VITE_LAWVER_API_BASE || 'https://law.mutsumi.moe'`；Web = `''`（同源）。
- `chat()`（第 112-154 行）构造 `/api/chat` 请求体。

**IndexedDB 层**（[src/lib/db.ts](../src/lib/db.ts)）：`LawverFileDB`，object stores `files`/`conversations`/`court_sessions`，`version=3`。

**WebDAV 备份快照**（[src/services/storageService.ts](../src/services/storageService.ts) 第 167-229 行）：
`BackupSnapshot`（`version:3`）已含 `settings:{theme}`，`buildBackupSnapshot`/`applyBackupSnapshot` 共用。续传偏好挂这里同步。

**原生工程**
- 已有自定义插件范例 [LawverUpdaterPlugin.java](../android/app/src/main/java/moe/mutsumi/lawver/LawverUpdaterPlugin.java)
  （`@CapacitorPlugin`、`@PluginMethod`、`notifyListeners`、`execute(Runnable)` 后台线程、`HttpURLConnection`）。
- 插件注册：[MainActivity.java](../android/app/src/main/java/moe/mutsumi/lawver/MainActivity.java) `onCreate` 调 `registerPlugin(...)`。
- [AndroidManifest.xml](../android/app/src/main/AndroidManifest.xml) 当前仅 `INTERNET`、`REQUEST_INSTALL_PACKAGES`，**无任何前台服务声明**。
- 应用 id `moe.mutsumi.lawver`，Capacitor 8，仅 Android 平台（无 iOS 工程）。

---

## 1. 设计公理（隐私优先，不可妥协）

1. 服务端**默认不持久化任何响应内容**；续传是 **opt-in**。
2. 续传偏好**不上服务端**：本地存储 + 用户自己的 WebDAV 同步，服务端对"谁开了续传"无状态。
3. 服务端续传缓冲只在"用户明确同意" 且 "尚未被设备确认收妥"的窗口内，**临时存在于进程内存**（不落盘）。
4. 防止恶意"大量请求 + 断连"撑爆存储：多重上限（并发数 / 单流字节 / 全局字节 / TTL）共同兜底。

---

## 2. 锁定决策（含理由，禁止擅改）

| # | 决策 | 理由 |
|---|---|---|
| 2.1 | **单 worker / 单实例** → 服务端缓冲用**进程内 `dict` + TTL**，不引入 Redis | 最简、最贴隐私（不落盘）。代价：重启即丢、扩 worker 会失效 → 见 5.6 启动闸 |
| 2.2 | 开了续传后，**生成跑到完**（即使无人重连） | 保证回来一定拿到完整答案。代价：废弃流烧 token + 占内存 → 防爆上限是**必须项**（5.5） |
| 2.3 | **两层一起做**：A 原生前台服务 + B 服务端续传 | 覆盖不同故障层级，见第 3 章 |
| 2.4 | 进程被杀这一层（划掉 App / 强杀），**靠服务端续传** | 原生内存 buffer 随进程消失，只有服务端 buffer 能跨进程死亡恢复 |
| 2.5 | 服务端续传**默认关**；检测到**首次断流时弹窗邀请开启** | opt-in 保隐私，又在最需要时让用户发现。**注意**：弹窗开启只对**未来**生效，救不回当前这条（当前未缓冲）——文案不可过度承诺（见 7.6） |
| 2.6 | 偏好**本地存 + WebDAV 同步**，每个请求带 `resume_enabled` 标志 | 服务端无状态；跨设备靠用户自己的 WebDAV |
| 2.7 | TTL 默认 **45 min（30–60 区间，可配置）** | 匹配真实续传窗口，控制暴露面与内存 |
| 2.8 | 新增**显式"停止"按钮** | 与"切后台 detach"明确区分：Stop = 真取消 + 删缓冲；切后台 = 只 detach |

**重要边界澄清（实现者必读）**：
- 移动端浏览器用户群体不小，他们**没有前台服务**，后台必断，服务端续传是其**唯一**续传手段 → Layer B 是承重墙，不是可选项。
- 原生前台服务（Layer A）是**传输层改造**，与续传开关**独立**：它无条件改善"切后台/熄屏"，不依赖 2.5 的开关。开关只控制 Layer B 的**服务端缓冲**。

---

## 3. 架构总览

### 3.1 故障分层与责任

| 故障层级 | 谁来兜 | 后端改动 | 受开关控制 |
|---|---|---|---|
| WebView JS 冻结 / 切后台 / 熄屏（原生 App） | **A. 原生前台服务**（原生内存 buffer + drain） | 否 | 否（无条件生效） |
| 移动端浏览器后台（无前台服务） | **B. 服务端续传** | 是 | 是 |
| 进程被杀 / 划掉 App（原生） | **B. 服务端续传** | 是 | 是 |
| 换设备（偏好跟随） | WebDAV 同步 `settings.resumeEnabled` | 否 | — |

### 3.2 两层如何协同（关键，否则 2.4 接不上）

**ACK 纪律 —— 缓冲区只能被"持久化进度"裁剪：**
- 谁向服务端 ACK、触发裁剪？**只有 JS，且以写进 IndexedDB 为准。**
- 原生前台服务**绝不替 JS 向服务端 ACK**（它的内存 buffer 不是持久的，进程一死就没）。
- 推论：App 在后台（JS 冻结）期间一个 ACK 都不发 → 服务端**保留完整缓冲** → 进程被杀后可从 IndexedDB 里的 `last_seq` 续传。

| 状态 | 原生内存 buffer | 服务端 buffer |
|---|---|---|
| 前台正常 | 实时转发给 JS | 被 ACK 持续裁到≈0 |
| 后台 / 熄屏 | 原生内存累积 | 不裁，保留完整（JS 没 ACK） |
| 进程被杀 | 随进程消失 | 仍在 → 重启后从 IndexedDB `last_seq` 续传 |

> **ACK 只是优化**：即使 ACK 丢失，服务端不裁剪，续传仍正确（服务端总能从 `from_seq` 之后重放）。

---

## 4. 核心协议（Layer A / B 共用语义）

### 4.1 stream_id 与 seq
- `stream_id` = 复用 `turn_id`（`prepare_chat_turn` 已生成）。**首事件**下发给客户端。
- **每个 SSE 事件的 JSON 内嵌 `seq`**（单调递增整数，从 0 开始）。
  之所以放进 JSON 而非只用 SSE `id:` 行：前端是**自定义解析**（非原生 `EventSource`），读 `data.seq` 最稳。
- 续传按 `seq` 门控：服务端只重放 `seq > from_seq` 的事件。`content` 累加型由此天然去重；
  `content_replace`/`memory_sync` 是覆盖型，重放也无害。

### 4.2 SSE 事件格式（在现有基础上**做加法**，向后兼容）

每条仍是 `data: {json}\n\n`；流尾仍是 `data: [DONE]\n\n`。新增/变化：

| 事件 | 何时 | 形态 | 说明 |
|---|---|---|---|
| `stream_start` | 缓冲模式首个事件 | `{"type":"stream_start","seq":0,"stream_id":"turn_xxx","buffered":true}` | 客户端据此存 `stream_id`；`buffered=false` 表示服务端未缓冲（开关关 / 降级） |
| 现有所有事件 | 不变 | 各自结构 **+ `"seq": N`** | 仅新增字段，旧客户端忽略未知字段，安全 |
| `done` | 生成正常结束、`[DONE]` 之前 | `{"type":"done","seq":N,"final_seq":N}` | 客户端据 `final_seq` 判定收全 |
| `resume_unavailable` | 请求要缓冲但无法满足 | `{"type":"resume_unavailable","seq":0,"reason":"quota\|disabled\|worker"}` | 客户端据此提示"本次无法续传"，仍正常直连接收 |
| `error` | 出错 | `{"type":"error","seq":N,"content":"..."}` | 不变，加 seq |

> 非缓冲模式（`resume_enabled=false`）下：仍发 `stream_start{buffered:false}` 与 `seq`，但**行为与今天一致**（生成器与连接绑死，断即丢）。这样前端逻辑统一，老 wire 仍兼容。

### 4.3 事件类型完整清单（实现者据此分发）
现有：`content`、`content_replace`、`thought`（含 `thought_type`/`mode`）、`thought_signature`、
`download_path`、`memory_sync`、`context_usage`、`history_trace`、`error`。
新增：`stream_start`、`done`、`resume_unavailable`。

---

## 5. Layer B — 服务端续传（FastAPI）

### 5.1 schemas 变更
[schemas.py](../schemas.py) `ChatRequest` 增加一个字段：
```python
resume_enabled: bool = False   # 客户端按"平台 + 本地偏好"决定是否置 true
```
其余字段不动。

### 5.2 新模块 `services/stream_buffer.py`

**数据结构（进程内全局单例）**
```text
StreamState:
  stream_id: str
  user: str                 # 拥有者（鉴权隔离）
  events: list[tuple[int, dict]]   # (seq, payload)，可从头部裁剪
  next_seq: int
  done: bool
  error: Optional[str]
  final_seq: Optional[int]
  created_at: float
  last_acked_seq: int        # = -1 表示未 ACK
  byte_count: int            # 当前缓冲字节（裁剪后）
  task: asyncio.Task         # 生成协程，引用必须持有防 GC
  cond: asyncio.Condition    # 有新事件 / done 时 notify_all

_REGISTRY: dict[str, StreamState]      # stream_id -> StreamState
_USER_STREAMS: dict[str, set[str]]     # user -> {stream_id}（算并发用）
```

**对外 API（async）**
- `create(stream_id, user) -> StreamState | None`：超并发上限返回 `None`（调用方据此降级）。
- `append(stream_id, payload) -> int`：分配 seq、入队、累加字节、`cond.notify_all`；超单流字节上限则不再追加、置 `truncated` 标记。返回 seq。
- `finish(stream_id, error=None)`：置 `done`、`final_seq`、`notify_all`。
- `reader(stream_id, from_seq) -> async iterator[dict]`：先吐缓冲里 `seq>from_seq` 的事件；
  若 `not done`，`await cond` 等新事件继续吐；直至 `done` 后吐完剩余并结束。**多个 reader 可并存**（每个持自己的游标）。
- `ack(stream_id, user, acked_seq)`：校验 owner；裁掉 `seq<=acked_seq`、更新 `last_acked_seq`/`byte_count`；
  若 `done and acked_seq>=final_seq` → `delete`。
- `cancel(stream_id, user)`：校验 owner；`task.cancel()`；`delete`。
- `delete(stream_id)`：从两个表移除。
- `get(stream_id, user) -> StreamState | None`：校验 owner；不存在返回 None（调用方回 410）。

**生产者协程**（把现有 `run_agent_stream` 包一层）
```text
async def _produce(stream_id, prepared):
    try:
        async for event in run_agent_stream(prepared):   # 副作用（persist_turn 等）仍在其中，跑到完
            await append(stream_id, event)
        await append(stream_id, {"type":"done"})          # finish 时补 final_seq
        await finish(stream_id)
    except asyncio.CancelledError:
        await finish(stream_id, error="cancelled"); raise
    except Exception as e:
        await append(stream_id, {"type":"error","content":str(e)})
        await finish(stream_id, error=str(e))
```
`task = asyncio.create_task(_produce(...))` —— **不绑定请求**，客户端断连不影响它。

### 5.3 routes/chat.py 改造

`chat_endpoint`：当 `request.stream and request.resume_enabled`：
1. `state = await stream_buffer.create(prepared.turn_id, user)`。
2. `state is None`（超并发）或全局字节超限 → **降级**：走原有非缓冲路径，但首事件发 `resume_unavailable{reason:"quota"}`（仍正常流式应答）。
3. 否则启动生产者 task，返回 `StreamingResponse`，其 body = 把 `stream_buffer.reader(turn_id, from_seq=-1)` 序列化成 SSE
   （首条注入 `stream_start{stream_id,buffered:true}`；每条注入 `seq`；末尾 `data: [DONE]`）。
- `resume_enabled=false`：保持今天的 `generate_agent()` 实现完全不变（只额外注入 `stream_start{buffered:false}`+`seq`，可选）。

**新端点（均 `Depends(get_current_user)`）**

| 方法/路径 | 请求 | 响应 | 行为 |
|---|---|---|---|
| `GET /api/chat/resume/{stream_id}?from_seq=N` | query `from_seq`（int，默认 -1） | `text/event-stream`（同上 SSE） | `get` 校验 owner；不存在/过期 → **410** `{"error":"stream_expired"}`；存在 → `reader(stream_id, from_seq)` 重放 `seq>N` 后续接 live 到 done |
| `POST /api/chat/ack` | `{"stream_id":str,"acked_seq":int}` | `{"ok":true,"trimmed_to":N}` | 裁剪缓冲；done 且收全则删 |
| `POST /api/chat/cancel` | `{"stream_id":str}` | `{"ok":true}` | 取消生产者 + 删缓冲 |

新增请求体放进 [schemas.py](../schemas.py)：`ResumeAckRequest{stream_id:str, acked_seq:int}`、`StreamCancelRequest{stream_id:str}`。
端点注册在 `chat.router`（[app_factory.py](../app_factory.py) 已 include）。

### 5.4 chat_pipeline.py 改造
- `run_agent_stream` 逻辑基本不动（它已是 async generator，且副作用内置）。
- 仅需保证：被 `_produce` 驱动到完，不再依赖 HTTP 连接存活。
- `persist_turn` / `memory_sync` / `context_usage` 等照旧 yield，进缓冲、被重放。

### 5.5 防爆上限（**必须项**，全部可配置）

| 项 | 默认 | env | 超限行为 |
|---|---|---|---|
| 每用户并发缓冲流 | 3 | `LAWVER_RESUME_MAX_STREAMS_PER_USER` | 降级为非缓冲 + `resume_unavailable{quota}` |
| 单流缓冲字节 | 2 MB | `LAWVER_RESUME_MAX_BYTES_PER_STREAM` | 停止继续缓冲（置 `truncated`），仍 live 转发；客户端续传只能到截断点 |
| 全局缓冲字节 | 128 MB | `LAWVER_RESUME_MAX_BYTES_GLOBAL` | 先淘汰最老的 done/废弃流；仍超 → 新请求降级 |
| TTL | 2700s(45min) | `LAWVER_RESUME_TTL_SECONDS` | 清扫器删除（连同 cancel 生产者） |
| 清扫间隔 | 60s | `LAWVER_RESUME_SWEEP_SECONDS` | — |

- 仅认证用户可用（`get_current_user` 已保证）。接入现有限流中间件 [services/app_security.py](../services/app_security.py) 对 `create` 计数。
- 清扫器 = lifespan 后台 task，遍历 `_REGISTRY`，删 `now-created_at > TTL` 者。

### 5.6 生命周期与单实例闸（app_factory.py）
- `lifespan` 中 `stream_buffer.start(app)`（建清扫 task）/ `stream_buffer.stop(app)`（取消清扫 + 取消所有生产者）。
- **启动闸**：读 worker 数（env `UVICORN_WORKERS`，或 `os.getenv`）。若 `>1` 且使用内存存储：
  - 默认 **大声 WARNING**：续传在多 worker 下不可靠（重连可能落到别的 worker）。
  - env `LAWVER_RESUME_REQUIRE_SINGLE_WORKER=1` 时 **直接拒启**。

### 5.7 后端边界与不变量
- `resume_enabled=false` 路径**零行为变化**（回归基线必须通过）。
- 缓冲只存"序列化后的 SSE 事件 dict"，**对 agent 模式不可知**（默认 / Plan-and-Solve / 工具循环都适用）。
- 庭审 `/api/court/turn`（[routes/court.py](../routes/court.py)）**本期不纳入**续传，保持原样。

---

## 6. Layer A — Android 原生前台服务

### 6.1 关键约束（避免踩坑）
- **WebView 的 JS 在后台会被冻结**，`fetch`+`reader.read()` 循环停摆。所以 **SSE 必须从原生侧发起**，不能继续用 WebView fetch。
- **Android 12+ 不允许从后台启动前台服务**（`ForegroundServiceStartNotAllowedException`）。
  因此前台服务必须**在流开始时（App 尚在前台）就启动**，结束时停止。代价：每次生成都会出现一条常驻通知（这是固有成本，可作为"正在生成"提示）。
  → **不要**尝试"切后台时才懒启动前台服务"，会抛异常。

### 6.2 新插件 `StreamServicePlugin`（仿 LawverUpdaterPlugin 结构）

TS 侧接口（新建 `src/lib/native-stream.ts`，仅原生可用）：
```ts
export interface NativeStreamPlugin {
  startStream(opts: { url: string; headers: Record<string,string>; body: string }): Promise<{ streamId: string }>;
  drain(opts: { streamId: string; fromIndex: number }): Promise<{ events: string[]; nextIndex: number; done: boolean; error?: string }>;
  stop(opts: { streamId: string }): Promise<void>;        // 完成/取消后清缓冲 + 停前台服务
  addListener('streamEvent', cb: (e:{streamId:string,index:number,payload:string}) => void): ...;
  addListener('streamDone',  cb: (e:{streamId:string,finalIndex:number,error?:string}) => void): ...;
}
```

Java 侧（`StreamServicePlugin.java` + 一个 `StreamForegroundService`）：
- `@CapacitorPlugin(name="StreamService")`，`@PluginMethod startStream/drain/stop`。
- `startStream`：在**前台线程上下文**用 `ContextCompat.startForegroundService` 拉起 `StreamForegroundService`，
  传入 url/headers/body。服务内：
  - `startForeground(notificationId, notification)`（通知文案"Lawver 正在生成回答…"，channel 低优先级）。
  - 用 `HttpURLConnection`（POST，写 body，逐行读 `data: ` 行；或加 OkHttp 依赖，二选一，建议沿用 `HttpURLConnection` 减少依赖）。
  - 每收到一个事件：追加到内存 `List<String> events`（保序），`notifyListeners("streamEvent", {streamId,index,payload})`。
  - JS 冻结时 `notifyListeners` 送不达 → 故事件**始终留在内存 list**，靠 JS 回前台 `drain` 补齐。
  - 收到 `[DONE]`/错误：`notifyListeners("streamDone", ...)`，**保留 list 等 JS drain**，不立即清。
- `drain(streamId, fromIndex)`：返回 `events[fromIndex..]`、`nextIndex`、`done`、`error`。
- `stop(streamId)`：清 list、`stopForeground(true)`、`stopSelf()`。
- 进程被杀：内存 list 随之消失（由 Layer B 兜底，见 2.4）。

### 6.3 鉴权与 URL（原生）
- `startStream` 的 `headers` 由 JS 传入：`Authorization: Bearer <token>`（`getAuthToken()`）+ `X-Lawver-Client: capacitor` + `Content-Type: application/json`。
- `url` = `API_BASE + '/api/chat'`，`API_BASE` 同 [api.ts](../src/services/api.ts)（原生 = `VITE_LAWVER_API_BASE || 'https://law.mutsumi.moe'`）。
- body = 与 `chat()` 相同的 JSON（含 `resume_enabled`）。

### 6.4 原生 ↔ JS drain 协议
1. JS `startStream` → 得 `streamId`，记 `lastIndex = -1`。
2. 前台：监听 `streamEvent`，按 `index` 顺序应用（丢弃 `index<=lastIndex` 的重复），更新 `lastIndex`。
3. App 回前台（`appStateChange isActive`）：先 `drain(streamId, lastIndex+1)` 补齐冻结期间漏的，再继续监听。
4. `streamDone`：再 `drain` 一次确保收全 → 写 IndexedDB → `stop(streamId)`。
5. **同时**（若续传开关开）：按 4.x 的 ACK 纪律向服务端 ACK（只在 JS 前台、已落 IndexedDB 后）。

### 6.5 AndroidManifest 变更
```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" /> <!-- Android 14+ -->
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />          <!-- Android 13+ 运行时申请 -->
<uses-permission android:name="android.permission.WAKE_LOCK" />                    <!-- 可选，保活网络读循环 -->
<!-- application 内： -->
<service
    android:name=".StreamForegroundService"
    android:exported="false"
    android:foregroundServiceType="dataSync" />
```
- `POST_NOTIFICATIONS` 需在首次启动服务前**运行时申请**（Android 13+）；未授予则服务仍可跑，但通知不显示（Android 会限制）。
- 注册插件：[MainActivity.java](../android/app/src/main/java/moe/mutsumi/lawver/MainActivity.java) `onCreate` 加 `registerPlugin(StreamServicePlugin.class);`。

### 6.6 何时走原生服务
- `isNativeAndroid()`（[src/lib/platform.ts](../src/lib/platform.ts)）为真时，聊天流式**一律经插件**（这是传输层改造，无条件，不依赖续传开关）。
- Web（含移动端浏览器）继续走 `fetch`（`processStream`）。

---

## 7. 前端（Web 共用 + 原生胶水）

### 7.1 类型（[src/types.ts](../src/types.ts)）
`Message` 增加可选字段：
```ts
stream_id?: string;
stream_status?: 'streaming' | 'done' | 'error';
last_committed_seq?: number;   // 已写进 IndexedDB 的最后 seq
```
（这些随会话一起进 IndexedDB / WebDAV，无需新 object store，db.ts 不升版本。）

### 7.2 api.ts
- `chat()` 增参 `resumeEnabled: boolean`，写进 body。
- 新增：
  - `resumeStream(streamId: string, fromSeq: number, signal?) => Promise<Response>`（`GET /api/chat/resume/{id}?from_seq=`；410 时抛 `StreamExpiredError`）。
  - `ackStream(streamId, ackedSeq)`（`POST /api/chat/ack`）。
  - `cancelStream(streamId)`（`POST /api/chat/cancel`）。

### 7.3 useChat.ts — `processStream` 改造
- 读 `data.seq`；维护 `lastSeq`。仅应用 `seq>lastSeq` 的事件（去重，保护累加型 `content`）。
- 处理 `stream_start`：把 `stream_id` 存到当前 assistant message，置 `stream_status='streaming'`。
- 每次 `commitAssistantState()` 落 React → 触发 IndexedDB 保存后，更新 `message.last_committed_seq=lastSeq`，并**节流**（如 ≥500ms 或每 N 条）调 `ackStream(stream_id, lastSeq)`（仅当 `buffered=true`）。
- 收到 `done`/`[DONE]` 且 `lastSeq>=final_seq` → `stream_status='done'`，发最终 ACK。
- **断流判定**：reader 抛错 / 提前结束且未见 `done`：
  - 若 `buffered=true`（开关开）→ 保持 `stream_status='streaming'`，留 `stream_id+last_committed_seq`，触发 7.4 续传。
  - 若 `buffered=false`（开关关）→ 触发 7.6 断流弹窗（注意：救不回当前这条）。

### 7.4 续传触发（重连 / 启动扫描）
- App 启动 / 回前台 / 网络恢复时，扫描 `conversations` 里 `stream_status==='streaming' && stream_id` 的 assistant message。
- 对每条调 `resumeStream(stream_id, last_committed_seq)`：
  - 成功 → 复用 `processStream` 消费（同样 seq 门控、ACK），续完置 `done`。
  - 410 `stream_expired` → 置 `stream_status='error'`，UI 提示"续传窗口已过"，提供"重新生成"（复用 `handleRegenerateMessage`）。

### 7.5 原生流式接入
- `isNativeAndroid()` 时，`handleSend`/`handleRegenerateMessage` 不走 `fetch`，改：
  1. JS 构造 url/headers/body（含 `resume_enabled`）。
  2. `nativeStream.startStream(...)` → 监听 `streamEvent`/`streamDone`，按 6.4 drain。
  3. 事件喂给一个**与 `handleStreamData` 等价的处理器**（建议把 `handleStreamData` 抽成可复用函数，原生/Web 共用）。
- **`appStateChange` 改造**（[useChat.ts:185-198](../src/hooks/useChat.ts#L185-L198)）：原生模式下，切后台**不再 abort**；改为依赖原生服务继续接收，回前台 drain。
  仅"显式停止"才取消（见 7.7）。

### 7.6 断流弹窗（决策 2.5）
- 触发：开关关 + 检测到断流（见 7.3）。用现有 `DialogContext`（[src/contexts/DialogContext.tsx](../src/contexts/DialogContext.tsx)）。
- 文案（**必须诚实，不过度承诺**）：
  > 「本次回答因离开页面/网络中断而停止。是否开启**断线续传**？开启后，**今后**的回答会在中断时自动恢复（为此需在服务器临时缓存回答内容，最多 45 分钟，或在你的设备确认接收后立即删除）。本次回答可点击重新生成。」
  - 「开启续传」→ 置本地偏好 `resumeEnabled=true`（7.8），不重试当前这条。
  - 「仅重新生成本次」→ `handleRegenerateMessage`。
  - 「不了」→ 关闭。
- 防打扰：同一会话/同一次会话内最多提示一次（加内存级标记）。

### 7.7 显式"停止"按钮（决策 2.8）
- 在 [src/components/InputArea.tsx](../src/components/InputArea.tsx)（生成中）放"停止"。
- 行为：`abortActiveRequest()` + 若有 `stream_id` 调 `cancelStream(stream_id)`；原生再调 `nativeStream.stop(streamId)`。
- 与切后台区分：切后台 = detach（不 cancel）；停止 = 真取消 + 删服务端缓冲 + 停前台服务。

### 7.8 偏好存储 + WebDAV 同步（决策 2.6）
- 新建 `src/lib/resume-prefs.ts`：`getResumeEnabled()/setResumeEnabled(bool)`，原生用 `@capacitor/preferences`、Web 用 `localStorage`（仿 [webdav-storage.ts](../src/lib/webdav-storage.ts) 模式）。key `lawver.resume.enabled`。
- [storageService.ts](../src/services/storageService.ts)：`BackupSnapshot.settings` 增 `resumeEnabled?: boolean`；
  - `buildBackupSnapshot`：读偏好写入 `settings.resumeEnabled`。
  - `applyBackupSnapshot`：若存在则 `setResumeEnabled(...)`。
  - 版本可升 `version:4` 或保持 3 容忍缺字段（建议升 4 并在导入处兼容旧 3）。
- 决定每请求 `resume_enabled` 取值：`getResumeEnabled()`（与平台无关；原生即便走前台服务，也按此决定是否额外开服务端缓冲以兜进程被杀）。
- [SettingsPage.tsx](../src/components/SettingsPage.tsx)：加一个开关绑定该偏好，附简短隐私说明（同 7.6 文案要点）。

---

## 8. 端到端流程（验收时按此走查）

1. **Web happy path（前台不断）**：开/关续传都应与今天体验一致；开时服务端缓冲被 ACK 裁到≈0，结束即删。
2. **Web 移动端后台续传（开关开）**：发起→切后台→回前台：`resumeStream` 从 `last_committed_seq` 续上，正文不重复、不丢，最终 `done`，服务端缓冲删除。
3. **原生前台服务（熄屏/切后台，开关无关）**：发起→熄屏→亮屏：原生服务持续接收，回前台 `drain` 补齐，通知在生成期间可见、结束消失。
4. **原生进程被杀恢复（开关开）**：发起→切后台→划掉 App→重开：扫描到 `streaming` 消息→`resumeStream` 成功续完。
5. **续传窗口过期**：`resumeStream` 返回 410 → 提示 + 重新生成可用。
6. **显式停止**：点击停止→生成中止、服务端缓冲删除、原生通知消失、`cancel` 返回 ok。
7. **断流弹窗（开关关）**：Web 移动端断流→弹窗→选"开启"→偏好写入并经 WebDAV 同步；当前条不被错误地"假装恢复"。
8. **防爆**：脚本并发发起 >上限 的缓冲流并断连→新流降级为非缓冲（`resume_unavailable`），内存有界，TTL 到期清理。

---

## 9. 边界与失败处理

| 场景 | 期望 |
|---|---|
| ACK 网络失败 | 服务端不裁剪，续传仍正确（幂等） |
| 重连时 `from_seq` 已被裁剪掉的更早位置 | 不会发生：客户端只用已落 IndexedDB 的 `last_committed_seq`，恰是已 ACK 点 |
| 服务器重启（单实例内存丢） | 在途/缓冲全失；客户端 `resumeStream` 收 410 → 提示重生成。**接受**（2.1 代价） |
| 多 worker 误部署 | 启动闸告警/拒启（5.6） |
| `resume_enabled=false` | 完全等同今天行为（回归基线） |
| 原生未授予通知权限 | 服务仍跑，尽量接收；通知可能不显示 |
| 同一 stream 多个并存 reader | reader 各自游标，互不影响 |
| 单流超字节上限 | `truncated`，live 仍转发；续传只能到截断点（文本极少触发） |

---

## 10. 分阶段任务拆解（建议交付顺序）

> 注意：决策是"两层一起做"，但**实现仍可分 PR**，下列为依赖顺序，非串行等待。

**P0 协议地基（后端 + 前端，互不阻塞可并行）**
- [ ] 后端：`ChatRequest.resume_enabled`；事件统一加 `seq`；`stream_start`/`done` 事件；`resume_enabled=false` 行为不变（回归测试）。
- [ ] 前端：`processStream` 读 `seq`、去重、处理 `stream_start`/`done`；`Message` 加 3 字段；`handleStreamData` 抽成可复用函数。

**P1 服务端续传（Layer B）**
- [ ] `services/stream_buffer.py`（数据结构 + API + 生产者 + 防爆 + TTL 清扫）。
- [ ] `routes/chat.py` 缓冲路径 + `/resume`/`/ack`/`/cancel` + schemas。
- [ ] `app_factory.py` lifespan 注册 + 单实例闸。
- [ ] 前端：`api.ts` resume/ack/cancel；`useChat.ts` ACK 节流、重连扫描、续传消费。
- [ ] 偏好 `resume-prefs.ts` + `SettingsPage` 开关 + `storageService` 同步字段。
- [ ] 断流弹窗（7.6）+ 显式停止按钮（7.7）。

**P2 原生前台服务（Layer A）**
- [ ] `StreamServicePlugin.java` + `StreamForegroundService` + Manifest + 注册。
- [ ] `src/lib/native-stream.ts` + `useChat.ts` 原生分支 + `appStateChange` 改造 + drain。
- [ ] `POST_NOTIFICATIONS` 运行时申请。

**验收标准**：第 8 章 8 条流程全过；`pnpm lint`（`tsc --noEmit`）通过；后端 `pytest` 通过（含 `resume_enabled=false` 回归 + 新端点单测：create/append/reader/ack/cancel/TTL/并发上限降级）。

---

## 11. 隐私 / 安全清单（合并前逐条核对）
- [ ] `resume_enabled=false` 时服务端零缓冲、零额外持久化。
- [ ] 缓冲仅内存、不落盘；进程退出即净。
- [ ] `/resume`/`/ack`/`/cancel` 均校验 `stream_id` 的 owner == 当前用户（防越权读他人响应）。
- [ ] 偏好不出现在任何服务端存储 / 日志。
- [ ] 断流弹窗文案不过度承诺（不暗示能救回当前未缓冲的回答）。
- [ ] TTL / 字节 / 并发上限默认值已设，且可经 env 收紧。
- [ ] 前台服务通知不泄露回答内容（仅"正在生成"）。

---

## 12. 开放问题 / 假设（实现中如遇请回填）
- 假设单 worker 单实例长期成立；若要扩容，须改 5.2 为共享存储（Redis Streams + EXPIRE），接口已按可替换设计。
- 假设无 iOS 工程；若新增 iOS，前台服务方案不适用（iOS 无等价长时后台），届时 iOS 仅靠 Layer B + 后台 URLSession 另议。
- `LAWVER_*` env 命名若与现有约定（[.env_example](../.env_example)）冲突，以现有约定为准并在此回填。
- 单流字节默认 2MB 是否足够覆盖最长法律分析输出，需用真实长样本验证后回填。
</content>
</invoke>
