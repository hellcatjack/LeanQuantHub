# 回测优化阶段报告（Phase 3）

## 目标约束
- MaxDD_all ≤ 0.12
- MaxDD_52w ≤ 0.12
- CAGR ≥ 0.10
- Turnover_week ≤ 0.08

## 本轮调整重点
- 在 P4（低波防御篮子 + max_exposure 0.28）基础上，测试 market_ma_window 150/250。

## 回测结果
| ID | 组合标签 | MaxDD_all | MaxDD_52w | CAGR | Sharpe | Turnover_week | VolScale | MarketFilter_Count | DD_Triggers | RiskOff_Count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 146 | P4_ma150 | 11.21% | 11.21% | 11.884% | 0.944 | 8.00% | 100.00% | 10 | - | 1 |
| 147 | P4_ma250 | 11.59% | 11.59% | 12.674% | 0.965 | 8.00% | 100.00% | 5 | - | 1 |

## 结论
- 两组均满足四项硬约束。
- P4_ma250 的 CAGR 和 Sharpe 更高，回撤略升但仍低于 0.12，综合表现更优。

## 推荐配置（当前最优）
- market_ma_window=250
- max_exposure=0.28
- vol_target=0.08
- risk_off_symbols=SHY,IEF,GLD,TLT
- risk_off_pick=lowest_vol
- drawdown_tiers=0.08,0.10,0.12
- drawdown_exposures=0.4,0.25,0.0

