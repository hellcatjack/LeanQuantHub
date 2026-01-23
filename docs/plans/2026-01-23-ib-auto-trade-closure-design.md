# IB 自动化交易闭环设计（首期）

**目标**：在 IB PRO 账户上完成 Paper/Live 可切换的周频调仓闭环，保证数据与执行一致、可追溯、可回放，并具备最小风控与监控能力。

**范围**：首期聚焦股票；期权扩展延后。训练/回测数据源仍为 Alpha，交易执行数据源为 IB。

---

## 1. 架构与组件边界

以“交易执行域”为核心分层：

- 连接管理：IBSettings / IBConnectionState / clientId 自愈 / Paper-Live 切换
- 行情与合约数据：IBMarket / IBContractCache / IBStream
- 信号快照：DecisionSnapshot（冻结当日信号）
- 订单执行：TradeOrder / TradeFill / IBOrderExecutor
- 风控：TradeGuard / RiskEngine（预交易与盘中）
- 调度与审计：PreTrade / TradeRun / 审计日志

**边界原则**：
- 行情模块只负责数据拉取与缓存，不参与信号生成。
- 执行模块只读取冻结快照与风险参数，保证幂等与可追溯。
- 模块通过 DB / 审计日志衔接，避免强耦合。

**QC/Lean 对齐**：
- DataFeed → IBMarket
- Alpha → DecisionSnapshot
- Portfolio Construction → 权重生成
- Execution → IBOrderExecutor
- Risk → TradeGuard
- Brokerage → IB Gateway/TWS

---

## 2. 数据流与状态机

**数据流**：
PreTrade checklist → 决策快照冻结 → 风控预检 → 权重转股数 → 下单 → 成交回写 → 盘后审计

**关键追溯点**：
- snapshot_id / 模型版本 / 参数版本
- clientOrderId（幂等）
- ib_order_id / perm_id / exec_id
- 风控触发与阻断原因

**订单状态机**：
NEW → SUBMITTED → PARTIAL → FILLED / CANCELED / REJECTED

**执行一致性**：
- 交易行情与成交来源一律使用 IB。
- Paper/Live 仅切换 IB 连接模式，不分叉策略逻辑。

---

## 3. 错误处理与风险控制

**优先级**：
1) 连接故障：阻断下单并告警
2) 风控触发：阻断下单并记录原因
3) 下单失败：回退 / 标记失败 / 人工介入

**安全与校验**：
- 所有外部输入参数校验（symbol / 价格 / 账户参数）
- clientOrderId 幂等，防止重复下单

**日志与可观测**：
- 关键路径必须记录 run_id / snapshot_id / order_id / exec_id

---

## 4. 测试与验证

**核心测试**：
- clientId 冲突自愈（自动递增并持久化）
- 订单状态机幂等
- 风控拦截（无下单）
- 快照冻结只读
- Paper/Live 切换不影响策略逻辑

**集成验证**：
- TWS 断线 → 自动重连 → 下单成功
- 重复触发同一 run_id 不重复下单
- 快照版本可回放复现交易行为

---

## 5. 优先级建议

**闭环优先 + 风控兜底**：
Phase 0 → Phase 2 → Phase 3.1 → Phase 4 → Phase 5 → Phase 6

目标是先交付可交易、可追溯、可监控的 Paper 周频调仓闭环，再扩展 Live 与调度器。
