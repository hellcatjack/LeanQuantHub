# Paper Covered Call Receipt Design

## 目标
为 `paper-only covered call submit` 增加提交后回执核对层。该层只读，不下单，不改变股票主路径。

## 范围
- 新增后端 receipt 服务与路由
- 输入：`mode/review_id/command_id`
- 数据源：
  - `command_results/<command_id>.json`
  - `open_orders.json`
  - `gateway_runtime_health.json`
  - `review_bundle.json`
- 输出：更稳的 receipt 状态

## 状态模型
- `rejected`
  - `command_result.status` 属于拒绝类状态
- `submitted/open_confirmed`
  - `command_result.status=submitted` 且 open orders 能按 `brokerage_ids/tag/underlying_symbol` 匹配
- `submitted/submitted_unconfirmed`
  - `command_result.status=submitted`，但当前 open orders 未匹配到
- `submitted/open_orders_stale`
  - 已 submitted，但 open orders 快照 stale
- `pending/pending_no_result`
  - 尚未读到 command result
- `pending/pending_runtime_unhealthy`
  - 尚未读到 command result，且运行态不健康

## 接口
- `POST /api/trade/options/covered-call/receipt`
- 仅允许 `mode=paper`

## 错误处理
- `paper_only` -> 400
- `review_id_required` -> 400
- `command_id_required` -> 400
- `review_not_found` / `review_bundle_invalid` -> 409

## 审计与产物
- 产物目录：`artifacts/options_receipt_<timestamp>/summary.json`
- 首版不新增数据库持久化，仅落盘 JSON

## 非目标
- 不做真实期权改单/撤单
- 不做前端 UI
- 不做 live 模式
