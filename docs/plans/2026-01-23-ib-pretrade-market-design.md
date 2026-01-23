# IB PreTrade 行情快照设计（Phase 0–1）

## 目标
在 Phase 0–1 范围内完成“连接管理 + 合约缓存 + PreTrade 触发短时行情快照”的设计，确保实盘/模拟盘交易在执行前获取一致的 IB 行情快照，避免常驻订阅带来的成本与稳定性风险。

## 架构与数据流
本阶段聚焦“PreTrade 触发快照”，不引入常驻订阅。复用现有 `ib_settings / ib_connection_state / ib_contract_cache / ib_market / ib_stream` 模块：PreTrade 执行前新增 `market_snapshot` 步骤（非常驻），从项目配置读取 `market_data_type`（默认 realtime），结合 `decision_snapshot_id` 或项目主题池生成 symbol 列表。快照通过 `IBRequestSession` 拉取 L1（bid/ask/last/volume），写入 `data/ib/stream/<SYMBOL>.json`，并更新 `stream/_status.json`（`last_heartbeat`、订阅列表、错误摘要）。引入 TTL（默认 30 秒，可项目配置）实现幂等：若 `last_heartbeat` 在 TTL 内且 symbols 一致，则跳过请求并复用快照。连接异常时将 `ib_connection_state` 标记为 `degraded`，在下一次成功快照后自动清理 `degraded_since`（由 `update_ib_state`/`build_ib_health` 统一处理）。

## 配置、接口与错误处理
配置采用“项目优先、全局兜底”：`IBSettings.market_data_type` 为全局默认；项目配置新增 `project.config.trade.market_data_type` 与 `project.config.trade.market_snapshot_ttl_seconds`（默认 30 秒）。PreTrade 步骤读取项目配置→IBSettings→默认值，保证无配置也可运行。接口上复用 `POST /api/ib/market/snapshot`（`IBMarketSnapshotRequest`）作为快照能力；PreTrade 可直接调用服务层 `fetch_market_snapshots` 并落地文件。状态与健康检查复用 `GET /api/ib/stream/status` 与 `GET /api/ib/health`：快照阶段遇到连接错误或 IB 错误码（如 1100/1102）写入 `stream/_status.json`，更新 `ib_connection_state` 为 `degraded`，记录 `last_error` 与 `ib_error_count`；成功刷新时清除 `last_error` 并重置计数。为避免重复请求，TTL 内返回缓存并在 PreTrade step artifact 中记录 `skipped=true` 便于审计。

## 测试与验收
测试采用 TDD：
1) TTL 命中时快照跳过；
2) symbol 列表变化触发重新快照；
3) IB 连接异常时 `ib_connection_state` 置 `degraded` 且 `stream/_status.json` 写入 `last_error`；
4) 成功后清理 `last_error` 与 `degraded_since`。
单测以 stub/mocking 替代真实 IB 连接，避免外部依赖不稳定。集成验证路径：
- PreTrade 流程触发快照，验证 `data/ib/stream/*.json` 与 `stream/_status.json` 更新；
- 调用 `POST /api/ib/market/snapshot` 并验证返回与落地一致。
验收标准：Paper 模式下 PreTrade 触发快照后 30 秒内重复触发不会再次请求（日志/step artifact 可见 skipped）；连接异常时 1 次请求即可记录错误并阻止交易继续（PreTrade step 失败或警告）。
