# Lean IB Bridge 统一执行与可视化设计

## 背景
当前系统已迁移为 `/api/brokerage/*` 路由，后端不再直接调用 IB API，但 Lean 侧尚未输出 bridge 文件，导致实盘交易页无法展示账户/持仓/行情。为实现全栈一致、可审计、可回放，决定以 **Lean IB Brokerage + 自定义 ResultHandler** 作为唯一执行与状态输出通道，由桥接文件向系统供数。

## 目标
- 执行/账户/持仓/行情/订单/成交 **仅来自 Lean 输出**。
- 账户与行情可视化 **通过 Lean 输出/日志/事件桥接**，不依赖 TWS 页面。
- 系统保留 IB 配置管理，但仅用于生成/更新 Lean 启动配置。
- 前端清晰展示数据来源、更新时间、是否降级。

## 非目标
- 不改变研究/回测/信号现有 Alpha 数据源策略。
- 首期不强制改造 Lean 研究/回测入口。
- 不引入期权等复杂品种支持。

## 架构与数据流
1) **Lean 执行层**
- Lean 算法读取本系统生成的订单意图（CSV/JSON）并通过 IB Brokerage 执行。
- 自定义 `LeanBridgeResultHandler` 包装 `LiveTradingResultHandler`，既保留 Lean 原生统计输出，又追加 bridge 文件输出。

2) **Bridge 输出（统一数据来源）**
- 输出目录：默认 `/data/share/stock/data/lean_bridge`，可由 Lean 配置项覆盖（调试/隔离用）。
- 文件契约：
  - `account_summary.json`：账户摘要（净值/现金/购买力等，含 `asof`）。
  - `positions.json`：持仓明细（symbol/qty/avg_cost/market_value/unrealized_pnl/currency）。
  - `quotes.json`：行情快照（symbol -> bid/ask/last/ts）。
  - `execution_events.jsonl`：订单/成交事件流（逐行追加）。
  - `lean_bridge_status.json`：心跳 + last_error + degraded + last_heartbeat。

3) **后端读取与展示**
- 统一由 `lean_bridge_reader` 读取 bridge 文件，提供 `/api/brokerage/*`。
- TTL 判断：`now - last_heartbeat` 超过阈值标记 `stale=true`。
- LiveTrade 页面展示 `source=lean_bridge`、更新时间与降级提示。

## 写入策略（防止半写入/性能抖动）
- 所有 JSON 写入采用 **临时文件 + 原子 rename**。
- `quotes/positions/status` 采用节流（1–2s）与批量更新。
- `execution_events.jsonl` 追加写入（按事件流分行）。

## 配置管理策略
- UI/DB 继续管理 IB 配置：host/port/client_id/account_id/mode。
- 后端将配置写入 Lean 启动配置（单一来源），并注入 `lean-bridge-output-dir`。
- 前端配置页对敏感字段做掩码展示。

## 错误处理与降级
- Lean 侧写入异常：记录到 `lean_bridge_status.json` 的 `last_error` 与 `last_error_at`，同时标记 `degraded=true`。
- 后端读取不到文件或 TTL 过期：返回 `stale=true`，不抛 500。
- 前端显式提示“桥接未更新/已降级”。

## 测试与验证
- Lean 侧（最小单测）：ResultHandler 写出 `account_summary/positions/quotes/status`，校验字段与原子写。
- 后端：bridge 读取缺失/过期/损坏 JSON 的单测，`stale` 状态正确。
- 前端：Playwright 验证 LiveTrade 页面更新与降级提示、表格不溢出。
- 端到端：TWS + Lean Live 启动后，bridge 文件 5s 心跳刷新，UI 可见更新。

## 清理范围（旧 IB 直连）
- 已完成：`/api/ib/*` 路由移除，迁移至 `/api/brokerage/*`。
- 后续仅保留桥接读取，不新增任何 IB 直连回退。

## 风险与应对
- **Lean 输出不稳定**：以 `lean_bridge_status.json` 心跳为准，UI 提示降级。
- **I/O 性能压力**：节流写入 + 原子替换，避免阻塞交易线程。
- **数据时效性误解**：UI 明示更新时间与 stale 状态。
