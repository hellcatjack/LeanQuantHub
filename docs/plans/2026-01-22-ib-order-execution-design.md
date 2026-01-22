# IB 下单闭环设计（扩展闭环）

## 目标
- 打通“决策快照 -> 订单生成 -> IB 下单 -> 回写成交 -> 批次状态”的闭环。
- 首期支持 MKT + LMT、部分成交累计、幂等 clientOrderId、风控阻断。
- 交易执行使用 IB 数据源，训练/回测仍使用 Alpha。

## 架构与数据流
1) UI/接口触发交易执行 -> 创建/获取 TradeRun。
2) 根据决策快照生成 TradeOrder 列表（已有 builder 逻辑）。
3) 订单提交到 IB：创建订单、监听 orderStatus/execDetails。
4) 回写 TradeOrder/TradeFill；更新 TradeRun 状态。
5) 批次结束后记录模型快照 ID 与参数版本。

数据流关键点：
- 订单幂等：clientOrderId = run_id + symbol + side（已有唯一约束）。
- 订单状态机：NEW -> SUBMITTED -> PARTIAL -> FILLED/CANCELED/REJECTED。
- 部分成交：fill 事件累计 fill_quantity 与 avg_fill_price。

## 错误处理与风控
- 提交失败：标记 REJECTED 并记录 reject_reason，批次进入 degraded。
- 行情异常/断线：可重试一次；不可重试错误直接失败并告警。
- 预交易风控：触发则阻止下单；盘中风控触发则停止后续订单。
- LMT 价格无法获取：按参数选择回退 MKT 或终止。

## 幂等与回写
- clientOrderId 固定规则，重复触发不重复下单。
- 订单回写包含：状态、filled_quantity、avg_fill_price、最后错误。
- 批次状态：done/partial/failed/halted；并记录执行时间。

## 测试与验收
- 单测：
  - 订单生成/校验
  - 幂等 clientOrderId
  - 部分成交累计与均价
- 接口测试：
  - 提交批次、查询状态
- 集成测试（Mock IB）：
  - 模拟 orderStatus/execDetails
  - 断线/超时 -> degraded

验收：
1) MKT/LMT 下单可追溯
2) 部分成交回写正确
3) 风控触发阻止后续订单
4) 幂等生效不重复下单

