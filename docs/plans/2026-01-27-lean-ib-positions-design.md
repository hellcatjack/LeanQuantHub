# Lean IB 持仓对齐设计

**目标**：实盘交易页面的持仓列表以 IB 账户持仓为权威，确保与 TWS 一致，并在 IB 不可用时可回退显示。

## 背景
当前 Lean Bridge 的 `positions.json` 由算法持仓生成，仅覆盖算法订阅标的，导致与 TWS 全量持仓严重不一致。需要改为使用 IB 账户持仓作为主来源。

## 方案（已确认）
**方案 A：以 IB 账户持仓为权威（推荐）**
- `BuildPositions` 优先使用 `IBrokerage.GetAccountHoldings()` 生成 `positions.json`。
- 若 brokerage 不可用/返回空，则回退到算法持仓（现有逻辑）。
- 增加 `source_detail` 字段用于标记来源：`ib_holdings` / `algorithm_holdings`。

## 数据流与结构
- **输入**：`IBrokerage.GetAccountHoldings()`
- **输出**：`/data/share/stock/data/lean_bridge/positions.json`
- **字段映射**：
  - `symbol` ← `Holding.Symbol.Value`
  - `quantity` ← `Holding.Quantity`
  - `avg_cost` ← `Holding.AveragePrice`
  - `market_value` ← `Holding.MarketValue`
  - `unrealized_pnl` ← `Holding.UnrealizedPnL`
  - `currency` ← `Holding.CurrencySymbol`
- **新增字段**：
  - `source_detail`: `ib_holdings` / `algorithm_holdings`

## 边界与回退策略
- IB 返回非空：使用 IB 持仓，`source_detail=ib_holdings`。
- IB 返回空且算法持仓非空：回退算法持仓，`source_detail=algorithm_holdings`。
- IB 返回空且算法持仓空：返回空列表，`source_detail=algorithm_holdings`（明确来源）。
- 仍保留 `refreshed_at` 与 `stale=false`，后续可扩展 IB 刷新判定。

## 测试与验证
- **单元测试（TDD）**：
  1) IB 有持仓，算法无持仓 → 输出包含 IB 标的。
  2) IB 空，算法有持仓 → 回退算法持仓。
  3) IB 空且算法空 → 输出空列表，`source_detail=algorithm_holdings`。
- **集成验证**：
  - 运行 Lean Bridge live/paper，核对 `positions.json` 与 TWS 持仓数量一致。
  - UI 实盘交易页显示与 TWS 对齐。

## 变更范围
- `Lean_git/Engine/Results/LeanBridgeResultHandler.cs`
- `Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs`（新增）

## 风险与缓解
- **IB 断线/缓存延迟**：回退算法持仓 + `source_detail` 明确来源。
- **误判空持仓**：仅在 IB 明确空且算法空时输出空列表。
