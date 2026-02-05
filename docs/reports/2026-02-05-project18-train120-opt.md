# 项目18 训练120优化回测报告

## 执行概览
- 基准 run：615（风险资产已替换为 VGSH）
- 训练任务：120
- 回测窗口：2020-01-01 ~ 最新数据
- 回测次数：30
- 约束：MaxDD ≤ 0.15

## 结果概览
- **DD≤0.15 的回测结果：0 个（未达标）**

## Top3（按 DD 最低）
1. run_id=625 / CAGR=17.906% / DD=22.800% / params={max_exposure:0.60, vol_target:0.045, max_weight:0.030}
2. run_id=626 / CAGR=17.806% / DD=22.800% / params={max_exposure:0.60, vol_target:0.045, max_weight:0.040}
3. run_id=627 / CAGR=17.906% / DD=22.800% / params={max_exposure:0.60, vol_target:0.050, max_weight:0.030}

## Top3（按 CAGR 最高）
1. run_id=637 / CAGR=23.918% / DD=30.500% / params={max_exposure:0.80, vol_target:0.045, max_weight:0.030}
2. run_id=639 / CAGR=23.918% / DD=30.500% / params={max_exposure:0.80, vol_target:0.050, max_weight:0.030}
3. run_id=641 / CAGR=23.918% / DD=30.500% / params={max_exposure:0.80, vol_target:0.055, max_weight:0.030}

## 结论
- 是否达标：否（最小 DD 仍为 22.8%）
- 现象：较低 max_exposure 可明显降低 DD，但仍无法达到 15% 目标；提高 max_exposure 显著抬升 CAGR 同时拉高 DD。
- 下一步建议：若坚持 DD≤0.15，需引入更强的风险约束（例如降低 max_exposure 范围、提高 drawdown_exposures 收敛强度或降低 vol_target 上限），再进入第二轮优化。
