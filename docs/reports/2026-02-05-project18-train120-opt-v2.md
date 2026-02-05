# 项目18 训练120可靠方向优化回测报告（v2）

## 执行概览
- 基准 run：622（风控骨架）
- 训练任务：120
- 风险资产：VGSH,IEF,GLD,TLT
- 回测窗口：2020-01-01 ~ 最新数据
- 回测次数：24（stage1）+ 6（stage2 可选）
- 约束：MaxDD ≤ 0.15

## Top3（按 DD 最低）
1. run_id=655 / CAGR=9.223% / DD=9.500% / params={max_exposure:0.30, vol_target:0.040, max_weight:0.022, drawdown_tiers:0.05,0.09,0.12, drawdown_exposures:0.45,0.30,0.20}
2. run_id=656 / CAGR=9.223% / DD=9.500% / params={max_exposure:0.30, vol_target:0.040, max_weight:0.026, drawdown_tiers:0.05,0.09,0.12, drawdown_exposures:0.45,0.30,0.20}
3. run_id=657 / CAGR=9.223% / DD=9.500% / params={max_exposure:0.30, vol_target:0.0425, max_weight:0.022, drawdown_tiers:0.05,0.09,0.12, drawdown_exposures:0.45,0.30,0.20}

## Top3（按 CAGR 最高）
1. run_id=673 / CAGR=10.784% / DD=10.700% / params={max_exposure:0.36, vol_target:0.040, max_weight:0.022, drawdown_tiers:0.05,0.09,0.12, drawdown_exposures:0.45,0.30,0.20}
2. run_id=674 / CAGR=10.784% / DD=10.700% / params={max_exposure:0.36, vol_target:0.040, max_weight:0.026, drawdown_tiers:0.05,0.09,0.12, drawdown_exposures:0.45,0.30,0.20}
3. run_id=675 / CAGR=10.784% / DD=10.700% / params={max_exposure:0.36, vol_target:0.0425, max_weight:0.022, drawdown_tiers:0.05,0.09,0.12, drawdown_exposures:0.45,0.30,0.20}

## 结论
- 是否达标：是（全部 24 条回测 DD≤0.15）
- 推荐参数：在达标集合内，优先选 run_id=673（CAGR 10.784%，DD 10.700%）
- 说明：风控骨架显著压低回撤，但收益上限仍偏低（≈10.8% CAGR）
