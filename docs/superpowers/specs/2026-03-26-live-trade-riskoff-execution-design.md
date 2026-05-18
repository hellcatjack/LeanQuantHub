# 实盘/虚拟盘防御资产执行统一设计

## 背景
当前回测与实盘执行对 `risk_off` 的防御资产处理存在语义偏差：

- 回测算法 `ml_overlay_scores.py` 在 `risk_off_mode=defensive` 时，只买入当日选中的单一防御资产 `RiskOff_Symbol`，仓位上限取 `effective_exposure_cap/max_exposure`。
- 交易执行器 `trade_executor.py` 的正常路径依赖 `decision_items.csv`，而诊断路径 `risk_off_drill` 又会把 `risk_off_symbols` 等权展开成整个防御篮子。

结果是：当 snapshot 已经判定进入 `risk_off` 时，回测和实盘可能会看到不同的目标持仓，导致虚拟盘/实盘无法自动按回测语义完成防御资产买卖。

## 目标
统一回测与实盘（含虚拟盘）在 `risk_off` 场景下的执行目标：

1. `risk_off=true` 时，执行器直接消费 snapshot summary 的风险语义。
2. `risk_off_mode=defensive/bond/safe` 时，只买入已选中的单一防御资产。
3. `risk_off_mode=benchmark` 时，买入基准资产。
4. `risk_off_mode=cash` 或无可用标的时，仅卖出风险资产，保留现金。
5. 正常 `risk_on` 路径继续按 `decision_items.csv` 执行，不改变已有回测/交易逻辑。

## 推荐方案
在 `trade_executor.py` 增加“snapshot 执行目标解析器”，统一产出 `target_weights` 与审计元数据。

### 方案比较

#### 方案 A：执行器侧解析 snapshot 语义（推荐）
- 新增 helper，从 `DecisionSnapshot.summary` 提取：
  - `risk_off`
  - `risk_off_mode`
  - `risk_off_symbol`
  - `effective_exposure_cap`
  - `algorithm_parameters.benchmark`
- 若 `risk_off=true`，执行器忽略 `decision_items.csv` 中的风险资产权重，直接合成风险关闭后的目标权重。
- 优点：改动集中，最快让虚拟盘/实盘自动对齐回测语义。
- 缺点：需要在执行器里维护一层语义解析。

#### 方案 B：在 decision snapshot 阶段物化最终执行权重
- 让 `decision_items.csv` 在 `risk_off` 时直接写入最终防御标的。
- 优点：执行器继续只读 items，职责更单一。
- 缺点：要改 snapshot 生成链路与历史产物语义，波及更大。

#### 方案 C：新增独立 execution targets 产物
- snapshot 继续保留 `decision_items.csv` 作为分析产物，另新增 `execution_targets.json/csv` 给执行器使用。
- 优点：审计最清晰。
- 缺点：实现量更大，当前问题不需要这么重。

推荐先做方案 A。它能在不重写 snapshot 管线的前提下，把实盘/虚拟盘执行语义直接拉齐到回测结果。

## 架构与边界

### 1. Snapshot 执行目标解析器
在 `backend/app/services/trade_executor.py` 新增 helper：
- 输入：`DecisionSnapshot`、从 `decision_items.csv` 读出的 items
- 输出：
  - `target_weights`
  - `meta`，用于写入 `run.params`

解析规则：
- `risk_off=false`：返回 `decision_items.csv` 对应权重
- `risk_off=true` 且 `risk_off_mode in {defensive,bond,safe}`：
  - 优先使用 `summary.risk_off_symbol`
  - 若缺失，再回退 `summary.algorithm_parameters.risk_off_symbol`
  - 权重 = `effective_exposure_cap`，剩余现金保留
- `risk_off=true` 且 `risk_off_mode=benchmark`：
  - 标的 = `summary.algorithm_parameters.benchmark`，缺省 `SPY`
  - 权重 = `effective_exposure_cap`
- `risk_off=true` 且 `risk_off_mode=cash`：
  - `target_weights = {}`

### 2. 自动买卖行为
执行器后续的 delta 订单逻辑保持不变：
- 当前持仓里不在目标内的风险资产自动卖出
- 目标防御资产缺口自动买入
- `cash` 模式下只会生成卖单或 no-op

### 3. 审计与可观测性
在 `run.params` 增加：
- `effective_target_source = snapshot_risk_off` 或 `decision_items`
- `effective_target_meta`：
  - `risk_off`
  - `risk_off_mode`
  - `risk_off_symbol`
  - `exposure_cap`
  - `decision_snapshot_id`

这样交易记录可以明确说明：这次自动买入防御资产，是 snapshot 风险关闭语义驱动的，不是人工 override。

### 4. 风险校验
`trade_riskoff_validation.py` 需要按同一套“有效目标”校验，而不是只盯 `decision_items.csv`。否则当 `risk_off` 执行目标来自 summary 时，校验层会误报。

## 错误处理
- `risk_off=true` 但没有可解析的防御资产：
  - 对 `defensive/bond/safe`：退化为 `cash`，并在 `run.params` 标记 `fallback_to_cash=true`
- `effective_exposure_cap` 缺失或非法：
  - 回退 `summary.max_exposure` -> `algorithm_parameters.max_exposure` -> `1.0`
- `positions` 不精确或价格缺失：
  - 继续沿用现有阻断逻辑，不降低安全阈值

## 测试策略
1. `trade_executor`：
   - `risk_off=defensive` 时卖出风险资产并买入单一防御标的
   - `risk_off=benchmark` 时买入基准资产
   - `risk_off=cash` 时仅卖出/不买入
   - `risk_off=false` 时继续按 `decision_items.csv`
2. `trade_riskoff_validation`：
   - 使用 summary 解析出的有效目标做通过/失败判断
3. 回归：
   - 保留现有 `risk_off_drill` 测试，确保诊断路径不影响正式执行语义

## 验收标准
- 虚拟盘/实盘执行 `risk_off` snapshot 时，会自动卖出风险资产并买入正确的防御资产
- 默认防御模式只买入单一 `RiskOff_Symbol`，不再等权整篮子
- `cash/benchmark` 模式与回测语义一致
- 风险校验与执行器使用同一套有效目标解析结果
