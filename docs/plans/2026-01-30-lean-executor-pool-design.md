# Lean 执行器常驻池（Leader 独占）设计

> 目标：将实盘/模拟盘下单延迟稳定控制在 <1s；确保 Lean Bridge 数据稳定可用；不触碰 IBKR API 限制。

## 背景与结论
- Lean 执行器 ≠ Lean Bridge：执行器是进程，Bridge 是输出文件与监控层。
- 采用 **每个模式 10 个常驻执行器池**，其中 **1 个 Leader 独占 Bridge** 输出目录，其余 Worker 只下单。
- 不触碰 IB 限制的策略：Leader 独占行情订阅，Worker 禁止行情订阅与历史请求；连接数与请求速率限制可配置。

## 核心设计

### 1) 角色划分
- **Leader**：唯一写入 `lean_bridge/` 目录（positions/account_summary/quotes/status）。
- **Worker**：仅执行订单，不写入共享 bridge 目录。

### 2) 池管理器（后端内托管）
- 启动时为 paper/live 各拉起 10 个 Lean 进程。
- 每个实例有独立输出目录：`/data/share/stock/data/lean_bridge/pool_{mode}_{client_id}/`
- Leader 输出目录固定为 `lean_bridge/`（权威数据来源）。

### 3) 健康监测
- 每 5s 读取实例 `lean_bridge_status.json` 与进程存活状态：
  - `last_heartbeat`、`ib_connected`、`error_count`、`pid_alive`、`last_order_at`
- Leader 采用更严格阈值（例如 20s 未心跳即 stale）。

### 4) 异常处理策略
- **Degraded**：延迟但仍可用，继续观察。
- **Stale**：超过阈值，自动重启 Leader。
- **Dead**：进程退出，直接重启补位。
- Leader 连续失败 3 次：自动晋升 Worker 为新 Leader，记录切换事件。
- 下单只选 healthy Worker，Leader 异常不阻断下单（仅桥接数据降级）。

### 5) IB 限制规避（必须）
- 只允许 Leader 订阅行情与快照。
- Worker 禁止市场订阅/历史拉取。
- 限流（pacing）统一后端控制（按 market data lines 计算）。
- 连接数上限可配置，默认不超过 10，并预留给其他工具。

> 注：IBKR API 连接数与行情订阅上限需再核验（以官方文档为准），设计上已提供保守限流与配置入口。

## UI/可观测性

### Bridge Pool 子页面
- 位置：Live Trade → Bridge Pool
- 列表字段：mode/role/client_id/pid/status/last_heartbeat/last_order_at/output_dir/last_error
- 事件流：重启/切换/剔除/恢复
- 概览：Leader 状态、可用实例数、平均下单延迟

### 操作权限
- 默认只读
- 提供“重启 Leader / 重启 Worker”
- “强制重置池”需二次确认 + live_confirm_token

## 数据模型（建议）

### 表 1：lean_executor_pool
- id
- mode (paper/live)
- role (leader/worker)
- client_id
- pid
- status (healthy/degraded/stale/dead)
- last_heartbeat
- last_order_at
- output_dir
- last_error
- created_at/updated_at

### 表 2：lean_executor_events
- id
- type (restart/switch/reap/health)
- mode
- client_id
- detail
- created_at

## 成功标准（Acceptance Criteria）
- 订单从点击到 TWS 可见 <1s（稳定）。
- Leader 异常不影响下单；仅桥接数据标记 stale。
- 页面可查看每个执行器健康状态与事件记录。
- 不触碰 IB 限制（无多实例行情订阅、限流生效）。

