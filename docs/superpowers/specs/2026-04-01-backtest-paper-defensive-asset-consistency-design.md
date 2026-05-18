# 回测与实盘防御资产语义一致性设计

## 背景
当前系统有三条相关但不完全一致的路径：

1. Lean 回测算法 `algorithms/ml_overlay_scores.py`
2. 交易批次生成时的 decision snapshot 管线 `scripts/universe_pipeline.py` + `backend/app/services/decision_snapshot.py`
3. 实盘/虚拟盘执行路径 `backend/app/services/trade_execution_targets.py` + `backend/app/services/trade_executor.py`

最近的 `run 1162 / snapshot 102` 暴露出两类不一致：

- `snapshot_summary.csv` 明确进入 `risk_off`，但 `risk_off_symbol=''`、`risk_off_selection='defensive_missing'`
- `paper` 执行器又回退到默认 `SGOV` 去下单

这意味着当前不是一套统一语义，而是：
- snapshot 管线在某些场景下算不出防御资产
- 执行器再用另一套回退规则补一个答案

这会让回测、snapshot 审计、paper/live 的结果出现偏差。

## 根因
### 1. snapshot 管线没有把防御/闲置资产价格纳入可交易价格矩阵
`scripts/universe_pipeline.py` 当前只遍历股票池 `universe` 来构建 `prices/trade_prices`。如果 `risk_off_symbols`、`benchmark` 不在股票池里，它们不会进入价格矩阵：

- `_pick_risk_off_symbol()` 只能在 `trade_prices.columns` 中挑选防御资产
- `idle_allocation=defensive/benchmark` 也只能在 `prices.columns` 中找 `idle_symbol`

因此 snapshot 会出现：
- `risk_off_selection = defensive_missing`
- `risk_off_symbol = ''`
- `idle_symbol = ''`

### 2. snapshot 管线的防御资产挑选逻辑与 Lean 算法不一致
Lean 算法的逻辑是：
- 若 `risk_off_symbols` 有值，则在篮子里按 `best_momentum/lowest_vol` 选
- 只有在篮子为空时，才回退到单一 `risk_off_symbol`

而 `scripts/universe_pipeline.py` 现在是：
- 如果 `risk_off_symbol` 存在且在价格矩阵里，直接返回它
- 这会绕过篮子挑选逻辑

这与 Lean 回测不一致。

### 3. `paper/live` 的 risk-on 执行没有补齐 idle allocation
Lean 回测在 `risk_on` 且 `idle_allocation != none` 时，会把剩余仓位补到：
- `benchmark`，或
- 当日选出的 `idle_symbol`（通常也是防御资产）

而 `trade_execution_targets.py` 在 `risk_off=false` 时只读取 `decision_items.csv`，不会补齐闲置仓。因此：
- 回测可能是 `30% 风险资产 + 70% defensive`
- paper/live 目前可能变成 `30% 风险资产 + 70% 现金`

## 目标
统一三条路径的语义，使其满足：

1. 防御资产选择逻辑与 Lean 回测一致
2. decision snapshot 必须固化当日有效的：
   - `risk_off_symbol`
   - `risk_off_selection`
   - `idle_symbol`
   - `idle_weight`
3. `paper/live` 执行只消费 snapshot 已固化的语义，不再现场猜测
4. `risk_on + idle_allocation` 与 Lean 回测结果一致
5. 对旧 snapshot 保留兼容回退，但新 snapshot 必须产出完整语义

## 方案对比
### 方案 A：只改执行器
- 执行器自己重新算 `risk_off_symbol/idle_symbol`
- 优点：改动最小
- 缺点：snapshot 审计仍然错误，回测与执行之间仍存在第二套语义

### 方案 B：统一 snapshot 与执行器，推荐
- 修 `scripts/universe_pipeline.py`，让 snapshot 输出与 Lean 回测一致的防御/闲置资产语义
- 执行器优先消费 snapshot 已固化结果
- 对旧 snapshot 再做受控回退
- 优点：回测、snapshot、paper/live 三条链路统一
- 缺点：改动面中等

### 方案 C：每次交易前重新跑 Lean 决策
- 优点：理论最一致
- 缺点：链路重、时延大、没有必要

推荐方案 B。

## 统一语义设计
### 1. 统一防御资产选择规则
新增共享 helper，供 snapshot 与执行器复用：

- 输入：
  - `snapshot_date/rebalance_date`
  - `risk_off_mode`
  - `risk_off_symbol`
  - `risk_off_symbols`
  - `risk_off_pick`
  - `risk_off_lookback_days`
  - `idle_allocation_mode`
  - `benchmark`
