# Trade Strategy Snapshot 回测绑定一致性设计

## 背景
交易批次已经通过 `decision_snapshot` 执行，但 `trade_run.params.strategy_snapshot` 仍默认取当前项目配置。这会造成同一笔交易里：
- `decision_basis/backtest_run_id` 指向 snapshot 绑定的历史回测
- `strategy_snapshot.backtest_params` 却显示当前项目配置

## 目标
- 当 `decision_snapshot.backtest_run_id` 存在时，交易相关配置快照默认对齐到该回测 Run。
- 当 `decision_snapshot.backtest_run_id` 不存在时，继续回退当前项目配置。
- 统一 `pretrade` 自动建批次和 `/api/trade/runs` 手工建批次。

## 设计
### 1. 新增统一构造函数
新增 `trade_strategy_snapshot` 服务，统一输出：
- `backtest_run_id`
- `backtest_link_status`
- `backtest_params`
- `benchmark`
- `backtest_start`
- `backtest_end`
- 当前项目配置版本元数据

### 2. 优先级
- `decision_snapshot.backtest_run_id` 对应的 `BacktestRun.params`
- 当前项目配置回退

### 3. 入口接入
- `backend/app/services/pretrade_runner.py`
- `backend/app/routes/trade.py`

## 测试
- `pretrade` 创建 TradeRun 时，`strategy_snapshot` 应继承 snapshot 绑定回测参数。
- `/api/trade/runs` 创建 TradeRun 时，`strategy_snapshot` 应继承 snapshot 绑定回测参数。
