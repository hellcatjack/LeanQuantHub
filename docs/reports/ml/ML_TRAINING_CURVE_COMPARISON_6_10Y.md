# LGBM Ranker 训练曲线与指标对比（训练集 6–10 年）

说明：指标取 walk-forward 每窗 valid NDCG@50 的均值与标准差，曲线为各窗口训练/验证曲线的均值聚合。

| 训练年限 | Job ID | 指标 | valid均值 | valid标准差 | 平均最佳迭代 | 曲线文件 |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | 23 | ndcg@50 | 0.4150 | 0.0125 | 0.0 | artifacts/ml_job_23/output/curve.svg |
| 7 | 24 | ndcg@50 | 0.4151 | 0.0135 | 0.0 | artifacts/ml_job_24/output/curve.svg |
| 8 | 25 | ndcg@50 | 0.4139 | 0.0168 | 0.0 | artifacts/ml_job_25/output/curve.svg |
| 9 | 26 | ndcg@50 | 0.4149 | 0.0171 | 0.0 | artifacts/ml_job_26/output/curve.svg |
| 10 | 27 | ndcg@50 | 0.4154 | 0.0150 | 0.0 | artifacts/ml_job_27/output/curve.svg |
