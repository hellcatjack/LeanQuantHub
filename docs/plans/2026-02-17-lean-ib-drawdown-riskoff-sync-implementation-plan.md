# 自动交易回撤/防御篮子与 LEAN/IB 同步改造计划（2026-02-17）

## 1. 背景与目标

当前系统在“下单执行通道”上已经接入 Lean Bridge，但在“回撤驱动风控、风险切换、防御篮子自动交易”方面仍与回测策略和 LEAN/IB 原生逻辑存在明显偏差。

本计划目标：

- 让自动交易在运行时稳定使用最新、可追踪的策略参数（尤其是 `algorithm_parameters`）。
- 让回撤与风险状态真正参与自动交易执行决策，而不是仅展示或离线评估。
- 让防御篮子切换逻辑与回测逻辑保持一致，至少达到“同参数、同触发条件、同执行结果方向”。
- 逐步收敛到 LEAN/IB 原生口径（净值、PnL、风控触发）并可验证。

## 2. 现状结论（已核实）

### 2.1 自动交易未稳定按回撤动态调整

- `trade_executor` 执行前只读取 guard 当前状态（halted/active），并不强制做当次回撤评估。
- `trade_guard` 评估链路是独立调用（API/脚本），并非执行链路硬前置。
- 运行态存在 guard 评估异常（时区 aware/naive 相减导致 500），影响 guard 可用性。

### 2.2 防御篮子未按回测参数自动触发

- 最新 `decision_snapshot` 的 `algorithm_parameters` 为空，导致 risk_off/market_filter/max_exposure 等关键参数没有进快照计算。
- `pretrade` 虽成功产出决策快照，但由于参数未继承回测配置，快照结果没有触发防御篮子。
- `trade_run` 实际交易标的未出现防御篮子标的（如 `VGSH/IEF/GLD/TLT`）。

### 2.3 与 LEAN/IB 原生逻辑的同步程度

- 已同步：执行 sizing 采用 `NetLiquidation`（Lean Bridge account summary）。
- 未同步：回撤口径和风控触发仍主要基于本地成交+报价推算，不是 LEAN `Portfolio.TotalPortfolioValue` / IB 原生 PnL 事件主驱动。
- 未同步：LEAN 算法中的 drawdown tier / dynamic exposure / risk_off 锁定恢复机制未在当前自动交易执行链路中完整复现。

## 3. 改造范围

### 3.1 In Scope

- 决策快照参数继承链路修复（回测参数 -> pretrade decision snapshot）。
- guard 评估稳定性修复与执行链路接入。
- 自动交易与回测 risk_off/防御篮子核心参数对齐。
- 风控/执行观测指标补全（可追踪触发原因与参数来源）。
- 覆盖关键单测与最小回归验证。

### 3.2 Out of Scope（本轮）

- 完整重写为 LEAN `RiskManagementModel` 运行时托管。
- 一次性替换全部本地风控实现。
- 大规模前端重构。

## 4. 设计原则

- 单一事实源：当次交易使用的风险参数必须可追溯到具体 `backtest_run_id` / `project config version`。
- 执行前风控：任何自动下单前必须完成一次最新风控评估。
- 失败可降级：参数缺失、行情异常时默认阻断下单并给出可读原因，不允许静默放行。
- 口径清晰：区分“账户净值口径（IB/LEAN）”与“本地估值口径（fallback）”，并记录来源。

## 5. 分阶段实施计划

## 阶段 P0（立即修复，阻断风险）

- [x] 修复 `trade_guard` 时区 bug（避免 `/api/trade/guard/evaluate` 500）。
- [x] 在 `decision_snapshot` 生成时补齐算法参数继承：
  - step override 优先；
  - 其次 pipeline params.backtest.algorithm_parameters；
  - 再次 backtest_run.params.algorithm_parameters（通过已解析的 backtest_run_id）；
  - 最后为空。
- [x] 补充参数来源标记（如 `algorithm_parameters_source`），写入 snapshot params/summary，便于审计。
- [x] 单测覆盖：
  - aware/naive 时间戳兼容；
  - pretrade 空 override 时能从 backtest_run 继承参数。

验收标准：

- guard evaluate API 不再 500；
- 最新 decision snapshot `algorithm_parameters` 非空且含 `risk_off_mode/max_drawdown/...`；
- 同参数下，risk_off 触发结果与回测脚本方向一致。

