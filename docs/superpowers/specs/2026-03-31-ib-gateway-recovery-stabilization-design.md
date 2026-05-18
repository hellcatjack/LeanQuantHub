# IB Gateway 恢复链路稳态化设计

## 背景
`2026-03-31 15:35` 到 `15:45 EDT` 出现宿主机 CPU 持续上升并在 `15:40 EDT` 达峰的事件。日志与 Prometheus 时间线表明，主因不是磁盘 IO 或 Kubernetes 批任务，而是 IB Gateway watchdog 连续触发 `bridge_refresh -> leader_restart -> gateway_restart`，进而放大了 Lean bridge 的账户回灌、订阅恢复和日志洪峰。

当前问题集中在两点：

1. 直连 probe 阈值过低，盘中短时抖动会被快速记为失败。
2. `leader_restart/gateway_restart` 后缺少恢复静默窗口，系统在恢复尚未完成时继续探活并再次升级动作。

## 目标

1. 降低 watchdog 对瞬时慢探针的误判概率。
2. 在 `leader_restart/gateway_restart` 后提供明确的恢复静默窗口，避免恢复风暴。
3. 只有在 `probe` 失败且业务快照/命令链路也表现异常时，才升级到 `bridge_degraded`。
4. 保持现有交易阻断语义：真正恢复期和真正降级期仍然阻止下单。

## 非目标

1. 本轮不拆分 `stocklean-backend.service` 与 Lean bridge 进程。
2. 本轮不实现订阅恢复分批化。
3. 本轮不调整前端展示逻辑。

## 方案

### 1. 提高默认探针阈值
在 `backend/app/core/config.py` 中显式声明并上调这组默认值：

- `ib_gateway_runtime_probe_timeout_seconds = 1.5`
- `ib_gateway_runtime_probe_hard_timeout_seconds = 5.0`
- `ib_gateway_restart_cooldown_seconds = 900`
- `ib_gateway_recovery_quiet_period_seconds = 240`

这样可以把瞬时盘中抖动和真实不可用区分开。

### 2. 收紧 `bridge_degraded` 判定
`build_gateway_runtime_health()` 不再仅因连续 probe 失败就进入 `bridge_degraded`。新的判定为：

- `bridge.stale = true`，直接判 `bridge_degraded`
- 否则必须同时满足：
  - `probe_ok is False` 且达到连续失败阈值
  - 并且存在 `snapshot_stale` 或 `command_stuck`

这能避免“探针慢，但快照仍在前进”的场景被误判为桥接退化。

### 3. 新增恢复静默窗口
在 watchdog 中新增 `_recovery_quiet_period_active()`：

- 若上一轮动作为 `leader_restart` 或 `gateway_restart`
- 且 `now < last_recovery_at + ib_gateway_recovery_quiet_period_seconds`
- 则进入恢复静默期

静默期内规则：

- 若本轮 `runtime_health.state == healthy`：沿用现有 `gateway_restarting -> recovering -> healthy` 过渡
- 若本轮仍不健康：
  - 不增加 `recovery_failure_count`
  - 不执行 `bridge_refresh/leader_restart/gateway_restart`
  - 若上一轮是 `gateway_restart`，状态保持 `gateway_restarting`
  - 若上一轮是 `leader_restart`，状态保持 `bridge_degraded`

这一步的核心是避免恢复中的系统再次被它自己的 watchdog 打断。

## 影响范围

### 修改文件
- `backend/app/core/config.py`
- `backend/app/services/ib_gateway_runtime.py`
- `scripts/ib_gateway_watchdog.py`
- `backend/tests/test_ib_gateway_runtime.py`
- `backend/tests/test_ib_gateway_recovery.py`

### 不修改文件
- 前端页面与样式
- 交易执行器与风控逻辑
- systemd unit 配置

## 测试策略

1. `ib_gateway_runtime`：
   - 连续 probe 失败但快照新鲜时，不应进入 `bridge_degraded`
   - 连续 probe 失败且快照停滞时，才进入 `bridge_degraded`

2. `ib_gateway_recovery`：
   - `leader_restart` 后静默窗口内再次不健康，不应升级到 `gateway_restart`
   - `gateway_restart` 后静默窗口内再次不健康，不应重复 restart
   - 静默窗口过后，若依然异常，升级链路恢复正常

## 验收标准

1. 新增测试先失败、修复后通过。
2. watchdog 在恢复静默窗口内不会重复升级恢复动作。
3. 单纯 probe 失败但 snapshot 正常推进时，不会把状态升级为 `bridge_degraded`。
4. 现有健康恢复路径与交易阻断测试不回归。
