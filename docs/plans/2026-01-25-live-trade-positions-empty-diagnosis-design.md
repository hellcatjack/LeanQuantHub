# 实盘交易-持仓空态诊断提示设计

## 背景
实盘交易页当前持仓为空时，用户难以判断是否为 Lean Bridge 数据过期导致。需要增加轻量诊断提示，辅助确认桥接状态并提供刷新入口。

## 目标
- 仅在“持仓为空且 Lean Bridge 过期（stale）”时显示提示，避免干扰。
- 提供明确可操作的刷新入口，并展示最近心跳/更新时间。
- 不改变原有表格与空态展示逻辑，仅增强诊断信息。

## 非目标
- 不引入新的后端接口。
- 不对 Lean Bridge 采集/写入流程做修改。
- 不改变持仓表格的数据结构或字段。

## 触发条件
- `accountPositions.length === 0` 且 `bridge stale === true` 时显示。
- `ibOverview` 不可用时，不显示诊断提示（避免误判）。

## 展示位置与样式
- 位置：持仓卡片标题与 meta 之间，或标题后紧邻区域。
- 样式：使用现有“提示/告警”视觉风格（黄底提示条或 `form-hint` + `warn` 语义）。
- 不阻断表格渲染，空态仍使用现有文案。

## 文案
- 中文："持仓为空且数据已过期，可能是 Lean Bridge 未更新。请检查 Lean 运行状态或点击刷新。"
- 英文："Positions are empty and data is stale. Lean Bridge may not be updating. Check Lean status or click refresh."

## 数据来源
- `ibOverview`：用于判断 stale 与展示时间。
  - `bridgeUpdatedAt` 或 `ibOverview.connection.last_heartbeat` 作为“最近心跳/更新时间”。
- `accountPositions`：用于判断是否为空。

## 交互
- 提示条内提供“刷新持仓”按钮，触发 `loadAccountPositions()`。
- 若无可用时间字段，显示“无/none”。

## 测试策略（TDD）
- Playwright 用例 1（正向）：mock `ibOverview` stale + positions 为空，断言提示条可见。
- Playwright 用例 2（反向）：stale=false 或 positions 非空，断言提示条不可见。

## 风险与权衡
- 文案过细可能暴露实现细节 → 保持提示简洁、强调操作。
- ibOverview 缺失时不提示，可能延后诊断 → 避免错误提示优先。
