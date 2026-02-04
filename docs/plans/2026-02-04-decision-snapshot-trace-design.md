# 决策快照追溯与列表设计

## 背景
当前决策快照只展示最新/预览，缺少明确的快照列表与详情描述；同时无法追溯“该快照对应哪一次回测”。需要在项目页补齐列表与追溯链路，形成可审计的记录。

## 目标
- 建立 `decision_snapshots` ↔ `backtest_runs` 的可追溯关系（可选）。
- 前端提供 `backtest_run_id` 输入，支持显式绑定。
- 项目页提供决策快照列表与详情展示。

## 范围
- 后端新增 `decision_snapshots.backtest_run_id` 字段与列表 API。
- 决策快照生成时写入追溯来源与状态。
- 前端在“算法 → 决策快照”增加输入与历史列表。

## 数据模型
- `decision_snapshots.backtest_run_id`：INT 可空。
- 追溯状态 `backtest_link_status`：`explicit` / `auto_pipeline` / `auto_project` / `missing`（存入 summary 与审计日志）。

## 追溯规则
1) 前端传入 `backtest_run_id`：校验存在且 project_id 匹配，否则 400。
2) 未传入：若 `pipeline_id` 存在，取该 pipeline 最近成功回测。
3) 否则取项目最近成功回测。
4) 无匹配则为空，并标注 `missing`。

## API 变更
- `POST /api/decisions/preview|run` 请求体新增 `backtest_run_id`。
- `GET /api/decisions`：分页列表（project_id 必填），支持 status / snapshot_date / backtest_run_id / keyword 筛选。
- `GET /api/decisions/{id}`：详情包含 `backtest_run_id`。

## 前端交互
- 决策快照表单新增 `backtest_run_id` 输入框（位于训练作业与快照日期下方）。
- 新增“快照历史”列表：显示 ID / 状态 / snapshot_date / backtest_run_id / created_at。
- 点击列表切换详情面板；空值显示“未绑定回测”。

## 错误处理与审计
- 显式 backtest_run_id 校验失败返回 400（`backtest_run_not_found` / `backtest_run_project_mismatch`）。
- 审计日志记录 backtest_run_id 与 link_status。

## 测试
- 后端：追溯规则单测 + 列表分页/筛选单测 + 显式 backtest_run_id 校验失败测试。
- 前端：手工验证输入/列表/详情/筛选。

## 验收标准
- 列表可查看历史快照；详情展示齐全。
- backtest_run_id 可手动输入并正确追溯。
- 无回测关联时有清晰提示。
