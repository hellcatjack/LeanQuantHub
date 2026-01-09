# 回测优化阶段报告（Phase 1）

## 目标约束
- MaxDD_all ≤ 0.12
- MaxDD_52w ≤ 0.12
- CAGR ≥ 0.10
- Turnover_week ≤ 0.08

## 阶段步骤
1. 已增加门控/波动率诊断与运行时统计（DD_Current、DD_Locked、DD_Triggers、DD_Last、VolScale、MarketFilter_Count、RiskOff_Count）。
2. 已加入分层降仓（drawdown_tiers / drawdown_exposures）与防御篮子（risk_off_symbols + best_momentum/lowest_vol）。
3. 已执行小步参数搜索（6 组）。

## 参数配置（本轮固定）
- drawdown_tiers=0.08,0.10,0.12
- drawdown_exposures=0.4,0.25,0.0
- risk_off_symbols=SHY,IEF,GLD,TLT
- risk_off_lookback_days=20
- market_filter=true, market_ma_window=200
- max_drawdown=0.12, max_drawdown_52w=0.12, max_turnover_week=0.08

## 小步搜索结果
| ID | 组合标签 | MaxDD_all | MaxDD_52w | CAGR | Sharpe | Turnover_week | VolScale | MarketFilter_Count | DD_Triggers | RiskOff_Count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 136 | S1_expo0.35_vol0.08_mom | 14.48% | 14.48% | 0.897% | -0.026 | 8.00% | 100.00% | 3 | 1 | 2 |
| 134 | S2_expo0.30_vol0.08_mom | 13.45% | 13.45% | 0.443% | -0.097 | 8.00% | 100.00% | 4 | 1 | 2 |
| 135 | S3_expo0.30_vol0.06_mom | 13.45% | 13.45% | 0.443% | -0.097 | 8.00% | 100.00% | 4 | 1 | 2 |
| 137 | S4_expo0.25_vol0.06_mom | 10.34% | 10.34% | 9.306% | 0.817 | 4.51% | 100.00% | 9 | - | 1 |
| 138 | S5_expo0.30_vol0.08_lowvol | 12.20% | 12.20% | 1.172% | -0.020 | 8.00% | 100.00% | 3 | 1 | 2 |
| 139 | S6_expo0.25_vol0.08_lowvol | 9.56% | 9.56% | 9.156% | 0.837 | 4.58% | 100.00% | 9 | - | 1 |

## 关键结论
- 回撤已显著下降，S4/S6 已满足 MaxDD_all/MaxDD_52w ≤ 0.12。
- CAGR 仍低于 10%（S4 9.306%，S6 9.156%），与目标仅差约 0.7~0.9 个百分点。
- VolScale 恒为 100%，说明波动率目标未触发明显缩放（可能是区间波动低于目标或历史取数未触发缩放）。
- market_filter 触发次数明显上升（9 次），与回撤下降相关，但可能也压低收益。

## 下一步建议（Phase 2）
1. 在不放宽回撤门槛的前提下，微调 exposure 以冲过 CAGR=10%：
   - 在 S4/S6 基础上仅微调 max_exposure 到 0.27~0.28。
2. 将 drawdown_exposures 第二档从 0.25 调至 0.28（保持 0.12 时为 0），观察收益提升。
3. 若 VolScale 始终 100%，尝试降低 vol_target 到 0.05 或提高 vol_window 到 30。

