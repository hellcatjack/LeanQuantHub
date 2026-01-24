# Lean IB Bridge 统一执行与可视化设计

## 背景
当前系统在后端直接连接 IB（行情/账户/历史/执行），与计划中的 Lean IB 执行存在双通道与一致性风险。为实现全栈一致、可审计、可回放，决定以 Lean IB Brokerage 作为唯一执行通道，并通过 Lean 输出桥接文件提供账户/行情/成交可视化，后端不再直接调用 IB API。

## 目标
- 执行/账户/持仓/行情/订单/成交 **仅来自 Lean 输出**。
- 系统保留 IB 配置管理，但仅用于生成/更新 Lean 启动配置。
- 清理旧 IB 直连代码路径，避免并行数据源造成的冲突。
- 前端可清晰展示数据来源、更新时间、是否降级。

## 非目标
- 不改变研究/回测/信号现有 Alpha 数据源策略。
- 不在首期强制改造 Lean 的算法研究/回测入口。
- 不引入期权等复杂品种支持。

## 架构与数据流
1) **Lean 执行层**
- Lean 算法读取本系统生成的订单意图（CSV/JSON）并通过 IB Brokerage 执行。
- 自定义 ResultHandler 输出桥接文件到 `data/lean_bridge/` 或 `artifacts/lean_bridge/`（以可配置路径为准）。

2) **Bridge 输出（统一数据来源）**
- `account_summary.json`：账户摘要（净值、现金、购买力等）。
- `positions.json`：持仓明细。
- `quotes.json`：当前行情快照（可选，取决于 Lean 是否订阅）。
- `execution_events.jsonl`：订单/成交事件流。
- `lean_bridge_status.json`：输出状态与心跳（last_heartbeat/last_error/stale）。

3) **后端读取与缓存**
- 后端提供 `lean_bridge` 读取服务：解析文件、处理缺失/过期、缓存到内存或 DB。
- `/api/ib/*` 兼容层在首期保留，但改为读取 lean_bridge 输出（后续可迁移为 `/api/brokerage/*`）。

4) **前端展示**
- LiveTrade 页面以 lean_bridge 作为数据源，显示数据来源与更新时间。
- 连接状态与降级信息由 `lean_bridge_status.json` 驱动。

## 配置管理策略
- UI/DB 继续管理 IB 配置：host/port/client_id/account_id/mode。
- 后端将配置写入 Lean 启动配置（如 `Launcher/config.json` 或运行参数），保证单一来源。
- 前端显示需明确“配置用于 Lean 执行”，并对敏感字段做掩码。

## 错误处理与降级
- 当 bridge 文件不存在或超时，API 返回 `stale=true`，并展示“数据滞后/连接未更新”。
- 不触发任何 IB 直连回退，避免双通道数据不一致。

## 安全与审计
- 配置敏感字段前端仅显示掩码。
- 订单/成交事件通过桥接文件记录，可追溯。
- 后端审计日志记录配置变更与执行调用。

## 测试与验证
- 后端：bridge 读取服务单测（正常/缺失/过期/损坏 JSON）。
- 前端：Playwright 验证 LiveTrade 页面在 bridge 数据存在时正确展示与不溢出布局。
- 端到端：Lean 输出桥接文件后，系统 UI 账户/持仓/成交可正确显示。

## 清理范围（旧 IB 直连）
- 删除/迁移：`backend/app/services/ib_*`（market/stream/history/execution/order_executor/health/status_overview）。
- 删除脚本：`scripts/run_ib_stream.py`。
- 路由：`backend/app/routes/ib.py` 改为 lean_bridge 兼容层或迁移到 `brokerage` 路由。
- 前端：`LiveTradePage.tsx` 相关接口调用替换为 lean_bridge 数据源。

## 风险与应对
- **Lean 输出不稳定**：以 `lean_bridge_status.json` 心跳为准，UI 提示降级。
- **迁移期 API 兼容**：保留 `/api/ib/*` 但内部走 bridge，降低前端改动风险。
- **数据时效性**：明确展示更新时间，避免“看似实时”的误解。
