# 回测优化参考（近期记录）

## 2026-01 新基线与跨年份稳健性验证
- 目的：验证“同一默认策略”在不同起始年份是否整体有效，而不是挑选最佳年份。
- 默认基线（项目 16 已固化）：
  - `top_n=36`
  - `max_weight=0.025`
  - `max_exposure=0.50`
  - `market_ma_window=200`
  - `retain_top_n=10`
  - `score_smoothing_alpha=0.15`
  - `max_drawdown=0.20`、`max_drawdown_52w=0.20`
  - 其他保持：`dynamic_exposure=true`、`market_filter=true`、`idle_allocation=defensive`

### 跨年份结果（同模型/同参数，仅起始年份不同）

| Run | 起始 | CAGR | Sharpe | MaxDD_all | MaxDD_52w | Turnover_week |
| --- | --- | --- | --- | --- | --- | --- |
| 304 | 2013-01-01 | 18.85% | 1.031 | 23.57% | 23.57% | 5.61% |
| 305 | 2015-01-01 | 16.65% | 0.896 | 23.57% | 23.57% | 5.42% |
| 306 | 2017-01-01 | 18.27% | 0.977 | 23.56% | 23.56% | 5.21% |
| 307 | 2018-01-01 | 22.10% | 1.078 | 24.51% | 24.51% | 5.60% |
| 308 | 2019-01-01 | 24.48% | 1.130 | 24.78% | 24.78% | 5.84% |
| 309 | 2020-01-01 | 23.59% | 1.073 | 18.93% | 18.93% | 5.80% |
| 310 | 2021-01-01 | 21.49% | 1.005 | 18.36% | 18.36% | 5.78% |
| 311 | 2022-01-01 | 24.32% | 1.058 | 19.31% | 19.31% | 5.88% |

### 稳健性结论（跨年份一致性）
- 平均：`CAGR=21.22%`、`Sharpe=1.031`、`MaxDD_all=22.07%`、`Turnover_week=5.64%`。
- 最弱年份：2015 起始（Sharpe 0.896、CAGR 16.65%）。
- 最大回撤年份：2019 起始（MaxDD_all 24.78%）。
- 结论：策略整体“起效”，但不同市场状态下存在回撤/收益不均匀性。

## 目标与约束（历史阶段记录）
- 目标：在稳健前提下提升收益与夏普。
- 阶段硬约束：`MaxDD_all ≤ 0.12`、`MaxDD_52w ≤ 0.12`、`Turnover_week ≤ 0.08`。

## 分组对比（平均值）

| 组 | 说明 | CAGR | MaxDD_all | Turnover_week | Sharpe |
| --- | --- | --- | --- | --- | --- |
| 192–199 | 稳健基线 | 7.17% | 9.02% | 4.25% | 0.84 |
| 200–205 | 提升 `max_exposure`（0.22–0.30） | 21.26% | 45.74% | 8.00% | 0.823 |
| 206–208 | 降低 `max_exposure`（0.16–0.20） | 5.49% | 7.66% | 6.57% | 0.654 |

结论：200–205 回撤严重超约束，不可用；206–208 过于保守；192–199 为稳健基线区间。

## 单参数微调（基于稳健基线）

### 1) 分数平滑 `score_smoothing_alpha`
- run 213（0.15）：CAGR 7.88%、MaxDD_all 9.17%、Sharpe 0.889、Turnover 3.51%
- run 214（0.10）：CAGR 7.89%、MaxDD_all 9.49%、Sharpe 0.871、Turnover 3.03%

结论：`0.15` 效果更稳，夏普更高，成为新基线。

> 注意：run 209–212 未完全继承稳健基线参数（因使用项目默认配置导致 `max_exposure/max_weight/drawdown` 发生漂移），不纳入比较。

### 2) `retain_top_n`
- run 215（12）与 run 216（15）在 `alpha=0.15` 下结果与 run 213 基本一致。

结论：`retain_top_n` 在 10–15 区间对结果不敏感，保持 10 即可。

### 3) 目标波动 `vol_target`
- run 218（0.055）与 run 219（0.06）结果与 run 213 完全一致。

结论：`vol_target` 在当前区间不敏感，保持 0.05。

### 4) 单股上限 `max_weight`
- run 220/221/222（0.025/0.028/0.032）与 run 213 基本一致；run 223（0.035）略差。

结论：`max_weight=0.03` 足够稳健，无需提高。

### 5) 选股数量 `top_n`
- run 224（26）：CAGR 7.96%、Sharpe 0.891
- run 225（28）：CAGR 7.91%、Sharpe 0.888
- run 226（30）：CAGR 7.88%、Sharpe 0.889
- run 227（32）：CAGR 7.87%、Sharpe 0.890

结论：`top_n=26` 略优，固化为新基线。

## 历史基线（阶段性记录，已被 2026-01 新基线替换）
- `top_n=26`
- `score_smoothing_alpha=0.15`
- `max_weight=0.03`
- `max_exposure=0.20`
- `vol_target=0.05`
- `retain_top_n=10`
- `dynamic_exposure=true`
- `drawdown_tiers=0.05,0.08,0.10`
- `drawdown_exposures=0.25,0.12,0.0`
- `max_drawdown=0.10`、`max_drawdown_52w=0.10`
- 其他：`market_filter=true`、`risk_off_mode=defensive`、`idle_allocation=defensive`

代表性回测：run 224（`top_n=26` + `alpha=0.15`）。

## SHY 占比偏高的观察
- run 224 指标：`Idle_Allocation=80%`、`Idle_Symbol=SHY`、`ExposureCap=20%`。
- 说明：在 `max_exposure=0.20` 与 `idle_allocation=defensive` 下，空余仓位自动流向防御资产，且 `risk_off_pick=lowest_vol` 往往选择 SHY。

稳妥改进方向（需确认后再实施）：
1) `idle_allocation=none`：空余转现金，最稳但收益可能下降。
2) `idle_allocation=benchmark`：空余转基准，提高收益但风险上升。
3) 防御资产分散持有（推荐）：将 idle 资金按防御篮子等权分配，减少 SHY 单一占比。

## 下一步建议（如继续）
- 在新基线下测试 `retain_top_n=8/10/12` 或 `risk_off_pick=best_momentum`。
- 若要降低 SHY 占比，优先实现“防御篮子分散持有”的逻辑，再回测验证。