## 阶段 P1（执行链路强制接入风控）

- [x] 在 `execute_trade_run` 前强制调用一次 `evaluate_intraday_guard`（可配置开关，默认开启）。
- [x] 将 `max_daily_loss/max_intraday_drawdown/cooldown_seconds` 纳入 `trade_settings.risk_defaults` 的标准项（API 校验+默认值）。
- [x] guard 触发时，将触发原因、阈值、估值来源写入 run params 与告警。
- [x] 将 `run_trade_guard.py` 纳入服务化或调度体系（systemd timer / app 内后台任务二选一），避免靠人工触发。

验收标准：

- 不经过风控评估不能执行自动下单；
- 风控触发能在 run 详情中看到完整理由链。

## 阶段 P2（回测逻辑与自动交易一致化）

- [x] 对齐 `universe_pipeline.py` 风控能力：
  - 实现 `drawdown_tiers/drawdown_exposures/drawdown_exposure_floor` 对仓位上限的实际约束；
  - 与 `market_filter` / `risk_off_mode` 联动。
- [x] 将 `dynamic_exposure/idle_allocation` 关键行为在 snapshot 生成链路可配置并可审计。
- [x] 输出“本次交易实际 exposure cap、risk_off 原因、防御标的选择过程”。

验收标准：

- 回测与自动交易在同一参数集下，对应时点的 `risk_off` 状态与 exposure cap 一致（允许小幅行情差异）。

## 阶段 P3（LEAN/IB 原生口径收敛）

- [x] 建立双口径净值/PnL：
  - 主口径：IB/Lean Bridge (`NetLiquidation`, `UnrealizedPnL` 等)；
  - 备口径：本地持仓估值。
- [x] 回撤计算优先主口径，备口径仅在主口径不可用时启用，并显式标记。
- [x] 增加“资金流入/流出校正”机制：
  - 区分净值变动中的市场收益与现金流变化，避免充值导致回撤误判。
- [x] 输出统一风险审计字段：`equity_source`, `cashflow_adjustment`, `dd_all`, `dd_52w`, `dd_lock_state`。

说明：`dd_52w` 已在 guard 服务按最近 252 窗口计算（历史 251 条 + 当前权益）；后续可继续增强为独立持久化指标表以支持跨服务重启连续统计。

验收标准：

- 充值/出金场景下回撤不误触发；
- 风险评估结果与 LEAN/IB 账户视图能够对账。

## 6. 关键技术方案

### 6.1 参数继承优先级

1. pretrade step `params.algorithm_parameters`（人工强制覆盖）
2. pipeline `params.backtest.algorithm_parameters`
3. `backtest_run.params.algorithm_parameters`
4. 空字典

并记录：

- `algorithm_parameters_source`（`override|pipeline|backtest_run|empty`）
- `algorithm_parameters_backtest_run_id`

### 6.2 回撤口径与现金流校正（目标口径）

- 账户权益序列：优先 `NetLiquidation`。
- 日内/区间回撤：
  - `DD = (Equity - PeakEquity) / PeakEquity`
- 现金流校正：
  - `AdjEquity_t = Equity_t - CumNetCashFlow_t`
  - 回撤基于 `AdjEquity` 计算，避免充值把回撤“抹平”或触发误差。

### 6.3 防御篮子选择一致化

- 保持与回测相同的 `risk_off_mode/risk_off_symbols/risk_off_pick/risk_off_lookback_days`。
- 交易前将“最终选中的防御标的 + 原因 + 评分/波动指标”写入 artifacts。

## 7. 数据与接口改动清单

- 后端服务：
  - `backend/app/services/trade_guard.py`
  - `backend/app/services/decision_snapshot.py`
  - `backend/app/services/pretrade_runner.py`
  - `backend/app/services/trade_executor.py`
  - `backend/app/routes/trade.py`
  - `scripts/universe_pipeline.py`
- 测试：
  - `backend/tests/test_trade_guard_service.py`
  - `backend/tests/test_decision_snapshot_backtest_link.py`
  - `backend/tests/test_trade_run_schedule.py`
  - 视改动新增针对性测试文件

## 8. 验证计划

### 8.1 自动化测试

