# IB 实盘交易连接状态面板与聚合接口设计

日期：2026-01-23

## 背景与现状
- 已有 IB 配置/连接状态接口与 LiveTrade 页面，但页面依赖多端点组合，缺少统一聚合状态。 
- 连接状态多为点检式更新，缺少面板级“统一概览数据源”。

## 目标
- 提供一个稳定、低开销的聚合状态接口，为“连接状态面板”提供唯一数据源。
- 页面统一轮询该接口，减少前端复杂度与错误分支。
- 支持增强信息：订阅数、快照缓存状态、最近订单回报、最近告警。

## 范围
- 后端新增 `GET /api/ib/status/overview` 聚合接口。
- LiveTrade 页面新增“连接状态面板”卡片组，统一轮询。
- 不在本阶段引入系统级常驻重连任务；探测由手动触发接口完成。

## 接口设计
### GET /api/ib/status/overview
返回结构（示意）：
```json
{
  "connection": {
    "status": "connected|disconnected|unknown",
    "message": "...",
    "last_heartbeat": "ISO8601",
    "updated_at": "ISO8601"
  },
  "config": {
    "host": "192.168.1.31",
    "port": 7497,
    "client_id": 101,
    "account_id": "U1***45",
    "mode": "paper|live",
    "market_data_type": "realtime|delayed|frozen",
    "api_mode": "ib|mock",
    "use_regulatory_snapshot": false
  },
  "stream": {
    "status": "starting|running|stopped|unknown",
    "subscribed_count": 12,
    "last_heartbeat": "ISO8601",
    "ib_error_count": 0,
    "last_error": null,
    "market_data_type": "realtime"
  },
  "snapshot_cache": {
    "status": "fresh|stale|unknown",
    "last_snapshot_at": "ISO8601",
    "symbol_sample_count": 5
  },
  "orders": {
    "latest_order_id": 123,
    "latest_fill_id": 456,
    "latest_order_status": "submitted|filled|rejected|...",
    "latest_order_at": "ISO8601"
  },
  "alerts": {
    "latest_alert_id": 789,
    "latest_alert_at": "ISO8601",
    "latest_alert_title": "..."
  },
  "partial": false,
  "errors": [],
  "refreshed_at": "ISO8601"
}
```

## 数据来源与聚合策略
- `connection`：`ib_connection_state`。
- `config`：`ib_settings`，`account_id` 脱敏。
- `stream`：`ib_stream` 状态文件。
- `snapshot_cache`：读取 `data_root/ib/stream` 最近快照文件时间戳（或以现有工具函数推断）。
- `orders`：`trade_orders`/`trade_fills` 最近一条。
- `alerts`：`audit_logs` 最近一条（trade/ib 相关事件）。

## 错误处理
- 子项读取失败：`partial=true`，`errors[]` 记录字段名与错误，HTTP 200。
- 仅当基础配置或 DB 访问失败时返回 503。
- 前端对 `partial` 显示“部分不可用”，但不阻断页面。

## 前端改动
- LiveTrade 页面新增“连接状态面板”卡片组，改为轮询 `overview` 接口。
- 轮询建议 5 秒；首屏加载立即请求一次。
- 保持现有独立工具区（合约刷新/行情健康/历史补齐）不变。

## 测试计划
- 后端：
  - 正常路径返回全字段；
  - 子项失败时 `partial=true` + `errors[]`；
  - `account_id` 脱敏校验。
- 前端：
  - `overview` 正常渲染；
  - `partial` 场景展示状态；
  - 触发“探测”后刷新 `overview`。

## 验收标准
1) 未配置：面板显示“未配置/只读”且 API 正常返回占位。
2) 断线：`connection.status=disconnected` 并展示错误摘要。
3) 连通：`connection.status=connected`，`refreshed_at` 随轮询更新。

## 备注
- 本阶段完成后需更新 `docs/todolists/IBAutoTradeTODO.md` 对应项状态。
