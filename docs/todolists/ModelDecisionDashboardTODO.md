# 模型当日决策看板 TODO（面向模拟盘/实盘）

## 目标
- 让用户直观看到“当日模型选择结果”、风险门控状态、可交易标的池与数据截止时间。
- 形成可审计的“决策快照”，可对比历史表现与回测结果。
- 与 PreTrade Checklist 形成闭环：数据 → PIT 快照 → 评分 → 当日决策。

## 范围与原则
- 只基于当日可用数据，避免前视。
- 决策逻辑与回测/策略逻辑一致，避免出现“看板结果 ≠ 真实交易”。
- 所有关键字段保存为快照，保证可追溯。

## Phase 0：现状梳理与口径固化
- 明确“当日决策 as-of 时间”口径（使用 PIT 快照日 + 上一交易日收盘）。
- 明确“数据截止时间”（价格、PIT 基本面、shares_outstanding）。
- 明确交易日历来源与风控门控使用的价格口径（adjusted_only）。

## Phase 1：后端决策快照引擎
1) 新增服务层 `decision_snapshot`（或复用现有评分/回测逻辑）
   - 输入：project_id、train_job_id、snapshot_date、backtest_params/strategy_params。
   - 输出：Top-N 名单、目标权重、风险门控状态、现金/防御占比。
2) 抽取/复用与 `ml_overlay_scores.py` 一致的过滤与权重逻辑：
   - missing_price / missing_pit / liquidity / halt 等过滤原因可追溯。
   - risk gate / market_filter 触发原因写入快照。
3) 决策快照落盘：
   - `artifacts/decision_snapshots/{project_id}/{date}/`
   - 文件：`decision_summary.json`、`decision_items.csv`、`filter_reasons.csv`。

## Phase 2：API 设计
- `POST /api/decisions/preview`
  - 不落盘，仅返回 Top-N + 统计概览（用于 UI 实时预览）。
- `POST /api/decisions/run`
  - 落盘并返回决策快照 ID。
- `GET /api/decisions/latest?project_id=`
  - 获取最新快照与文件路径。
- `GET /api/decisions/{id}`
  - 返回完整快照详情 + 统计摘要。

## Phase 3：前端看板（项目页/算法页）
1) “当日模型决策”卡片
   - 模型/训练ID、score_csv_path、预测期、快照日、as-of 时间。
   - 可交易标的数 / 被过滤数（及原因分布）。
   - 风控状态：market_filter / max_dd / exposure。
2) Top-N 选股表
   - Symbol / Score / Rank / 权重 / 主题 / 过滤原因。
   - 支持筛选“入选/被过滤”。
3) 组合计划概览
   - 目标仓位、现金占比、防御资产占比。
4) 数据审计展示
   - PIT 覆盖率、pit_market_cap 缺失数、价格缺失数。

## Phase 4：联动与审计
- Checklist 完成后自动触发决策快照（可配置开关）。
- 决策快照与回测结果建立关联（同一模型 ID、同一参数集）。

## Phase 5：测试计划
- 单元测试：决策快照结果与回测同参数输出一致性。
- Playwright：
  - 发起快照 → 页面展示 → 过滤原因展开 → 导出文件路径可见。
  - 项目16测试：确认 Top-N、风险门控与数据截止时间正常。

## 交付标准
- UI 能清晰说明“当日选择结果”与“数据口径”。
- 任一快照可复现并追溯输入数据与过滤逻辑。
- 决策结果与策略逻辑一致（与回测一致性验证通过）。