- `cd backend && pytest -q backend/tests/test_trade_guard_service.py`
- `cd backend && pytest -q backend/tests/test_decision_snapshot_backtest_link.py`
- `cd backend && pytest -q backend/tests/test_trade_run_schedule.py`
- 变更后执行相关回归集合（trade/pretrade/decision_snapshot）。

### 8.2 运行态验证

- 触发一次 pretrade（项目 18）：
  - 核验 snapshot `algorithm_parameters` 来源与内容。
- 发起一次 paper trade：
  - 核验执行前 guard 评估已发生。
- 人工注入风险阈值：
  - 核验 guard halt 能阻断执行。
- risk_off 场景：
  - 核验防御篮子标的被实际下单。

## 9. 风险与回滚

- 风险：执行链路接入强制风控后，短期可能出现“比过去更严格”的阻断。
- 缓解：
  - 增加开关（默认启用）；
  - 提供 `force` 受控兜底并留审计日志。
- 回滚：
  - 所有行为改动保留 feature flag；
  - 参数继承逻辑可降级回旧路径。

## 10. 里程碑

- M1（P0 完成）：guard 稳定 + 快照参数继承可用。
- M2（P1 完成）：执行链路强制风控。
- M3（P2 完成）：回测/自动交易 risk_off 与 exposure 行为对齐。
- M4（P3 完成）：LEAN/IB 原生口径收敛与现金流校正上线。

## 11. 当前执行顺序（本轮立即开始）

- [x] 先完成 P0 两项代码修复与单测。
- [x] 输出本轮变更结果与验证证据。
- [x] 进入 P1：将 guard 评估并入执行前置链路。

## 12. 本轮执行补充（2026-02-17）

- [x] 修复 `test_trade_execution_builder.py` 的锁路径权限依赖：非 `dry_run` 用例显式绑定临时 `data_root`，不再写入 `/data/share/stock/data/locks`。
- [x] 扩展 guard 告警阈值摘要：告警文案补充 `max_drawdown/max_drawdown_52w/drawdown_recovery_ratio`。
- [x] 完成变更回归：`pytest -q $(git status --short backend/tests | awk '{print $2}')`，结果 `113 passed`。
- [x] 多币种校正回归：`pytest -q $(git status --short backend/tests | awk '{print $2}')`，结果 `120 passed`。

## 13. 后续待调整项

- [x] 增加“实盘/模拟盘单次端到端验证脚本”：自动校验 risk_off 触发后实际下单标的是否进入防御篮子（VGSH/IEF/GLD/TLT）。
  - 实现：`backend/app/services/trade_riskoff_validation.py` + `scripts/validate_riskoff_trade_run.py`。
  - 增强：支持 `--risk-off-only` 自动选择最近一次 `risk_off=true` 的交易批次；在无样本时返回 `skipped/risk_off_trade_run_not_found`，便于 `--strict` 控制验收门槛。
- [x] 将 `_IB_GUARD_BASELINE_PNL` 从进程内内存迁移到可持久化状态（DB 或 bridge 状态文件），避免服务重启后当日现金流校正基线丢失。
  - 实现：`trade_guard` 基线文件 `data_root/state/trade_guard_ib_baseline_pnl.json`。
- [x] 多币种账户场景下分币种现金流校正（按 base currency 汇总），与 IB `NetLiquidationByCurrency` 对齐。
  - 实现：`ib_account._normalize_items` 输出 `__by_currency__`；`trade_guard` 解析并优先使用 `pnl_total_by_currency` 计算市场 PnL。
  - 持久化：基线存储升级为 `{"scalar": ..., "by_currency": {...}}` 结构，兼容旧版标量格式。
  - 测试：`test_load_ib_equity_snapshot_extracts_currency_maps`、`test_guard_uses_currency_pnl_for_cashflow_adjustment`。
- [x] 将 `trade_run` 返回的 `risk_audit` 接入实盘交易页展示，支持查看 `cashflow_adjustment/dd_all/dd_52w/dd_lock_state/pnl_total_by_currency` 与阈值/触发详情。
  - 后端：`TradeRunDetailOut.risk_audit` + `trade_run_summary._build_risk_audit_payload` + `/api/trade/runs/{id}/detail`。
  - 前端：`LiveTradePage`“目标偏离概览”区域新增风险审计块，支持中英文文案与 JSON 审计详情展示。
