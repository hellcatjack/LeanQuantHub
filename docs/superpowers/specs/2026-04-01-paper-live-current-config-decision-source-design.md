# Paper/Live 决策快照参数来源修正设计

## 背景
当前 `paper/live` 交易批次在生成 decision snapshot 时，如果未显式传入 `backtest_run_id`，会自动绑定项目最近一次成功回测（`auto_project`）或 pipeline 最近一次成功回测（`auto_pipeline`）。这会导致实盘/虚拟盘默认继承历史回测参数，而不是基于当前项目/当前 pipeline 配置做决策。

## 问题
- `paper/live` 的默认行为会被旧 AB 回测污染。
- 当前项目默认配置修改后，交易批次仍可能引用旧回测参数。
- 这与“回测、paper、live 共享同一套判断逻辑，但默认基于当前配置运行”的目标不一致。

## 目标
- 未显式指定 `backtest_run_id` 时：
  - `paper/live` decision snapshot 默认不再自动绑定任何历史回测。
  - 若带 `pipeline_id`，使用当前 pipeline 参数，标记 `backtest_link_status=current_pipeline`。
  - 若不带 `pipeline_id`，使用当前项目配置，标记 `backtest_link_status=current_project`。
- 仅当显式传入 `backtest_run_id` 时，才允许继承历史回测参数，标记 `backtest_link_status=explicit`。

## 非目标
- 不改变“显式回放某次历史回测”的能力。
- 不修改历史 snapshot / trade run 记录。
- 不改变回测引擎本身的策略判断逻辑。

## 设计
### 1. Backtest 绑定解析
修改 `resolve_backtest_run_link()`：
- 有 `explicit_backtest_run_id`：校验后返回 `(run.id, "explicit")`
- 无显式回测且有 `pipeline_id`：返回 `(None, "current_pipeline")`
- 无显式回测且无 `pipeline_id`：返回 `(None, "current_project")`

### 2. Decision Snapshot 参数来源
保留 `generate_decision_snapshot()` 的参数提取逻辑：
- `backtest_run_id=None` 时不会读取 `BacktestRun`
- 若 `pipeline_id` 存在且 pipeline 参数里有 `backtest.algorithm_parameters`，来源记为 `pipeline`
- 若也没有 pipeline 参数，则来源记为 `override` 或 `empty`

### 3. 入口统一
统一以下入口的默认行为：
- `backend/app/routes/decisions.py`
- `backend/app/services/pretrade_runner.py`

### 4. 可观测性
新的 snapshot summary / params 中继续保留：
- `backtest_run_id`
- `backtest_link_status`
- `algorithm_parameters_source`

这样可以明确区分：
- `explicit`：显式历史回测
- `current_pipeline`：当前 pipeline 配置
- `current_project`：当前项目配置

## 测试策略
- 单测 `resolve_backtest_run_link()`：未显式指定时不再自动选回测。
- 路由测试：`/api/decisions/run` 默认不写入自动回测 ID。
- PreTrade 测试：生成交易批次默认传 `backtest_run_id=None`，并记录 `current_project/current_pipeline`。
- 回归测试：显式指定 `backtest_run_id` 的路径保持不变。
