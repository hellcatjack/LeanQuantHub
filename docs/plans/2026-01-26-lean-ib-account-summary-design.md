# Lean IB 账户摘要桥接设计

## 目标
将 Lean Bridge 输出的 `account_summary.json` 与 IB 真实账户对齐，避免使用 `Algorithm.Portfolio` 的默认值（100000 等），保证实盘交易页显示准确。

## 现状与问题
- Lean Bridge 当前 `LeanBridgeResultHandler.BuildAccountSummary` 读取 `Algorithm.Portfolio`，与 TWS/IB 账户不一致。
- 实盘交易页展示的数据来自 `/data/share/stock/data/lean_bridge/account_summary.json`，因此出现默认值而非真实账户。

## 设计方案（已确认）
采用 **混合策略**：合并 `AccountUpdates(UpdateAccountValue)` 与 `AccountSummary(reqAccountSummary)` 两路 IB 数据，优先 `BASE` 币种，同名标签按来源优先级合并，最终由 Lean Bridge 输出。

### 数据流
1. `InteractiveBrokersBrokerage` 监听：
   - `HandleUpdateAccountValue`（AccountUpdates）
   - `HandleAccountSummary`（AccountSummary）
   - 账户摘要快照来自 `AccountProperties`（键：`{Currency}:{Tag}`），提供 `GetAccountSummarySnapshot()` 只读拷贝。
2. 两路数据分别写入账户快照字典，键为 `"{Currency}:{Tag}"`。
3. `LeanBridgeResultHandler` 从 `BrokerageTransactionHandler.Brokerage` 读取 IB 快照并构建 `account_summary.json`。
4. 后端读取 `account_summary.json`，实盘交易页展示该结果。

### 合并规则
- **币种优先级**：优先 `BASE:{Tag}`，缺失时再查其他币种。
- **来源优先级**：AccountUpdates > AccountSummary。
- **兜底规则**：若 AccountUpdates 缺失则回退 AccountSummary。
- **数值解析**：可解析数值则转 `decimal`，解析失败保留字符串。

### 输出字段（摘要）
优先构建以下字段并写入 `items`：
- `NetLiquidation`
- `TotalCashValue`
- `AvailableFunds`
- `BuyingPower`
- `UnrealizedPnL`
- `TotalHoldingsValue`
- `CashBalance`
- `EquityWithLoanValue`
- `GrossPositionValue`
- `InitMarginReq`
- `MaintMarginReq`

### 兼容字段
- `cash_available` 由 `AvailableFunds → CashBalance → TotalCashValue` 兜底。

### Stale 策略
- 当快照为空或未更新时：`items={}` 且 `stale=true`，避免 UI 误展示默认值。

## 测试与验证
### 单测（TDD）
- `InteractiveBrokersAccountData.GetAccountSummarySnapshot()` 返回深拷贝。
- `LeanBridgeResultHandler` 写出的 `account_summary.json` 使用 IB 合并快照，而非 `Algorithm.Portfolio`。

### 手动验证
- 启动 Lean Live（paper）后比对：
  - `account_summary.json` 与 TWS Account Summary（NetLiquidation/CashBalance/BuyingPower）。
- 实盘交易页展示应与 `account_summary.json` 一致。

## 风险点
- 字段命名与币种冲突：通过 BASE 优先与来源优先级避免误覆盖。
- 账户数据不完整：通过 `stale` 避免误展示默认值。
