# IB Client ID 冲突治理与健康探针设计

## 背景与问题
当前直连下单会为每个订单启动独立的 Lean 进程，但所有进程都复用同一个 `ib-client-id`（由 `project_id` 派生）。在并发场景下，多个进程连接同一 TWS/Gateway 时触发 API 326 错误（client id 已被占用），导致订单无法执行。与此同时，`lean-bridge-output-dir` 使用全局目录，缺乏“每进程独立心跳/事件”的可观测性，TWS 崩溃或 Lean 进程异常后无法可靠回收连接与释放 client id。

## 目标
- 并发提交直连订单时，保证 **client id 全局唯一且可回收**。
- 提供 **Lean 进程健康度探针**，可在 TWS 崩溃或进程异常时自动回收。
- 在 client id 池耗尽时，给出明确的可控错误返回，而不是触发 326。

## 约束与事实
- IB API 要求每个连接使用唯一 clientId，同一 TWS/Gateway 最多 32 个客户端连接。
- IB 错误 326 表示 client id 已被占用，必须改用唯一 id。
- QuantConnect 文档对 IB 错误处理要求参考 TWS API 错误码说明。

## 方案概述（推荐）
采用 **Client ID 池 + DB 租约 + 健康探针**：
1) **Client ID 池**：初始化一段连续的 client id（默认 32 个），分配时事务性占用，防止重复。
2) **租约记录**：每次分配时记录 `client_id / order_id / pid / output_dir / acquired_at / last_heartbeat / status`。
3) **独立输出目录**：每个直连订单使用独立 `lean-bridge-output-dir`（例如 `.../lean_bridge/direct_{order_id}`），便于单进程心跳与事件判断。
4) **健康探针**：周期性检查 PID 存活、`lean_bridge_status.json` 心跳、`execution_events.jsonl` 更新；若异常超过阈值，自动 kill 进程并释放租约。
5) **失败回收**：若检测到 326 或健康异常，标记订单失败并释放 client id。

## 数据模型（建议）
新增表 `ib_client_id_leases`（或 `ib_client_id_pool`）：
- `client_id` (唯一)
- `status` (free/leased/released/failed)
- `order_id`
- `pid`
- `output_dir`
- `lease_token`
- `acquired_at`, `last_heartbeat`, `released_at`
- `release_reason`

## 接口与配置改动
- `build_execution_config` 新增可选参数：`client_id`、`lean_bridge_output_dir`。
- 直连下单流程：先创建订单与 intent → 分配 client id → 生成 config（含独立输出目录）→ 启动 Lean（`Popen` 获取 PID）→ 记录租约。
- 新增配置：
  - `ib_client_id_pool_base`
  - `ib_client_id_pool_size`（默认 32）
  - `ib_client_id_lease_ttl_seconds`
  - `lean_bridge_heartbeat_timeout_seconds`

## 健康探针策略
- **活性判定**：PID 存活 + 心跳文件更新时间（例如 60s 阈值）。
- **异常处理**：超时/缺失 → 标记租约失败 → 自动 kill 进程 → 释放 client id。
- **池耗尽**：返回 `client_id_busy`（409），避免触发 326。

## 测试与验证
- 单测：分配/释放/回收逻辑、池耗尽错误、并发占用冲突保护。
- 单测：配置生成包含 `ib-client-id` 与独立输出目录。
- 集成干跑：mock IB 模式下直连下单，验证租约创建与释放。
- 手动验证：并发下单不重复；停 TWS/kill 进程后租约自动释放。

## 参考资料
- https://interactivebrokers.github.io/tws-api/classIBApi_1_1EClientSocket.html
- https://interactivebrokers.github.io/tws-api/message_codes.html
- https://www.quantconnect.com/docs/v2/lean-cli/live-trading/brokerages/interactive-brokers
- https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/interactive-brokers
