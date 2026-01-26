# Lean IB 账户摘要准确性修复设计

## 目标
将 `lean_bridge/account_summary.json` 的账户信息从“算法 Portfolio 估值”改为“IB 原始账户摘要”，确保实盘交易页与 TWS/Paper 账户一致。

## 背景与问题
当前 `LeanBridgeResultHandler.BuildAccountSummary()` 直接读取 `Algorithm.Portfolio`，导致固定显示算法初始资金（如 100000），与 IB 真实账户不一致。

## 方案概述（只保留 IB 原始摘要）
1. 在 `InteractiveBrokersBrokerage` 内新增账户摘要快照缓存与读取接口。
2. 在 `LeanBridgeResultHandler` 中优先从 IB 账户摘要快照生成 `account_summary.json`。
3. 若 IB 快照不可用则输出空 `items` + `stale=true`，避免误导。

## 关键设计
### 1) IB 账户摘要快照
- 数据来源：`UpdateAccountValue` 事件已经写入 `_accountData.AccountProperties`（键：`{Currency}:{Tag}`）。
- 新增方法：`GetAccountSummarySnapshot()` 返回 `Dictionary<string,string>` 的只读拷贝。
- 处理规则：优先 `BASE` 货币的关键字段；若 `CashBalance` 无 `BASE`，则回退到首个币种 `CashBalance`。

### 2) Lean Bridge 输出
- `LeanBridgeResultHandler` 通过 `TransactionHandler` 获取 `Brokerage`，若类型为 `InteractiveBrokersBrokerage` 则读取快照。
- 输出结构保持不变：`items/refreshed_at/source/stale`。
- `source` 可设为 `ib_brokerage` 或保留 `lean_bridge`，以兼容前端展示逻辑。

## 错误处理与降级
- 快照为空：`items={}`，`stale=true`。
- 异常：写入 `lean_bridge_status.json` 的 `last_error/last_error_at` 并 `degraded=true`（沿用已有机制）。

## 测试与验证
- 单元测试：验证 `GetAccountSummarySnapshot()` 返回包含 `BASE:NetLiquidation` 等关键字段。
- 结果处理测试：当快照存在时 `account_summary.json.items` 与 IB 一致；快照缺失时 `stale=true`。
- 运行验证：启动 Lean live/paper 后比对 `account_summary.json` 与 TWS 纸面账户。
