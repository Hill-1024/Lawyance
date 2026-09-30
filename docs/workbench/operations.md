# 云端工作台运行与恢复

## 部署顺序

1. 保留现有认证与模型服务配置，安装更新后的 Python 与 pnpm 依赖。
2. 启动 PostgreSQL 17（可使用 `deploy/workbench/compose.yml`），创建专用数据库与持久文件目录。数据库端口只监听本机。
3. 根据 `deploy/workbench/environment.example` 配置数据库、文件卷与独立插件加密密钥。密钥必须放入部署密钥管理渠道，不进入 Git。
4. 执行 `alembic upgrade head`；重启现有 FastAPI 服务。
   - **账号现在也在这个库里**：`accounts` 与 `account_sessions` 两张表。首次启动若账号表为空，会依次尝试导入遗留的 `data/account.json`、旧 `data/auth.sqlite3`，都没有才用 `INITIAL_ADMIN_PASSWORD` 引导；导入过的旧库会改名归档（`auth.sqlite3.imported-<时间戳>`）。
   - 因此**没配 `LAWVER_DATABASE_URL` 就没人能登录**，服务照常起、登录界面会提示「工作台尚未就绪」。
   - 会话凭据是不透明 sid（不再是 JWT），表里删行即失效；升级后**所有人需要重新登录一次**。
   - 登录失败节流（原 `data/lockout.json`）也在库里（`login_throttle`）：Redis 负责快路径计数与锁定标记，Postgres 是事实源。Redis 不可用时自动退回查库，锁定策略不变。
5. 构建 Web 与 Android。正式 Android 包不得带 `VITE_LAWVER_API_BASE` 本机测试值或 `LAWVER_QA_NATIVE=1`。
6. 启动三件套：分流核心、功能页、介绍页（见下一节）。介绍页来自独立仓库 `Hill-1024/Lawyance_Intro`，在本机各自 `git pull` 后构建，不与本仓库的构建耦合。
7. 完成真实模型、文档审阅、多设备与原生验收之后再放开账号。官网演示仍需标明发布状态。

## 进程与入口

同机三件套（分流核心 8080 / 功能页 8081 / 介绍页 8082）的安装、配置、systemd 化、上线自检、更新与回滚，全部写在 **[README 的「部署运行手册（远端机器）」](../../README.md#部署运行手册远端机器)** 里，这里不再重复。与本文件相关的只有两件运维动作：

```
# 只读维护窗口：功能页照常读取，写操作被拒
LAWVER_WORKBENCH_READ_ONLY=1   # 写入 .env 后重启 lawver-app

# 两侧状态（挂监控也用它）
curl -s 127.0.0.1:8080/__core/status
```

**整机或隧道全挂时没有维护页**：核心自己也在这台机器上，此时只剩 Cloudflare 的错误页——这是把入口收在本机的代价，缓解手段是核心保持 `Restart=always` 且体积极小。

## 每日备份与 30 天保留

通过部署调度器每日执行一次。先设置 `LAWVER_WORKBENCH_READ_ONLY=1`，等待运行中的任务结束，停止 worker/重启只读进程，确认没有活动写事务，再运行：

```
python -m workbench.maintenance backup /secure/backups/lawver/YYYY-MM-DD
python -m workbench.maintenance verify /secure/backups/lawver/YYYY-MM-DD
```

命令需要 PostgreSQL 客户端 `pg_dump` 在 PATH。备份包含数据库、原始文件与 SHA-256 清单。数据库备份包含加密后的插件凭据，独立加密密钥另行保管。用户 v5 ZIP 备份不包含插件密钥，恢复后插件默认停用。

保留至少 30 天的成功备份，只有新备份校验成功之后才清理超龄备份。保留失败记录并报警。备份期间不要删除原始 blob。回收站到期清理使用 `python -m workbench.maintenance purge`；不可逆清理只应在已配置保留政策的部署任务中执行。

## 恢复演练

将数据库恢复到一个新的空库，而不是覆盖正在服务的库：

```
pg_restore --dbname=NEW_EMPTY_DATABASE /secure/backups/lawver/YYYY-MM-DD/database.dump
python -m workbench.maintenance verify /secure/backups/lawver/YYYY-MM-DD
```

复制 `blobs/` 到新的文件卷，设置新的数据库与卷路径，再检查项目、会话、文档、版本和事件数量、附件校验和、登录读取、导出与一个虚构材料任务。确认后切换数据服务入口。插件加密密钥需要从独立密钥管理恢复。

## 中断与回退

任务通过数据库租约领取。过期的 running/waiting_confirmation 标记 interrupted，不自动重放未知外部操作。事件带持久序号，可从最后读取序号继续。发生严重问题时开启只读维护模式，保留读取与导出，不把新版数据交给旧客户端写回。数据库迁移是增量新增；本次初始迁移不支持破坏性 downgrade。

## 监控与敏感数据

监控 HTTP 409 保存冲突、迁移状态 awaiting_files/complete_with_missing、任务 failed/interrupted、插件连接失败与附件缺失。日志只使用运行 ID、错误类型与状态，禁止记录正文、密钥或插件认证头。部署还需配置磁盘与数据库容量、备份结果以及过期任务告警。
