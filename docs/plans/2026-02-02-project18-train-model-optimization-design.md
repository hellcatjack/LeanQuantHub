# 项目18 训练模型优化设计（固定 run 462 参数）

## 目标
- 固定 run 462 的策略参数（max_exposure=0.40, vol_target=0.045, max_weight=0.028 等），对项目18**全部训练模型**执行回测。
- 在 **DD≤0.15** 的约束下，筛选 **CAGR 最大**的训练模型作为最终候选。

## 范围
- 覆盖项目18所有成功训练模型（train_job.status=success）。
- 并发控制 ≤ 8。
- 回测区间固定为 2020-01-01 ~ 2026-01-13（当前数据上限）。

## 架构与流程
1) **训练模型列表采集器**
   - 从后端获取项目18训练作业列表。
   - 过滤 status=success，形成 train_job_id 清单。

2) **固定参数回测调度器**
   - 复用 run 462 参数作为模板。
   - 每个 train_job_id 生成 payload：
     - params.algorithm_parameters：固定参数 + backtest_start/end + score_csv_path
     - params.pipeline_train_job_id：对应训练模型 ID
   - 并发 ≤ 8，自动重试与退避。
   - 每次提交写 manifest：train_job_id, run_id, params。

3) **结果评分器**
   - 遍历 manifest，对每个 run 读取 summary。
   - 过滤 DD≤0.15，按 CAGR 降序排序。
   - 输出 Top3，并生成报告。

## 错误处理策略
- 单个模型失败不影响整体流程：
  - 记录错误到 manifest（如 HTTP 500、timeout）。
- 缺失 scores.csv：
  - 标记 missing_score 并跳过。
- 进度长时间停滞：
  - 标记 stuck，保留人工处理通道。

## 可观测性与进度探针
- 每次提交时记录 manifest。
- 轮询 `/api/backtests/{id}/progress`；
- 输出实时统计：success/running/queued/failed。

## 测试策略
- 单元测试：
  - payload 构造正确（params.algorithm_parameters + pipeline_train_job_id）。
  - 500/timeout 自动重试与退避。
- 集成验证：
  - 先用最近 3 个训练模型 dry-run；
  - 确认回测结果不再一致。

## 交付物
- 训练模型优化调度脚本
- 评分脚本
- 训练模型优化报告（Top3）

## 成功标准
- 所有训练模型完成回测（或明确失败原因）。
- 输出 DD≤0.15 下 CAGR 最优训练模型。
- 报告包含 Top3 + 推荐结论。
