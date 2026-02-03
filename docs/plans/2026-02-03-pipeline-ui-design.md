# 交易 Pipeline 可视化设计（实盘交易页）

## 背景与目标
- 目标：在「实盘交易」页新增 Pipeline 子标签，以“时间轴 + 事件流”展示每周一自动交易与手动 PreTrade/Trade Run 的完整链路。
- 核心诉求：可审计、可回溯、可重试，清晰揭示“哪里卡住、为什么失败、如何重试”。
- 参考方向：QuantConnect 的运行流与输出视图理念 + 主流专业量化平台的审计与回溯体验。

## 范围
- 覆盖类型：
  - 每周一自动交易（Automation Weekly）
  - 手动 PreTrade / Trade Run
- 最小审计粒度：子任务级（PIT Job / 训练作业 / 交易批次 / 订单等）。

## 总体信息架构
- 页面入口：实盘交易 → Pipeline 子标签。
- 左侧：Run 列表（按时间倒序）。
- 右侧：Run 详情（时间轴 + 事件流）。
- 顶部：过滤器（项目/模式/状态/日期范围/关键ID）。

## 视觉与交互方案（时间轴 + 事件流）
- 形态：阶段泳道（Stage Lanes）+ 时间轴事件节点。
- 阶段分组：
  1) 数据准备（PIT 周度/基本面/训练评分）
  2) 评分/快照（Decision Snapshot）
  3) 交易前检查（Bridge Gate / 市场快照）
  4) 下单执行（Trade Run / 批次 / 订单 / 成交）
  5) 审计归档（日志/产物/事件）
- 事件节点最小显示：状态、任务类型、ID、开始/结束/耗时、项目/模式。
- 事件详情抽屉：
  - 参数快照（JSON）
  - 产物路径/日志路径
  - 错误码/原因
  - 重试入口
- 关系追踪：节点之间用细线标识“父子/重试/关联”。
- 搜索：输入 order_id / run_id / snapshot_id 高亮相关链路。

## 数据模型（事件流 DTO）
- 字段建议（可先聚合，不必落库）：
  - trace_id / event_id / parent_id / retry_of
  - project_id / mode / run_type
  - stage / task_type / task_id
  - status / message / error_code
  - started_at / ended_at / duration
  - artifact_paths / log_path / params_snapshot

## 后端聚合 API
- `GET /api/pipeline/runs`：Run 列表（支持 project_id、mode、status、date_range、type）。
- `GET /api/pipeline/runs/{trace_id}`：事件流详情（按时间排序，阶段分组）。
- `POST /api/pipeline/events/{event_id}/retry`：触发重试（映射到具体子任务）。

## 数据来源映射
- Automation Weekly: `auto_weekly_jobs` → 数据准备/回测
- PreTrade: `pretrade_runs` / `pretrade_steps`
- Decision Snapshot: `decision_snapshots`
- Trade Execution: `trade_runs` / `trade_orders` / `trade_fills`
- 审计：`audit_log`

## 错误处理与重试策略
- 失败原因强制记录：error_code + message。
- 重试不会覆盖历史：新增事件，保留原失败节点。
- 可恢复任务支持自动重试（指数退避），UI 展示下一次重试时间。

## 验收标准
1) 任意一次 Run 能回放完整阶段与子任务事件流。
2) 失败事件可查看原因、日志与产物路径。
3) 重试产生新事件，并保留历史链路。
4) 通过 order_id/run_id/snapshot_id 能定位并高亮全链路。

## 风险与约束
- 不破坏现有运行/执行流程，仅聚合展示。
- 事件流初期允许“实时 + 定时刷新”混合，但需保证一致性与审计完整。

