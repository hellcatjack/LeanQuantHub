# Trade Guard 盘中峰值异常过滤设计

## 背景

`trade_runs.id=1155` 与 `1156` 都在执行前被 `guard_halted` 拦截。排查确认：

- 阻断原因是 `max_intraday_drawdown`
- `trade_guard_state` 在 `2026-03-16` 的 `equity_peak` 被抬到 `443184.0`
- 实际账户权益仍在 `2.9 万` 附近
- `dd_all` / `dd_52w` 有峰值异常过滤，但 `intraday_drawdown` 直接使用 `state.equity_peak`

因此，当前系统会被异常盘中峰值污染，导致后续同日批次持续误 block。

## 目标

- 防止异常 `equity_peak` 触发假的 `max_intraday_drawdown`
- 一旦识别到异常盘中峰值，自动把污染状态回写修正
- 如果当前 halt 仅由异常峰值造成，自动恢复 `active`
- 不削弱真实盘中回撤风控

## 非目标

- 不修改 `dd_all` / `dd_52w` 现有逻辑
- 不改变其他 risk trigger 的阈值与优先级
- 不改前端页面，仅修复后端 guard 逻辑

## 方案

### 1. 增加盘中峰值清洗

在 `trade_guard.py` 中引入盘中峰值标准化逻辑：

- 原始值：`intraday_peak_raw = state.equity_peak`
- 锚点：`max(day_start_equity, peak_52w, adjusted_equity)`
- 上限：`anchor * peak_all_outlier_ratio`
- 若 `intraday_peak_raw` 超过上限，则使用清洗后的 `intraday_peak_sanitized`

`intraday_drawdown` 改为基于 `intraday_peak_sanitized` 计算。

### 2. 自动回写污染状态

若判定 `state.equity_peak` 为异常值：

- 直接把 `state.equity_peak` 回写为清洗后的值
- 在 metrics 中追加：
  - `intraday_peak_raw`
  - `intraday_peak_sanitized`
  - `intraday_peak_outlier_filtered`

### 3. 自动解锁

若满足以下条件：

- 当前 halt 原因只有 `max_intraday_drawdown`
- 清洗峰值后重新计算，已不再触发任何风险原因

则本次评估直接恢复 `state.status = active`，清空 `cooldown_until`，并写入 unlock 原因。

## 测试要求

- 异常盘中峰值不会触发误判的 `max_intraday_drawdown`
- 清洗后会把 `state.equity_peak` 修正写回
- 仅由异常盘中峰值造成的 halt 会自动解锁
- 合理盘中峰值下的真实回撤仍会正常 block

## 风险

- 若合法的盘中权益跳升超过 outlier ratio，可能被压制
- 当前默认复用 `peak_all_outlier_ratio`，若后续发现盘中与历史需要不同阈值，再拆分独立参数