- 数据源：`data_root/curated_adjusted`
- 选择规则：
  - `risk_off_symbols` 非空：按篮子挑选
  - `risk_off_symbols` 为空：回退 `risk_off_symbol`
  - `idle_allocation=benchmark`：`idle_symbol = benchmark`
  - `idle_allocation=defensive`：`idle_symbol = 同一套 defensive picker 的结果`

### 2. 修正 snapshot 管线
`scripts/universe_pipeline.py` 需要：

- 把 `benchmark`、`risk_off_symbols`、`risk_off_symbol` 对应的价格序列加入价格矩阵
- 但这些标的不进入股票池选股，只作为：
  - benchmark 过滤
  - risk_off 选标
  - idle allocation 选标
- `_pick_risk_off_symbol()` 改成与 Lean 相同：
  - 优先使用 `risk_off_symbols`
  - 只有篮子为空时才退回单一 `risk_off_symbol`
- 输出 `snapshot_summary.csv` 时保证：
  - `risk_off_symbol`
  - `risk_off_selection`
  - `idle_symbol`
  - `idle_weight`
 真实可用，而不是空字符串

### 3. 修正执行器目标解析
`trade_execution_targets.py` 改成两段语义：

#### `risk_off=true`
与 Lean 保持一致：
- `cash`：全清仓，不买入
- `benchmark`：买入 `benchmark`，权重=`effective_exposure_cap`
- `defensive/bond/safe`：买入 snapshot 固化的 `risk_off_symbol`，权重=`effective_exposure_cap`
- 不再把剩余资金填入 idle defensive，这与 Lean `risk_off` 路径一致

#### `risk_off=false`
- 先从 `decision_items.csv` 构建风险资产权重
- 若 `idle_allocation_mode != none`：
  - 把剩余 `1 - sum(risk_weights)` 分配给 snapshot 固化的 `idle_symbol`
- 若 snapshot 缺失 `idle_symbol`：
  - 对新 snapshot 视为错误
  - 对旧 snapshot 再按共享 helper 回退计算

### 4. 兼容策略
为避免历史 snapshot 全部失效：

- 新生成 snapshot：必须产出完整字段
- 旧 snapshot：执行器允许回退计算，并在 `effective_target_meta` 标记：
  - `compat_fallback_used=true`
  - `compat_missing_fields=[...]`

### 5. 审计与校验
`trade_riskoff_validation.py` 与后续审计应复用同一套有效目标解析结果：
- 不再直接用 `decision_items.csv` 推断 risk-off 目标
- 校验 payload 需要带出：
  - `effective_target_source`
  - `compat_fallback_used`
  - `target_symbols`

## 错误处理
- 防御篮子无可用价格：
  - `risk_off` 下退化为 `cash`
  - 记录 `risk_off_selection=defensive_missing`
- `idle_allocation` 需要的标的无可用价格：
  - 新 snapshot 生成直接记 warning
  - 执行器对旧 snapshot 允许退化为现金并标记兼容回退
- 价格文件缺失或窗口不足：
  - 记录具体原因到日志/summary meta，避免再次出现“只知道空字符串”的状态

## 测试策略
### 后端单测
1. snapshot 共享 picker：
- `risk_off_symbols` 篮子选择与 Lean 逻辑一致
- `risk_off_symbol` 只在篮子为空时才生效
- `idle_allocation=defensive` 时返回同一 defensive symbol

2. 执行目标解析：
- `risk_off=defensive` 只买 `risk_off_symbol` 且仓位=`effective_exposure_cap`
- `risk_off=false + idle_allocation=defensive` 会补齐 idle symbol
- `risk_off=false + idle_allocation=benchmark` 会补齐 benchmark
- 旧 snapshot 缺字段时会触发兼容回退

3. snapshot 摘要：
- `decision_summary` 会落出真实 `risk_off_symbol/idle_symbol`

### 运行态验证
- 用最新 project 18 决策链路重建一个 preview snapshot
- 检查 `snapshot_summary.csv` 不再出现 `defensive_missing + risk_off_symbol=''`
- 再用 dry-run 执行验证 paper/live 目标权重与 snapshot 一致

## 验收标准
满足以下条件才算完成：

1. 最新 snapshot 在 `risk_off` 时能写出非空 `risk_off_symbol`
2. `risk_on + idle_allocation=defensive/benchmark` 的 paper/live 目标权重与 Lean 语义一致
3. `risk_off` 时 paper/live 只买 `effective_exposure_cap` 对应的防御仓，其余保留现金
4. 风险校验使用同一套有效目标，不再因 summary/items 分歧误判
5. 相关 pytest 全绿，且至少完成一次真实 dry-run 验证
