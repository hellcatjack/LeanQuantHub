# 交易日历可靠来源 TODO

目标：为 PIT 周度快照与数据质量流程引入稳定、可追溯的交易日历来源，避免依赖 SPY 下一交易日数据才能生成最新快照。

## 当前问题
- 交易日历依赖 SPY 日线；要生成“上一个交易日收盘”的快照，必须等到下一交易日出现。
- 当 SPY 数据只更新到上一个交易日时，无法在周一上午生成上周五快照。
- 部分脚本各自读取 SPY 交易日，缺少统一来源与元数据。

## 可靠来源评估（候选）
1) 交易所官方节假日/早收盘日历（NYSE/Nasdaq）
   - 优点：官方发布，最权威。
   - 风险：通常是网页/文件公告，缺少标准 API，需要抓取或手工同步。
2) exchange_calendars / pandas_market_calendars（推荐）
   - 优点：离线可用、可生成未来交易日、覆盖 NYSE 假期/早收盘。
   - 风险：突发停市需人工覆盖（需要 overrides 机制）。
3) Lean MarketHoursDatabase（兼容 QC 体系）
   - 优点：与 QC 逻辑一致、包含市场时段与节假日。
   - 风险：需要同步其数据库文件，更新成本较高。
4) 本地维护的 CSV 交易日历
   - 优点：完全可控、易于审计与回滚。
   - 风险：需要定期更新，需引入校验逻辑。
5) SPY 交易日（现有 fallback）
   - 优点：零依赖。
   - 风险：无法提前生成最新快照。

> Alpha 评估：Alpha Vantage 未提供“官方交易日历”接口；只能从历史时间序列反推交易日，无法覆盖未来交易日与临时停市。

## 推荐方案（优先级）
- 优先级 1：本地交易日历文件（由 exchange_calendars 生成）+ overrides。
- 优先级 2：交易所官方日历年度校验（发现偏差时以 overrides 修正）。
- 优先级 3：Lean MarketHoursDatabase（可选，需明确来源）。
- 优先级 4：SPY 交易日兜底（仅在本地日历缺失时使用）。

## 数据与配置约定
- 目录：`DATA_ROOT/universe/trading_calendar/`
  - `nyse_trading_calendar.csv`：交易日列表（date, session, is_trading_day, is_early_close）。
  - `trading_calendar_overrides.csv`：临时停市/特殊交易日覆盖（date, override_type, note）。
  - `calendar_meta.json`：来源、覆盖范围、更新时间。
- 配置：`DATA_ROOT/config/trading_calendar.json`
  - `source`: `local|exchange_calendars|lean|spy|auto`
  - `exchange`: `XNYS`
  - `start_date` / `end_date`
  - `refresh_days`
  - `override_enabled`

## TODO 列表
### Phase 0 — 设计与约定
- [ ] 定义 TradingCalendarProvider 接口（source/coverage/metadata）。
- [ ] 明确“交易日历优先级”与 fallback 策略。
- [ ] 设计 overrides 机制（覆盖临时停市）。

### Phase 1 — 数据生成与更新脚本
- [ ] 新增 `scripts/build_trading_calendar.py`：使用 exchange_calendars 生成交易日历。
- [ ] 支持增量更新（基于 refresh_days 或 end_date）。
- [ ] 写入 `calendar_meta.json` 并记录来源与覆盖范围。

### Phase 2 — 统一交易日历读取
- [ ] 新增 `app/services/trading_calendar.py` 或 `scripts/trading_calendar.py`。
- [ ] 统一 `_load_trading_days` 调用，支持 `source=auto`。
- [ ] 适配文件：
  - `scripts/build_pit_weekly_snapshots.py`
  - `scripts/build_pit_fundamentals_snapshots.py`
  - `scripts/validate_pit_weekly_snapshots.py`
  - `scripts/scan_price_quality.py`
  - `backend/app/routes/datasets.py`

### Phase 3 — PIT 周度快照生成规则优化
- [ ] 当 calendar_end > spy_last_date 时，允许“生成最新周快照”。
- [ ] 增加元数据：`calendar_source` / `calendar_end` / `spy_last_date`。
- [ ] 校验规则：snapshot_date 必须 <= 最新价格覆盖日，否则标记为 `pending`。

### Phase 4 — UI 与运维
- [ ] 数据页显示交易日历来源与覆盖范围（只读）。
- [ ] 提供“刷新交易日历”按钮（写入 meta + 日志）。
- [ ] UI 提示：若 calendar_end 超过价格覆盖日，快照生成仍会受限。

### Phase 5 — 验收与回归
- [ ] 生成交易日历后，能在周一上午生成上周五快照（无 SPY 下一交易日）。
- [ ] `validate_pit_weekly_snapshots` 使用统一交易日历对齐。
- [ ] 失败场景：无日历 / 日历损坏 → fallback 到 SPY，且日志明确。

## 验收标准
- 周度快照不再依赖“下一交易日价格更新”。
- 交易日历来源可追溯、可更新、可回退。
- PIT 周度快照与 PIT 基本面快照日期一致。
