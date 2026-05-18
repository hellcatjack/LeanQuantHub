# 2026-04-07 防御资产实验基线

## 目标
冻结本轮防御资产实验的控制面，确保 Layer A 到 Layer D 仅比较防御篮子或 benchmark 变化，不混入股票池、训练任务、时间窗口或风控参数漂移。

## 当前项目基线
- 项目：`18 / 初始模型项目`
- 策略算法路径：`/app/stocklean/algorithms/ml_overlay_scores.py`
- 算法版本：`6`
- 训练任务：`120`
- 分数文件：`/app/stocklean/artifacts/ml_job_120/scores.csv`
- benchmark：`SPY`
- 回测窗口：`2020-01-01` 到 `2026-03-26`
- 调仓频率：`Weekly / Monday / +30m`
- 选股数量：`top_n=36`
- 保留数量：`retain_top_n=10`
- 暴露上限：`max_exposure=0.3`
- 最大回撤：`max_drawdown=0.12`
- 52 周最大回撤：`max_drawdown_52w=0.12`
- 风险关闭模式：`risk_off_mode=defensive`
- 防御挑选规则：`risk_off_pick=best_momentum`
- 闲置仓位：`idle_allocation=defensive`
- 默认防御主标的：`SGOV`
- 当前默认防御篮子：`SGOV,VGSH`

## 当前系统边界
### 当前默认自动评估范围
当前活跃项目自动评估集合只会带入：
- 最新 decision snapshot 实际涉及的 symbols
- 项目 `risk_off_symbols / risk_off_symbol`
- 项目 `benchmark`

因此在当前运行态下，`USO/BNO/QQQ/SOXX` 不会自动进入默认评估集合。

### 当前数据支持
以下标的均已存在于 `curated_adjusted`，可用于第一阶段实验：
- 防御/利率：`SGOV`, `VGSH`, `IEF`, `TLT`
- 对冲：`GLD`
- 商品观察：`USO`, `BNO`
- 风险对照：`QQQ`, `SOXX`
- benchmark：`SPY`

## 已有可复用回测
以下历史回测与当前项目控制面一致，可直接作为 Layer A 的已完成样本：

| Layer | Run | 防御配置 | CAGR | MaxDD | Sharpe | Idle | RiskOff |
|---|---:|---|---:|---:|---:|---|---|
| A0 | 727 | `SGOV` | 7.810% | 12.800% | 0.629 | SGOV | SGOV |
| A1 | 728 | `SGOV,VGSH` | 8.282% | 12.700% | 0.718 | SGOV | SGOV |
| A2 | 729 | `SGOV,VGSH,IEF` | 7.371% | 10.100% | 0.660 | SGOV | VGSH |

说明：
- 这三组都使用算法版本 `6`、训练任务 `120`、窗口 `2020-01-01` 到 `2026-03-26`
- 与当前实验基线相比，唯一关键变量是 `risk_off_symbols`
- 因此本轮 Layer A 只需补跑 A3：`SGOV,VGSH,TLT`

## 本轮实验约束
1. Layer A 保持时间窗口固定为 `2020-01-01` 到 `2026-03-26`。
2. Layer A 保持算法版本 `6`、训练任务 `120` 不变。
3. Layer A 只修改 `risk_off_symbols`，不改 `top_n/max_exposure/max_drawdown/risk_off_pick/idle_allocation`。
4. 若后续扩展到 Layer B/C/D，再明确记录每组唯一变量。

## 长期判据
后续默认防御资产的任何升级，必须优先满足：
1. 回撤可控
2. 恢复稳定
3. 跨阶段一致性
4. 手续费与换手率不过度恶化

收益提升只能作为二级判据，不能单独决定默认值。
