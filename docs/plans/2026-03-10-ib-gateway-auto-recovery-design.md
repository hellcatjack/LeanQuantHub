# IB Gateway 半挂自动恢复设计

## 背景
在执行交易批次后，页面出现“当前持仓不显示”，同时观察到 IB Gateway 有卡死迹象。现有系统已经具备以下能力：
- `lean bridge` 心跳与快照文件
- `positions/open_orders/account_summary` 读取与部分 `ibapi fallback`
- `stocklean-ibgateway.service` 通过 IBC 托管 Gateway
- `stocklean-ibgateway-watchdog.timer` 定时执行低层看门狗

但当前健康判定仍然偏向“进程活着、端口可连、心跳在跳”，没有把“命令是否继续被消费、快照是否继续前进、直连 `reqPositions` 是否成功”纳入同等级别判断。因此会出现一种典型半挂状态：
- Gateway Java 进程仍在
- `lean_bridge_status.json` 仍有 heartbeat
- `commands/` 中新命令不再出结果
- `positions/open_orders/account_summary` 长时间停在旧时间
- 页面在一次刷新失败后清空当前持仓

## 当前确认
### Gateway 管理方式
当前主机使用用户级 `systemd` 服务 `stocklean-ibgateway.service` 管理 Gateway，`ExecStart` 通过 IBC 的 `gatewaystart.sh -inline` 启动；系统级 `/etc/systemd/system/ibgateway.service` 处于 `disabled/inactive`，不存在双重管理。

### 重启可靠性
当前用户级 service 具备：
- `KillMode=control-group`
- `TimeoutStopSec=30`
- `SendSIGKILL=yes`
- `FinalKillSignal=SIGKILL`

因此 `systemctl --user restart stocklean-ibgateway.service` 会终止整个 IBC/Gateway cgroup，而不是只杀外层 shell。对“Gateway 假死但进程仍在”的情况，重启动作本身是可靠的。

### 当前缺口
现有 `scripts/ib_gateway_watchdog.sh` 只检测：
- service 是否 active
- `ibcalpha.ibc.IbcGateway` 进程是否存在
- API 端口是否可连接
- `ESTAB/CLOSE-WAIT` 数量是否异常

它无法识别以下业务级故障：
- bridge 快照停止前进
- commands 队列持续积压
- `reqPositions` 业务请求超时
- 持仓接口退化为 stale/空列表

## 目标
- 准确识别“Gateway 半挂但未真正退出”的状态。
- 在连续探测失败后，优先通过现有 `systemd user service` 自动重启 Gateway。
- 在恢复期间阻止新的交易批次与新下单，保留取消与状态同步能力。
- 页面始终保留“最后一次可信持仓”，避免单次刷新失败直接清空。
- 故障原因、恢复动作、恢复结果具备审计与可观测性。

## 非目标
- 不重构现有 Lean bridge 基础架构。
- 不引入新的进程编排器替代 `systemd + IBC`。
- 不在本期处理所有 IB 连接问题，只聚焦“Gateway 半挂/卡死导致持仓与命令链路失真”的闭环。

## 方案选择
### 方案 A：仅做前端兜底
优点：改动小。
缺点：只能隐藏症状，不能自动恢复 Gateway。

### 方案 B：分级自愈，推荐
将“业务探针 + bridge 状态 + systemd/IBC 重启”串成状态机。先做轻量恢复，再升级到 Gateway 重启。

### 方案 C：外部 supervisor 全接管
优点：长期最强。
缺点：当前侵入面过大，不适合这次问题的最短闭环。

**最终选择：方案 B。**
原因：能直接修正本次误判点，复用现有 `systemd + IBC` 管控链路，且不需要替换现有部署模型。

## 核心方案
### 一、引入业务级 Gateway 运行健康状态
新增统一运行健康快照 `gateway_runtime_health`，由后端服务与 watchdog 共用，状态建议为：
- `healthy`
- `snapshot_stale`
- `command_stuck`
- `bridge_degraded`
- `gateway_restarting`
- `gateway_degraded`
- `recovering`

