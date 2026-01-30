# Lean IB 执行算法设计

## 背景
当前交易执行通过 Lean 启动，但算法为 `LeanBridgeSmokeAlgorithm`，仅输出桥接数据与心跳，不会读取 `execution-intent` 下单，导致 TWS 无实际交易记录。需要新增一个执行型算法，满足“quantity 优先、weight 兜底”的下单策略，并保持桥接状态输出。

## 目标
- 在 Lean Live 环境中读取 `execution-intent-path` 并下单。
- 支持 quantity 与 weight 两种语义（quantity 优先）。
- 确保只执行一次，防止重复下单。
- 保留现有桥接输出（状态/行情/账户）。

## 非目标
- 不实现订单回写 DB（后续由 bridge 事件处理）。
- 不支持限价/止损等复杂订单类型（先仅 MKT）。

## 架构与数据流
1. 后端生成 `trade_run_{id}.json`，填入 `execution-intent-path`。
2. Lean 启动 `LeanBridgeExecutionAlgorithm`：
   - 在 `Initialize()` 中读取 intent 文件。
   - 订阅 symbol，选择执行路径（quantity / weight）。
   - 仅执行一次下单。
3. Lean ResultHandler 继续输出 bridge 文件（状态/账户/行情）。

## 执行规则
- **quantity 优先**：若 item 含 `quantity` 且 >0，执行 `MarketOrder(symbol, quantity)`。
- **weight 兜底**：quantity 缺失或 <=0 时，若 `weight` >0，则执行 `SetHoldings(symbol, weight)`。
- **字段缺失处理**：`symbol` 缺失或为空 → 跳过并记录 warning。
- **weight 总和**：不做强制归一，超 1 或不足 1 仅记录 warning。
- **执行次数**：使用 `executed` 标志（内存标志即可），避免重复下单。

## 错误处理与安全约束
- intent 文件不存在或 JSON 解析失败：记录错误并退出下单流程。
- intent 为空：记录 `intent_empty`，不下单。
- `order_type` 字段出现时记录日志，但忽略（仅支持 MKT）。
- 日志不输出账户敏感信息，仅记录 symbol/qty/weight。

## 测试与验证
1. **C# 单元测试**（最小 JSON）：
   - quantity 优先路径
   - weight 路径
   - symbol 缺失跳过
   - intent 空列表
2. **后端配置测试**：
   - `build_execution_config` 输出 `algorithm-type-name=LeanBridgeExecutionAlgorithm`
   - `execution-intent-path` 被正确写入
3. **端到端验证**：
   - 生成 `trade_run` + `order_intent`（AAPL qty=1）
   - 启动 Lean 执行
   - Lean 日志出现 “EXECUTED_ONCE / MarketOrder AAPL 1”
   - TWS Paper 账户出现订单记录

## 验收标准
- TWS（Paper）可看到下单记录。
- Lean 日志明确记录执行路径与一次性执行标志。
- 后端 `trade_run` 能成功触发 Lean 执行，配置正确。
