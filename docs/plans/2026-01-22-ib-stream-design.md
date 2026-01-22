# IB 行情订阅与缓存设计（Streaming）

> 目标：在 **IB API 可用** 的前提下，为“当前项目/当日决策快照”提供稳定的 L1 行情订阅与缓存，作为实盘/模拟盘交易的**唯一行情来源**（必要时降级到 snapshot/历史回退），并对风控/估值可复用。

## 背景
- 系统已具备 IB 配置与 snapshot/历史回退接口，但**缺少常驻 streaming 订阅**。
- 交易执行与风控需要**稳定且一致**的行情输入，避免价格来源不一致。

## 目标与范围
- 订阅范围：**当前项目 + 当日决策快照**（优先快照，缺省回退到项目主题成分）。
- 行情来源：IB L1（bid/ask/last/volume），必要时降级到 snapshot/历史回退。
- 缓存输出：`data/ib/stream/{symbol}.json` + `_status.json`。
- 非目标：不覆盖期权，不做分钟级历史回放。

## 设计原则
- **单实例执行**：多副本启动时只能一个实例订阅（JobLock）。
- **数据一致**：交易执行与风控只读取 `data/ib/stream`。
- **可降级**：IB 断线时可自动回退到 snapshot/历史回退，但标记来源。
- **可观测**：状态、订阅数量、错误需可查询并可告警。

---

## 架构与数据流
1) 订阅服务常驻（后台任务或 systemd job）。
2) 定时刷新订阅集合：
   - 若存在最新决策快照 → 使用快照 symbols。
   - 否则使用项目主题成分作为 fallback。
3) 计算差异：新增 → 订阅；移除 → 取消订阅。
4) IB streaming 更新 → 写入 `data/ib/stream/{symbol}.json`。
5) 断线或无更新 → 降级 snapshot/历史回退补写同路径文件。

## 订阅集合策略
- 输入：`project_id`（必填）、`decision_snapshot_id`（可选）。
- 优先级：决策快照 > 项目主题成分。
- 限制：可配置 `max_symbols` 防止误订阅过量。
- 刷新节奏：默认 30–60 秒。

---

## 容错与监控
### 状态机
- `connected`：IB streaming 正常。
- `degraded`：IB 连接失败/超时，使用 snapshot/历史回退。
- `disconnected`：订阅服务停止或不可用。

### 降级策略
- IB 连接失败或 10s 无更新 → `degraded`。
- 触发 snapshot/历史回退写入文件，`source=ib_snapshot|ib_history`。

### 监控与告警
- `_status.json` 记录：
  - `status`、`last_heartbeat`、`subscribed_symbols`、`ib_error_count`、`last_error`
  - `market_data_type`（realtime/delayed）
- Telegram 告警：进入 `degraded` 或 `disconnected`。

---

## 存储格式
### `data/ib/stream/{symbol}.json`
```
{
  "symbol": "SPY",
  "timestamp": "2026-01-22T09:31:00Z",
  "source": "ib_stream",
  "bid": 480.1,
  "ask": 480.2,
  "last": 480.15,
  "close": 479.8,
  "volume": 123456,
  "currency": "USD",
  "exchange": "SMART"
}
```

### `data/ib/stream/_status.json`
```
{
  "status": "connected",
  "last_heartbeat": "2026-01-22T09:31:05Z",
  "subscribed_symbols": ["SPY","NVDA"],
  "ib_error_count": 0,
  "last_error": null,
  "market_data_type": "delayed"
}
```

---

## 接口设计
- `POST /api/ib/stream/start`
  - body: `project_id`, `decision_snapshot_id?`, `refresh_interval_seconds?`, `max_symbols?`
- `POST /api/ib/stream/stop`
- `GET /api/ib/stream/status`

UI（LiveTradePage）增加：
- 行情订阅卡片：状态、订阅数量、最近更新时间、Start/Stop。

---

## 并发与安全
- `JobLock("ib_stream")` 保证单实例订阅。
- 并发调用 start 时应返回 `ib_stream_lock_busy`。

---

## 测试与验收
1) **订阅集合测试**：快照优先/主题回退。
2) **mock 模式测试**：Start → 写入 `data/ib/stream/SPY.json` → status=connected。
3) **降级测试**：模拟断线 → status=degraded → snapshot/历史回退写入。
4) **互斥测试**：并发 start → 第二实例被拒绝。

验收标准：
- 行情文件持续更新且来源可追溯。
- trade_guard 可读取并用于估值。
- UI 能显示订阅状态与订阅数量。

---

## 后续扩展
- Live 模式下引入账户/持仓同步，行情估值统一使用 streaming。
- 订阅集与“今日决策快照”自动联动。
