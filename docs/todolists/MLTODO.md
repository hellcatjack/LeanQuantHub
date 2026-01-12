# ML TODO

## 当前数据现状（最近核对）
- 价格数据：`curated_adjusted` 目录下现有 21118 个标的
- Alpha 股票清单：`alpha_symbol_life.csv` 中 assetType=Stock 共 14860 个标的
- PIT 周度快照：1999-11-05 ～ 2025-12-26，共 1365 期（`data/universe/pit_weekly/`）
- PIT 基本面覆盖：缺失清单 249 个（`data/universe/fundamentals_missing.csv`）
- 基本面长期排除清单：249 个（`data/universe/fundamentals_exclude.csv`）
- 价格排除清单：78 个（`data/universe/exclude_symbols.csv`）
- 数据覆盖收口报告：`artifacts/data_coverage_report.md`

## 配置说明（回测窗口与资产过滤）
- `backtest_start` / `backtest_end`：限定回测区间（YYYY-MM-DD），留空即全量（默认空）。
- `universe.asset_types`：资产类型白名单（默认 `["STOCK"]`），用于排除 ETF/ADR。
- `universe.pit_universe_only`：只使用 PIT 周度快照股票池（默认 `false`），减少 not_in_pit 过滤。

## 完成情况
- [x] PIT 周度快照脚本/任务入口与数据页触发已就绪，支持生成快照与质量摘要
- [x] 交易日历与调仓规则固化：以 SPY 交易日历为准、周一开盘调仓、快照取上一个交易日收盘；明确时区与交易时段
- [x] 股票生命周期与映射基础落地：接入 symbol_map，支持别名/改名映射并应用到回测与 PIT 快照过滤
- [x] 价格数据质量扫描/修复脚本落地：覆盖缺失/重复/异常收益检测，可选修复输出
- [x] 公司行为口径固化：回测默认使用复权价（adjusted_only），Lean 回测读取 price_source_policy 并在 UI 标注口径
- [x] Universe 规则落地：低价/流动性/停牌过滤 + 每次调仓集合记录
- [x] PIT 财务/因子接入：训练/推理支持周度快照，覆盖阈值与缺失策略可配
- [x] 特征与标签对齐：特征截止至快照日收盘，标签从下一交易日开盘起算
- [x] 周度信号/权重生成：支持 ML 分数与主题权重，输出 signals/weights 快照
- [x] 回测执行细则：仓位限制、换手约束、交易日/时段限制已落地
- [x] 验证与回归初版：完成全量回测 + 泄露/幸存者偏差审计报告（`artifacts/full_backtest/audit_report.md`）
- [x] 自动化流程基础：周度 PIT 快照/基本面/回测串联 + 状态日志落地 + 项目页展示入口
- [x] 自动化调度（cron）：周一 08:00 ET 触发周度自动化（可调整）
- [x] 算法模块融合：策略来源选择 + 基线因子打分任务入口（算法页）

## 待办清单（按顺序执行）
1. ~~生命周期异常收口：处理 Alpha delist 与价格覆盖冲突（5 个样本），补充多段生命周期或二次上市映射策略~~（已完成）
2. ~~数据覆盖收口：明确缺失/剔除策略（249 基本面缺失 + 回测缺失复权价），形成长期白名单/黑名单与覆盖率报表~~（已完成）
3. ~~自动化流程：周期性刷新 PIT 快照 → 触发周度回测 → 状态与告警 → UI 展示最近一次运行状态/日志入口~~（已完成）
4. ~~结果展示一致性：summary/DB/UI 对齐 artifact 输出路径，保证日志与关键输出可追溯~~（已完成）

## 策略落地 TODO（PIT 周度）
1. ~~基线因子方案：确定因子列表（动量/质量/估值/低波/流动性）与权重、标准化与截尾规则~~（已完成：`configs/factor_scores.json`）
2. ~~因子计算落地：实现 PIT 滞后 + 周度快照因子表生成（含缺失/异常处理）~~（已完成：`scripts/build_factor_scores.py`）
3. ~~评分与选股规则：按主题内横截面打分 + TopN/权重分配规则~~（已完成：`configs/portfolio_weights_factor.json` + `score_top_n`）
4. 交易约束固化：最大持仓、换手、流动性阈值、停牌/异常剔除
5. 回测对比基线：主题权重 vs 因子基线 vs 等权基准（统一成本/口径）
6. ML 增强模型：训练轻量排名模型（线性/树模型），输出 scores.csv
7. ML 集成回测：用 scores.csv 进行周度选股回测，并与基线对比
8. 稳定性评估：IC/RankIC、分层回测、敏感性分析与样本外验证
9. 周度生产化流程：周期性更新因子/评分 + 自动回测 + 指标与告警
