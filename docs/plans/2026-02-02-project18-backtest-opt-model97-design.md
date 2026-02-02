# 项目18 回测优化（训练模型97）设计

## 目标
- 约束：最大回撤（DD）≤ 0.15。
- 优化目标：在约束内最大化 CAGR。
- 回测区间：2020-01-01 至今。
- 项目：#18。
- 训练模型：train_job_id=97。
- 基线中心：回测 run_id=514 的参数。
- 搜索规模：80 次候选（并发 ≤ 8）。

## 输入与数据源
- 基线参数：`/api/backtests/514` 的 `params.algorithm_parameters`。
- 项目配置兜底：`/api/projects/18/config`（用于补齐缺失参数/默认值）。
- 训练模型绑定：提交回测时写入 `params.pipeline_train_job_id=97`。
- 回测区间：写入 `algorithm_parameters.backtest_start=2020-01-01`，`backtest_end` 为空或取项目默认。

## 参数空间与搜索策略
- 方案：随机/贝叶斯（若无现成贝叶斯引擎，退化为“自适应随机”）。
- 参数范围（精简 8 核心参数，围绕基线局部扰动）：
  - max_weight
  - max_exposure
  - vol_target
  - max_drawdown
  - top_n
  - retain_top_n
  - max_turnover_week
  - market_ma_window
- 约束：
  - retain_top_n ≤ top_n
  - 其它参数按类型与范围裁剪
- 执行策略：
  - 先随机 40 组覆盖范围
  - 以当前最优 10 组为中心进行自适应扰动，再随机 40 组
  - 全程去重与约束校验

## 输出
- manifest（jsonl）：记录参数、run_id、状态
- summary.csv：全量结果（CAGR/DD/Sharpe/Sortino 等）
- top10.json：满足 DD ≤ 0.15 的 TOP10（按 CAGR 排序）

## 进度探针
- 每次提交与状态变更落地到 manifest
- 运行中/完成/失败状态持续更新
- 80 次完成后汇总输出