其中：
- `snapshot_stale` 表示 bridge 心跳可能还活，但账户/持仓/委托快照停止前进。
- `command_stuck` 表示命令目录存在超时未消费命令，或 `command_results` 长时间无新增。
- `gateway_degraded` 表示已达到自动恢复上限，禁止新交易，等待人工关注或后续成功恢复。

### 二、探针信号来源
运行健康判断必须综合以下信号，而不是只看 heartbeat。

#### 1. bridge 文件与时间戳
读取：
- `lean_bridge_status.json`
- `positions.json`
- `open_orders.json`
- `account_summary.json`
- `lean_bridge_refresh.json`

检查项：
- heartbeat 是否超时
- `positions/open_orders/account_summary` 是否在阈值内更新
- `source_detail` 是否落入错误类型

#### 2. commands / command_results 进度
读取 bridge 根目录下：
- `commands/`
- `command_results/`

检查项：
- pending command 数量
- 最老 pending command 年龄
- 最近 command_result 时间
- command_id 是否长期未出结果

如果出现“heartbeat 新鲜，但 command 长时间不出结果”，直接判为 `command_stuck`。

#### 3. 直连 `reqPositions` 探针
使用现有 `ibapi` 读会话能力进行短超时业务探针，确认：
- 是否能够从 Gateway 直接拿到 positions
- 耗时是否超阈值
- 是否连续失败

该探针是“Gateway 是否真的可服务”的最终判据，优先级高于单纯端口可连。

### 三、分级恢复梯度
恢复策略按“由轻到重”执行，避免重启风暴。

#### 第 1 级：bridge refresh
触发：首次出现 `snapshot_stale` 或 `command_stuck`。
动作：
- 强制执行 bridge refresh
- 记录审计 `brokerage.gateway.recovery_attempt`

#### 第 2 级：重启 lean bridge leader
触发：连续第二次业务探针失败，且 Gateway 端口/进程仍正常。
动作：
- 强制执行 `ensure_lean_bridge_leader(..., force=True)`
- 重新观测快照前进与 command 消费

#### 第 3 级：重启 IB Gateway
触发：连续第三次业务探针失败，或直连 `reqPositions` 连续失败达到阈值。
动作：
- 通过 `systemctl --user restart stocklean-ibgateway.service` 重启
- 仍由 IBC 拉起 Gateway，不直接 `pkill java`
- 写审计 `brokerage.gateway.restart`
- 状态进入 `gateway_restarting`

#### 第 4 级：冻结新交易
触发：Gateway 重启后仍未恢复，或在冷却窗口内多次失败。
动作：
- 状态升级为 `gateway_degraded`
- 禁止新的批次执行、直接买卖、手工新单
- 保留取消、同步、查看状态、查看持仓历史快照
- 前端明确提示“系统正在等待 Gateway 恢复”

### 四、冷却与防抖
必须对每种恢复动作设置独立冷却：
- `bridge refresh`：秒级
- `leader restart`：分钟级
- `gateway restart`：更长的分钟级冷却

同一窗口内，只有在状态未恢复时才允许升级到下一级动作。

## systemd / IBC 集成原则
### 复用现有用户级服务
Gateway 自动恢复只允许通过：
- `stocklean-ibgateway.service`
- `stocklean-ibgateway-watchdog.service`
- `stocklean-ibgateway-watchdog.timer`

不新增第二套 Gateway manager，不启用系统级 `ibgateway.service`。

### 保留 shell 入口，增强业务探针
现有 `scripts/ib_gateway_watchdog.sh` 可以保留为 service 入口，但内部应改为调用 Python 业务探针/恢复逻辑，避免在 shell 中堆积复杂状态机。

推荐结构：
- shell 脚本仍作为 systemd `ExecStart`
- shell 脚本调用 Python helper
- Python helper 复用 backend service 中的健康判定逻辑

