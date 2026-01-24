# Lean IB Bridge 设计（禁止直连 IB API）

> 目标：**系统内账户/持仓/行情可视化完全由 Lean 输出桥接提供**，后端不再直连 IB API。执行链路统一走 Lean IB Brokerage。

## 背景与现状评估
- 现有系统存在两条并行链路：
  1) **IB 直连数据/账户/stream**：`ib_market/ib_stream/ib_account` + `/api/ib/*`。
  2) **IB 直连下单**：`ib_execution.py → ib_order_executor.py → trade_executor.py`。
- 已新增 Lean 执行骨架：`trade_order_intent.py`、`lean_execution.py`（配置/启动/事件 ingest skeleton）。
- 需求变更：**禁止 IB API 直连**，所有可视化数据必须来自 Lean 输出/日志/事件桥接。

## 目标与非目标
### 目标
- 执行统一来源：Lean IB Brokerage。
- 可视化统一来源：Lean Bridge 输出文件。
- 保持 `/api/ib/*` 的读取兼容（内部改为读 Lean Bridge）。
- 交易与审计可回溯（订单、成交回写 DB）。

### 非目标
- 不在本阶段实现 Lean 侧复杂 PnL 分解或历史回补。
- 不保留任何 IB API 直连数据或下单路径。

## 核心决策
- **移除**所有 IB API 直连执行与数据获取逻辑。
- **采用 Lean ResultHandler 输出桥接**（自定义 `LeanBridgeResultHandler`），后端仅 ingest 输出文件。
- **`/api/ib/*` 仅保留读接口**（配置/订阅/历史补齐等写操作下线）。

## Lean Bridge 输出规范
输出目录：`/app/stocklean/artifacts/lean_bridge/`

### 文件与字段（JSON）
1) `account_summary.json`
```json
{
  "account": "U123456",
  "currency": "USD",
  "NetLiquidation": 100000,
  "TotalCashValue": 45000,
  "AvailableFunds": 44000,
  "EquityWithLoanValue": 100000,
  "timestamp": "2026-01-24T10:00:00Z"
}
```
2) `positions.json`
```json
[
  {
    "symbol": "AAPL",
    "quantity": 10,
    "average_price": 180.5,
    "market_price": 182.1,
    "market_value": 1821,
    "unrealized_pnl": 16,
    "timestamp": "2026-01-24T10:00:00Z"
  }
]
```
3) `quotes.json`
```json
[
  {
    "symbol": "AAPL",
    "bid": 182.0,
    "ask": 182.2,
    "last": 182.1,
    "volume": 120000,
    "timestamp": "2026-01-24T10:00:01Z",
    "source": "ib"
  }
]
```
4) `execution_events.jsonl`
```json
{"order_id": 123, "symbol": "AAPL", "status": "FILLED", "filled": 10, "avg_price": 182.1, "exec_id": "123-1", "time": "2026-01-24T10:00:05Z"}
```
5) `lean_bridge_status.json`
```json
{
  "last_seen_utc": "2026-01-24T10:00:10Z",
  "last_account_write": "2026-01-24T10:00:00Z",
  "last_positions_write": "2026-01-24T10:00:00Z",
  "last_quotes_write": "2026-01-24T10:00:01Z",
  "last_event_append": "2026-01-24T10:00:05Z",
  "last_error": null,
  "event_lag_ms": 1200
}
```

### 频率建议
- account/positions：30~60s
- quotes：1~5s
- events：实时追加

## 后端 Bridge 服务设计
新增 `lean_bridge.py`（或同名服务）用于：
- 读取 Lean Bridge 文件并写入缓存与 DB。
- 写入桥接健康状态：`lean_bridge_status.json`。

### 写入策略
- **缓存**：`data/lean_bridge/cache/*.json`（UI 快速读取）。
- **DB 回写**：`trade_orders/trade_fills` 幂等写入（按 `exec_id` 或 `order_id+time` 去重）。

### 错误与降级
- 文件缺失 → 标记 `stale=true`，保留旧缓存。
- JSON 解析失败 → 记录 `last_error`，不覆盖旧值。
- 事件重复 → 去重写入。
### 文件写入保证
- `account_summary.json/positions.json/quotes.json` 采用**原子写入**（临时文件 + 覆盖）。
- `execution_events.jsonl` 使用**追加写**；超过阈值（如 50MB）进行轮转（`execution_events.YYYYMMDD.jsonl`）。

### 可观测性
- `lean_bridge_status.json`：`last_seen` / `last_error` / `stale_flags` / `event_lag_ms`。
- UI 实盘交易页展示桥接状态与更新时间。

## 接口兼容策略
- `/api/ib/*` 保留为**只读**，数据来源改为 Lean Bridge 缓存。
- 移除或禁用写操作：
  - 订阅/停止订阅
  - 历史补齐
  - 合约刷新
  - 直连健康探测

## 清理范围（IB 直连相关）
### 必须移除（执行链路）
- `backend/app/services/ib_execution.py`
- `backend/app/services/ib_order_executor.py`
- `backend/app/services/ib_orders.py`
- 相关测试：`test_ib_execution_*`、`test_trade_executor_ib.py` 等

### 必须替换（数据链路）
- `ib_market.py`、`ib_stream.py`、`ib_stream_runner.py`、`ib_account.py`、`ib_history_runner.py`
- `routes/ib.py` 改为读取 Lean Bridge 输出

### 执行链路调整
- `trade_executor.py`：仅生成订单意图 + 触发 `lean_execution.launch_execution`
- `lean_execution.py`：事件 ingest → 回写订单/成交

## 验收标准
1) 系统 UI 可展示账户/持仓/行情（不直连 IB API）。
2) Lean 输出停止时 UI 显示“数据过期”。
3) 订单/成交回写与 Lean 事件一致，重复 ingest 不重复写入。
4) 交易执行仅走 Lean IB Brokerage。

## Lean 侧落地（ResultHandler）
### 处理器名称
- `StockLean.LeanBridgeResultHandler`（建议放在 `Lean_git/Engine/Results` 或 `Lean_git/Engine/Results/Bridge`）

### 配置落地
- `Launcher/config.json` 的 live 环境新增配置：
  - `"result-handler": "StockLean.LeanBridgeResultHandler"`
  - `"lean-bridge-output-dir": "/app/stocklean/artifacts/lean_bridge"`

### 输出来源
- 账户摘要与持仓：`IAlgorithm.Portfolio` + `IAlgorithm.Securities`。
- 行情快照：优先使用 `Securities[symbol].Price` 及 `SecurityCache`（last/bid/ask/volume）。
- 订单事件：`OrderEvent` 回调追加写入 `execution_events.jsonl`。

## 测试与验证
### Lean 侧单元测试
1) 输出文件写入（account/positions/quotes）。
2) 订单事件追加（execution_events.jsonl）。
3) 原子写入失败场景（旧文件不被破坏）。

### 集成验证
1) 启动 live paper 运行（TWS 已开）。
2) 触发 `trade_executor` 执行意图并启动 Lean。
3) 确认 `artifacts/lean_bridge` 生成文件。
4) `/api/ib/account/summary` 返回 `source=lean_bridge` 且 `stale=false`。
5) 实盘交易页面可见账户与持仓数据。

## 风险与对策
- **Lean 输出字段不足** → 需扩展 Lean 侧输出插件/脚本。
- **事件延迟** → 桥接状态显示延迟与滞后告警。
- **大频率文件写入** → 采用轮询间隔与增量 append。
