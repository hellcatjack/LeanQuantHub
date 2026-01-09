# 回测优化阶段报告（Phase 4）

## 目标约束
- MaxDD_all ≤ 0.12
- MaxDD_52w ≤ 0.12
- CAGR ≥ 0.10
- Turnover_week ≤ 0.08

## 本轮调整重点
- 在 P4_ma250 基础上提升 top_n，并同步降低 max_weight。

## 回测结果
| ID | 组合标签 | MaxDD_all | MaxDD_52w | CAGR | Sharpe | Turnover_week | VolScale | MarketFilter_Count | DD_Triggers | RiskOff_Count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 148 | P4_ma250_top25 | 10.94% | 10.94% | 12.224% | 0.969 | 8.00% | 100.00% | 5 | - | 1 |
| 149 | P4_ma250_top30 | 11.43% | 11.43% | 13.191% | 1.009 | 8.00% | 100.00% | 5 | - | 1 |

## 结论
- P4_ma250_top30（ID 149）在保持回撤目标的同时，进一步提高 CAGR 与 Sharpe，综合表现最佳。

## 推荐配置（当前最优）
- market_ma_window=250
- top_n=30
- max_weight=0.04
- max_exposure=0.28
- vol_target=0.08
- risk_off_symbols=SHY,IEF,GLD,TLT
- risk_off_pick=lowest_vol
- drawdown_tiers=0.08,0.10,0.12
- drawdown_exposures=0.4,0.25,0.0
- market_filter=true
- max_drawdown=0.12
- max_drawdown_52w=0.12
- max_turnover_week=0.08