这样可以保证：
- `systemd` 仍负责真正的 restart
- 业务级判断逻辑可测试、可在 API/UI 中复用

## 交易保护策略
### 需要阻止的动作
当状态为 `gateway_restarting` 或 `gateway_degraded` 时，阻止：
- 交易批次执行
- 页面持仓区的买入/卖出/批量平仓/全部清仓
- 手工新单

### 允许的动作
保留以下能力：
- 查看状态
- 查看最后可信持仓
- 同步订单/回执
- 取消现有未完成订单
- 人工触发恢复或刷新状态

### 后端拦截点
至少拦截：
- `execute_trade_run`
- `submit_direct_order`
- `execute_manual_order`

错误码统一为可解释的业务状态，例如：
- `gateway_degraded`
- `gateway_restarting`

## 前端行为
### 持仓展示
页面不再因为单次加载失败而把持仓表清空，而是：
- 保留最后一次 `stale=false` 的可信持仓
- 标记为 `stale/unverified`
- 展示：
  - 最后可信更新时间
  - 当前运行健康状态
  - 最近一次恢复动作

### 操作按钮
当运行健康状态进入 `gateway_restarting` 或 `gateway_degraded` 时：
- 禁用执行与新下单按钮
- 允许刷新、同步、取消
- 展示恢复中的横幅或告警卡片

### 管理视图
在实盘页面或 brokerage 面板中增加：
- Gateway 运行健康状态
- 连续失败次数
- 最近恢复动作 / 时间
- 是否已触发 systemd restart

## 可观测性与审计
### 状态快照
新增一个运行时状态文件，建议放在 bridge 根目录，例如：
- `gateway_runtime_health.json`

内容至少包含：
- 当前状态
- failure_count
- pending_command_count
- oldest_pending_command_age_seconds
- last_positions_at
- last_open_orders_at
- last_account_summary_at
- last_command_result_at
- last_probe_result
- last_recovery_action
- last_recovery_at
- next_allowed_action_at

### 审计日志
新增审计事件：
- `brokerage.gateway.recovery_attempt`
- `brokerage.gateway.leader_restart`
- `brokerage.gateway.restart`
- `brokerage.gateway.recovered`
- `brokerage.gateway.degraded`

## 实施边界
### 不做数据库迁移
本期先不新增数据库表。运行态信息落在 bridge 根目录 JSON 文件，长期事件写 `audit_log`。

### 不变更 Gateway manager 归属
仍使用：
- IBC 负责拉起 Gateway
- systemd user service 负责生命周期
- backend 负责业务级探针与状态解释

## 验收标准
- 当 heartbeat 仍在但 `commands` 不再被消费、快照长时间不前进时，系统能判定非健康。
- 连续失败达到阈值后，系统通过 `systemctl --user restart stocklean-ibgateway.service` 自动重启 Gateway。
- Gateway 重启期间，新交易批次和新下单被阻止，取消操作仍可执行。
- 前端不会因单次持仓刷新失败而直接清空表格，而是显示最后可信持仓并标记 stale。
- 恢复成功后，系统状态自动回到 `healthy`，并写入恢复审计日志。
- 整个恢复过程具备可观察的状态文件、API 输出和 UI 提示。

## 风险与缓解
### 风险 1：重启风暴
缓解：分级动作 + 冷却窗口 + 失败计数重置规则。

### 风险 2：误判导致过度保护
缓解：业务探针至少连续失败多次才升级到 Gateway restart；单次失败只做 refresh/leader restart。

### 风险 3：前端保留旧持仓引起误解
缓解：明确区分“当前可信持仓”和“最后可信持仓”，并显示 stale 标记与时间。

### 风险 4：backend 不可用时无法执行业务探针
缓解：保留现有低层 `bash watchdog` 基本检测；业务级探针失败时至少仍能依赖 systemd + IBC 的基础恢复能力。
