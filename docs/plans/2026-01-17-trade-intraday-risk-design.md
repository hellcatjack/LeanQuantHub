# 盘中风险管理（Phase 3.2）设计

## 目标
- 在**盘中**对账户损益、回撤与异常事件进行持续监控，触发阈值后进入**保护状态**（停止新交易、保留持仓）。
- 形成可审计、可追溯的风险事件记录，支持 UI 可视化与告警。
- 估值优先使用 **IB 实时/延时行情**，异常时自动降级到本地估值并标记来源。

## 非目标
- 不做强制清仓/对冲（本期采用 **动作 A：停止交易、保留持仓**）。
- 不引入期权/衍生品风控。

## 前提与假设
- IB API 可能暂不可用：估值需要支持 fallback。
- 交易执行由现有交易流程触发，风险护栏可在**下单前**与**定时巡检**两处生效。

---

## 方案概述
### 1) 风控状态机（Risk Guard State）
新增**盘中风险状态**，用于记录当日风控上下文与触发原因。建议新增表 `trade_guard_state`（或等价持久化结构）：
- `trade_date` / `project_id` / `mode`
- `status`: `active` | `halted`
- `halt_reason`: JSON/文本（多原因）
- `risk_triggers` / `order_failures` / `market_data_errors`
- `day_start_equity` / `equity_peak` / `last_equity`
- `last_valuation_ts` / `valuation_source`
- `cooldown_until`
- `created_at` / `updated_at`

**状态规则**：
- `active` → 触发任一阈值 → `halted`
- `halted` 后仅允许状态查看/重置（如手动解锁），默认不自动恢复

### 2) 估值来源（IB 优先 + 本地降级）
- **首选 IB**：实时/延时行情 + 账户净值（若可获取）。
- **降级本地**：使用最近可用价格快照（`data/ib/stream` 或本地 `prices`）估值。
- 引入 `valuation_stale_seconds`（如 120s）：若 IB 数据过旧则自动降级并记录 `valuation_source=local`。

### 3) 触发条件（阈值 C）
新增/扩展风控阈值配置（持久化到 `trade_settings.risk_defaults`）：
- `max_daily_loss`（日内亏损比例）
- `max_intraday_drawdown`（盘中回撤比例）
- `max_order_failures`（下单失败次数）
- `max_market_data_errors`（行情异常次数）
- `max_risk_triggers`（风控触发累积次数）
- `cooldown_seconds`（重复触发保护期）

触发逻辑：
- `daily_loss = (last_equity - day_start_equity) / day_start_equity`
- `drawdown = (last_equity - equity_peak) / equity_peak`
- 任意阈值超限 → `halted` + 记录原因

### 4) 行为策略（动作 A）
- 触发风控后：**禁止新下单**，现有持仓保留
- 不强制清仓、不切换防御资产
- UI 明确提示“已进入保护状态（停止交易）”

---

## 数据流与触发点
1) **下单前检查**：
- 订单生成前调用 `risk_guard.evaluate()`，若 `halted` 则阻断

2) **定时巡检**（如 30-60 秒）：
- 拉取估值 → 更新 `trade_guard_state` → 判断阈值
- 触发后通知 Telegram

3) **事件累积**：
- 下单失败/行情异常 → 累加计数，记录到 `trade_guard_state`

---

## UI/告警
- 在“实盘交易”面板展示：
  - 状态（active/halted）
  - 当前净值 / 日内回撤 / 日内亏损
  - 触发原因与时间
  - 估值来源（IB / local）
- Telegram：触发风控、行情异常、下单失败达到阈值

---

## 测试与验证
- 单元测试：
  - 日内亏损触发
  - 回撤触发
  - 事件计数触发
  - IB 数据过期 → 本地估值
- 集成测试：
  - 模拟行情异常/下单失败 → 风控触发
  - 风控触发后禁止下单

---

## 兼容与扩展
- 后续可扩展“动作 B/C”（回退模型/防御资产）
- 若 IB 恢复可用，可自动切换回 IB 估值
