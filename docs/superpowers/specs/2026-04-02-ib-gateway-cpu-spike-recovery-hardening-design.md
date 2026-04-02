# IB Gateway CPU 峰值恢复链路加固设计

## 背景
`2026-04-02 09:21` 到 `09:30 EDT`，宿主机出现持续 CPU 抬升，并在 `09:30 EDT` 左右恢复。日志显示，主因是 StockLean 的 `IB Gateway -> watchdog -> Lean bridge` 恢复链路连续升级：`bridge_refresh -> leader_restart -> gateway restart`，随后 Lean bridge 在 `stocklean-backend.service` 内完成账户回灌、持仓恢复和 `79` 个实时订阅恢复，并触发多次 `The IB API request has been rate limited.`。

本轮问题不在磁盘 IO，也不是 Kubernetes 或其他批任务。风险集中在以下四点：

1. `watchdog` 的 `gateway_restart` 通过阻塞式 `systemctl restart` 执行，`oneshot + TimeoutStartSec=30s` 会截断动作，导致恢复状态落盘不完整。
2. Lean bridge 在重连后立即串行恢复全部订阅，容易形成订阅洪峰和 IB API 限流。
3. 订阅恢复期间每个 symbol 都输出 TRACE 级请求/成功日志，放大 journald 和 CPU 压力。
4. `2104/2106/2107/2158` 这类 IB farm OK/idle 消息在 watchdog 与 Lean 侧仍带有误导性 ERROR/TRACE 噪音。

## 目标

1. 避免 `gateway_restart` 被 watchdog 自己的 service 超时截断。
2. 保留现有恢复状态机，但让 `gateway_restarting` 在动作发起后立即稳定落盘。
3. 将订阅恢复从“一次性洪峰”改为“分批恢复 + 批次摘要日志”。
4. 将 IB farm OK/idle 消息降级为信息日志，减少恢复期日志噪音。
5. 不改变当前交易阻断语义，不改变 IB Gateway 仍由 `systemd + IBC` 管理的边界。

## 非目标

1. 本轮不拆分 `stocklean-backend.service` 与 Lean bridge 进程。
2. 本轮不修改前端页面。
3. 本轮不改变交易策略、下单逻辑或风险控制参数。
4. 本轮不改动 `IB Gateway` 自身的 JVM 参数或 IBC 配置。

## 方案

### 1. watchdog 改为异步 gateway restart
在 [ib_gateway_watchdog.py](/app/stocklean/scripts/ib_gateway_watchdog.py) 中将 `gateway_restart` 动作改为：

- 先生成新的 `runtime_health`：
  - `state = gateway_restarting`
  - `last_recovery_action = gateway_restart`
  - `last_recovery_at = now`
  - `next_allowed_action_at = now + cooldown`
- 立刻写入 `gateway_runtime_health.json`
- 然后使用 `systemctl --user restart --no-block stocklean-ibgateway.service`
- watchdog 自身立即返回，不再等待 Gateway 完整停启

这样即使 `IB Gateway` 停止阶段超过 30 秒，watchdog 也不会因 `TimeoutStartSec=30s` 被 systemd 杀掉，恢复状态文件也能保持一致。

### 2. Lean IB 订阅恢复分批
在 [InteractiveBrokersBrokerage.cs](/app/stocklean/Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs) 内调整 `Subscribe(IEnumerable<Symbol>)` 的恢复行为：

- 引入可配置批次大小和批次间隔：
  - `InteractiveBrokersSubscriptionBatchSize = 10`
  - `InteractiveBrokersSubscriptionBatchDelayMs = 100`
- 在恢复旧订阅时，每批处理固定数量 symbol
- 每批之间 `Thread.Sleep(batchDelayMs)`
- 正常单个新订阅路径不受影响，只有“恢复整批旧订阅”时走分批节奏

这样可以降低瞬时 `RequestMarketData()` 洪峰和 `CheckRateLimiting()` 的集中阻塞。

### 3. 恢复日志改为批次摘要
保持关键日志，但不再对恢复期间每个 symbol 同时输出 `Subscribe Request` 和 `Subscribe Processed` TRACE。

新的日志策略：
- 恢复开始时输出：`Restoring data subscriptions in batches... total=N batchSize=M delayMs=K`
- 每批完成后输出：`Restored subscription batch X/Y size=S totalDone=T/N`
- 保留异常/跳过日志（例如 expired contract）
- 非恢复场景下的单 symbol 订阅仍可保留现有 TRACE

这样可以保留可观测性，同时避免恢复期数百行日志洪峰。

### 4. IB farm OK/idle 日志降噪
分两侧处理：

1. Python watchdog：
   - 对 `2104/2106/2107/2108/2158` 只记 `INFO`
   - 不再补一条 `ERROR ERROR -1 ...`
2. Lean C# brokerage：
   - `HandleError()` 识别同组消息时不再统一写入 TRACE
   - 改为 `Log.Debug` 或更简短的信息日志
   - 保持真正断连类消息（如 `2103/2105/1100`）的现有恢复触发逻辑不变

## 影响范围

### 修改文件
- `scripts/ib_gateway_watchdog.py`
- `backend/tests/test_ib_gateway_recovery.py`
- `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs`
- `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/InteractiveBrokersBrokerageAdditionalTests.cs`
- `deploy/systemd/stocklean-ibgateway-watchdog.service`（仅确认无需改值；若需说明则更新注释）

### 可能不改但需验证
- `backend/app/services/ib_gateway_runtime.py`
- `backend/tests/test_ib_gateway_runtime.py`

## 测试策略

### Python
1. `gateway_restart` 动作应调用 `systemctl --user restart --no-block ...`
2. 发起 `gateway_restart` 后，`runtime_health` 必须立即写成 `gateway_restarting`
3. `oneshot` watchdog 不再依赖外部 restart 完成即可成功退出

### C#
1. 恢复期间订阅应按批次节奏处理，而不是一次性处理全部 symbol
2. 恢复期间应输出批次摘要日志，而不是为每个 symbol 生成恢复 TRACE 洪峰
3. `2104/2106/2107/2158` 不应再被视为高噪音错误日志
4. 真正错误码（如 `2103/2105`）仍应保留恢复触发能力

## 验收标准

1. 新增测试先失败，修复后通过。
2. `watchdog` 在触发 `gateway_restart` 时不会再因 `TimeoutStartSec=30s` 被截断。
3. Lean bridge 恢复 `79` 个订阅时，日志表现为分批摘要，而不是每个 symbol 双 TRACE 洪峰。
4. `The IB API request has been rate limited.` 的出现频率明显下降，或至少不再与大规模恢复订阅洪峰一起出现。
5. 当前运行态仍能正常恢复到 `state=healthy`，交易阻断语义不回归。
