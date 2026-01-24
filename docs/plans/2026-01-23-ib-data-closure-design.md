# IB 数据闭环设计方案（Phase B）

**目标：** 以“实时行情订阅 → 快照缓存 → 交易/风控消费 → 监控展示”为核心，形成最小可用的数据闭环，优先服务模拟盘/实盘交易。

**范围：** 订阅任务按需启动；快照仅保留最新；前端参考 Yahoo 财经风格展示标的信息；交易/风控在行情缺失时回退本地快照。

## 1) 架构与数据流
- UI 通过 `/api/ib/stream/start` 发起订阅任务（按项目/快照/最大数量生成 symbols）。
- 订阅任务连接 TWS/IB Gateway，实时拉取 tick，并写入：
  - `data/ib/stream/{symbol}.json`（仅保留最新快照）
  - `data/ib/stream/_status.json`（订阅状态与心跳）
- UI 通过 `/api/ib/stream/status` 与 `/api/ib/status/overview` 展示连接/订阅健康。
- 交易与风控读取快照：当 IB 行情不可用或延迟时，读取本地快照作为回退来源。

## 2) 错误处理与监控
- 订阅任务采用“软失败 + 状态降级”：连接失败/订阅失败/心跳超时 → `status=degraded`、记录 `last_error` 与 `ib_error_count`。
- 连接恢复后自动清理 `degraded_since`，恢复 `status=connected`。
- 快照落盘失败保留旧快照并累积错误计数；读取侧根据 `timestamp` 判断“stale”。
- 监控展示：连接状态、订阅状态、订阅数量、快照时间、最近错误。
- 告警先复用 Telegram，仅对“断线/恢复/连续错误阈值”告警。

## 3) UI/UX（参考 Yahoo 财经）
- 行情快照卡片默认展示：
  - **价格**、**涨跌/涨幅**、**成交量**（Option 1）
- 可展开显示：当日高/低、开盘/昨收、Bid/Ask、更新时间等。
- 清晰标注数据来源：IB 实时/延迟与快照更新时间。
- 状态徽章：connected / degraded / disconnected。

## 4) 实现要点（高层）
- 后端新增订阅任务 Runner（按需启动/停止）。
- 现有 `ib_stream` 写入快照与状态文件；与 `ib_market` 复用合同解析与 IB API。
- `trade_guard` / `trade_executor` 在行情不可用时读取本地快照。
- 前端 LiveTrade 页面新增行情快照卡片（Yahoo 风格）。

## 5) 测试与验收
- 后端单测：快照存在/过期/缺失的回退路径；订阅状态文件字段完整性。
- 前端测试：快照为空/过期/正常三态；状态徽章与时间格式正确。
- 验收：触发订阅后 10s 内 UI 可见快照；断线进入 degraded，恢复后状态清除并刷新时间。
