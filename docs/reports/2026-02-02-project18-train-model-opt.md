# 项目18 训练模型优化回测报告（固定 run 462 参数）

## 执行概览
- 回测窗口：2020-01-01 至 2026-01-13
- 固定参数：沿用 run 462（max_exposure=0.4, vol_target=0.045, max_weight=0.028）
- 训练模型数量：22
- 成功产出 summary 的训练模型：22
- 失败回测：1（run 498，对应 train_job_id=71；已存在成功回测 run 504 作为替代）
- DD 约束：max_dd ≤ 0.15

## Top3 训练模型（DD≤0.15 且 CAGR 最高）
1. train_job_id=83 / run_id=486 / CAGR=0.14007 / DD=0.149
2. train_job_id=87 / run_id=482 / CAGR=0.13837 / DD=0.150
3. train_job_id=81 / run_id=488 / CAGR=0.12651 / DD=0.148

## 说明
- 训练模型 run 505 长时间 queued，已重新提交并由 run 509 完成（train_job_id=70）。
- 本次评分基于 `scripts/score_train_model_opt.py`，仅统计存在 `lean_results/-summary.json` 的结果。
