# 交易执行闭环与可视化增强设计（C+D 优先）

## 背景与差异评估
根据 `docs/todolists/IBAutoTradeTODO.md`，当前系统已具备：`trade_runs/trade_orders/trade_fills` 数据结构、批次创建与执行入口、基础订单列表与批次列表。核心差距集中在 **订单状态/成交回写闭环** 与 **可视化（C 订单/成交明细 + D 目标偏离对比）**。此外，LMT 订单类型未覆盖。

## 目标
- **闭环正确性**：订单状态机（NEW→SUBMITTED→PARTIAL→FILLED/CANCELED/REJECTED）可回写并可追溯；成交明细写入 `trade_fills`。
- **可视化可用性**：展示订单/成交明细与“目标权重 vs 成交偏离”对比，优先满足 C+D。
- **扩展性**：为 LMT、撤单与更多执行细节预留字段与接口。

## 分阶段路径（并行分轨）
- **Phase 1：闭环回写（轨 A）**
  - IB orderStatus / execDetails 回写 `trade_orders`/`trade_fills`。
  - 订单状态与成交明细可查询。
- **Phase 2：规则完善（轨 B）**
  - LMT 订单支持、限价验证与滑点校验。
- **Phase 3：可视化增强（轨 C）**
  - 订单/成交明细 + 目标偏离对比完整落地。

## 架构与数据流
1) **批次生成**：从 decision snapshot 读取目标权重 → 生成订单草案（trade_orders）。
2) **下单执行**：IB 下单后订阅 orderStatus/execDetails → 实时写回订单状态与成交明细。
3) **偏离评估**：聚合 fills（按 symbol）并结合目标权重 → 计算 `fill_ratio`、`delta_value`、`delta_weight`。

## 数据模型与字段口径
- `trade_orders`：status、filled_quantity、avg_fill_price、ib_order_id、rejected_reason
- `trade_fills`：fill_quantity、fill_price、commission、exchange、exec_id、fill_time
- **目标权重**：来自 decision snapshot（CSV）或 run.params（如已固化）。
- **成交汇总**：按 symbol 聚合 fills。
- **偏离**：`target_value - filled_value`；`delta_weight` 以同一 portfolio_value 计算。

## API 设计
- `GET /api/trade/runs/{run_id}/detail`
  - 返回 run + orders + fills（分页）+ last_update_at
- `GET /api/trade/runs/{run_id}/symbols`
  - 返回 symbol 级汇总：target/filled/delta/fill_ratio + last_update_at
- `GET /api/trade/fills?run_id=...` 或 `GET /api/trade/orders/{id}/fills`
  - 订单维度成交明细分页

## UI 设计（C+D）
- **执行概览卡**：run 状态、完成率、异常统计、刷新时间。
- **偏离对比表（D）**：目标权重/目标市值 vs 成交市值/完成率，支持排序与颜色标记。
- **订单/成交明细（C）**：Orders / Fills Tab，支持状态筛选与订单行展开查看 fills。

## 测试与可观测
- 后端单测：IB 回写→订单状态/成交写入；symbols 汇总正确性。
- 前端单测：批次切换与偏离/成交表渲染；无回写提示。
- 审计日志：`trade_order.status_change` 与 `trade_fill.created` 记录。

## 风险与约束
- 没有实时回写将导致 UI 只能展示“目标”而非真实成交。
- IB API 回调存在时序不确定性，需要去重与幂等处理。
