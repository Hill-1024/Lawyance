# 法库巡检、配额与用量周报

只在持有语料的自营服务器运行。客户实例通过固定 URL 调用，服务恢复后下一次查询自动恢复；不需要改客户配置或补发语料。

## 巡检和告警

先在受限环境文件配置 `LAW_MONITOR_KEY`，与 `keys.json` 中独立监控 key 相同。
巡检必须同时检查 `/healthz` 与带该 key 的 `/v1/meta`。`/healthz` 只检查索引就绪，
不写用量审计，也不验证密钥或审计写入；密钥配置失效或审计不可写会使 `/v1/meta`
失败，双探针仍会告警。不能将巡检缩减为只请求 `/healthz`。
缺少监控 key 会报告 `monitor_key_missing`，不能作为健康检查通过。

```bash
python3 scripts/law_service_ops.py check \
  --url http://127.0.0.1:8084 \
  --audit /var/lib/lawver-law/audit.jsonl \
  --minutes 15 --p95-ms 2000 --max-rpm 30 --min-sample 100
```

正常退出码为 0；异常退出码为 1，JSON 的 `alerts` 给出告警原因。不可用、5xx、p95 超阈值、触发 429 或峰值请求数达到阈值都会告警。至少 100 次请求后，查询哈希去重率高于 95% 或低于 5% 会提示人工检查遍历或重试失控。该信号只供核查，不自动吊销客户 key。按 key 的实际 rpm 配置调整 `--max-rpm`；不同套餐可分别巡检对应日志。

将退出状态和 JSON 输出接入现有监控即可；脚本不会主动发送邮件或第三方消息。部署目录有可选 systemd 巡检/周报 timer 示例。启用后以 `systemctl list-timers 'lawver-law-*'` 核对调度；实际告警通知由既有监控的 failed-unit 或日志规则负责，启用 timer 本身不代表已接通通知。

审计日志按 UTC 记时；周报窗口是执行时刻之前的滚动 7 天。脚本读取当前日志及数字后缀的轮转文件。需让巡检用户有读取权限，禁止把审计目录发布到公网。服务固定每份 10 MiB、保留 7 份轮转备份；确认实际流量下覆盖至少 7 天，高流量时由运维外部归档，避免周报缺失旧数据。

审计字段 `ip` 仅为 TCP 直连对端地址。服务位于回环隧道/反向代理或容器网桥后时，
它通常是 `127.0.0.1` 或网桥/代理地址，不能据此认定客户的真实出口 IP。
客户用量和异常调用按 `key_name` 维度分析；来源取证另查可信入口日志。
服务不会根据请求中的 `X-Forwarded-For` 或 `CF-Connecting-IP` 改写该字段，
不要将它当作经过验证的客户端来源地址。

## Canary 验收

为监控单独生成随机 key，在服务 `keys.json` 条目设 `canary: true`。它仍受 rpm 与 daily_quota 限制，不复用生产客户 key。只有搜索文本严格为 `__lawver_canary__` 时返回标记，普通法律问题完全走真实检索。

```bash
# LAW_CANARY_KEY 从服务器的受限环境文件加载，勿粘贴进共享日志。
python3 scripts/law_service_ops.py check \
  --audit /var/lib/lawver-law/audit.jsonl \
  --canary-key-env LAW_CANARY_KEY
```

诊断 key 错误或响应没有 canary 标记会报告 `canary_failed`。诊断条目是虚构测试数据，不是法律依据。用于泄露溯源的标记按专用 key 派生；常规客户检索不注入虚构法条。

## 用量周报与配额调优

```bash
python3 scripts/law_service_ops.py report \
  --audit /var/lib/lawver-law/audit.jsonl --days 7 \
  > /var/lib/lawver-law/weekly-usage.json
```

报告包含每个 key 的请求量、端点分布、HTTP 状态分布、429、5xx、p95、每分钟峰值和哈希去重率。不输出查询正文、查询哈希、来源 IP 或 API key。异常行只计数，不原样回显。

精确端点 `/healthz` 不计入请求量、key 分组、p95、峰值或调用模式告警；历史当前及
轮转日志中合法的健康检查记录也会在汇总时排除，原始日志不改写。
格式损坏的行仍计入 `invalid_lines` 并触发 `audit_invalid`。
鉴权失败、未知端点及 `/v1/meta` 继续统计；监控 key 的元数据请求保留在其独立分组。

试运行先用示例的 30 rpm / 20000 次日配额。按周报里的正常峰值留出余量再调整，观察 429 与 p95 是否下降。修改 `keys.json` 时先在同目录写完整临时文件，再原子替换，避免重载读到半份 JSON；禁用单个 key 用 `enabled: false`。限流/日配额为单进程内存状态，重启会重置，服务只运行一个进程；有严格持久额度要求时另行接入计量存储。调用量接入 credit 扣费作为 issue 允许的后续迭代。

## 故障与恢复演练

在 dev 环境执行，记录时间与输出：

1. 停止法库服务，运行 `check`，确认 `unavailable` 和非零退出码；客户法条工具应返回明确的不可用信息。
2. 启动原服务，等待 `/healthz` 返回 `{"ready": true}`；使用同一个客户 URL/key 再次调用三个工具，确认恢复。
3. 将巡检 `--p95-ms` 暂设低于实测延迟，确认 `latency_p95`；还原阈值。
4. 使用独立低 rpm 测试 key 触发 429；确认审计记录及 `rate_pressure`。不要用生产客户 key 试限流。
5. 使用 canary 专用 key 验证标记，再给巡检传错误诊断 key，确认 `canary_failed`。

失败时先查 `journalctl -u lawver-law.service`、语料/索引磁盘权限、密钥 JSON 与审计磁盘空间。使用保留的上一版本代码和匹配的数据版本回滚并重启；语料更新与应用发布分别留档。不要在客户机器上建立本地语料缓存作为故障兜底。
