# Alpha Vantage 数据源

## 基本信息
- 官网文档：`https://www.alphavantage.co/documentation/`
- API 基础地址：`https://www.alphavantage.co/query`
- 认证方式：API Key（环境变量 `ALPHA_VANTAGE_API_KEY`）
- 适用场景：历史数据 + 基本面 + 事件/新闻；不适合作为超低延迟实盘行情源

## 覆盖能力（按用途分类）
- 行情/价格
  - `TIME_SERIES_INTRADAY`, `TIME_SERIES_DAILY`, `TIME_SERIES_DAILY_ADJUSTED`
  - `TIME_SERIES_WEEKLY`, `TIME_SERIES_WEEKLY_ADJUSTED`
  - `TIME_SERIES_MONTHLY`, `TIME_SERIES_MONTHLY_ADJUSTED`
  - `GLOBAL_QUOTE`, `REALTIME_BULK_QUOTES`
- 基本面/公司财报
  - `OVERVIEW`, `EARNINGS`
  - `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`
  - `DIVIDENDS`, `SPLITS`, `SHARES_OUTSTANDING`, `ETF_PROFILE`
- 事件/日历/新闻
  - `EARNINGS_CALENDAR`, `IPO_CALENDAR`
  - `INSIDER_TRANSACTIONS`, `EARNINGS_CALL_TRANSCRIPT`
  - `NEWS_SENTIMENT`
- 期权
  - `HISTORICAL_OPTIONS`, `REALTIME_OPTIONS`
- 外汇/加密/宏观/大宗商品
  - `FX_*`, `DIGITAL_CURRENCY_*`, `CRYPTO_INTRADAY`
  - `TREASURY_YIELD`, `CPI`, `INFLATION`, `UNEMPLOYMENT`, `FEDERAL_FUNDS_RATE`
  - `WTI`, `BRENT`, `NATURAL_GAS`, `COPPER`, `CORN` 等
- 技术指标
  - `SMA`, `EMA`, `RSI`, `MACD`, `BBANDS`, `ADX`, `STOCH` 等

## 本项目落地映射
- Listing / 生命周期
  - 接口：`LISTING_STATUS`
  - 输出：`data/universe/alpha_symbol_life.csv`
- 基本面原始缓存
  - 接口：`OVERVIEW`, `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`, `EARNINGS`, `SHARES_OUTSTANDING`
  - 输出：`data/fundamentals/alpha/<SYMBOL>/*.json`
- PIT 周度快照
  - 输入：`data/universe/pit_weekly/*.csv`
  - 输出：`data/factors/pit_weekly_fundamentals/*.csv`

## Alpha-only 配置约束
- 项目配置保存时强制写入 `data.primary_vendor=alpha`，`fallback_vendor` 为空。
- 前端配置页仅显示 Alpha（只读），避免误用 Stooq/Yahoo。
- 任何训练/回测默认以 Alpha 为唯一数据源。

## 限速与重试
- 限速提示常见字段：`Note` / `Information` / `Error Message`
- 本项目规则：出现限速提示视为可重试，按 `rate_limit_sleep` 与 `rate_limit_retries` 控制
- 建议：批量抓取时保持 `min_delay_seconds` ≥ 0.8（或按订阅权限调优）

## 已验证可用接口（使用本机 `.env` Key 实测）
- `GLOBAL_QUOTE`
- `TIME_SERIES_DAILY_ADJUSTED`
- `TIME_SERIES_INTRADAY`
- `OVERVIEW`
- `EARNINGS`
- `INCOME_STATEMENT`
- `BALANCE_SHEET`
- `CASH_FLOW`

## 备注
- 若未来接入更多数据源，保持同一结构：`docs/data_sources/<vendor>.md`
- 避免在文档中写入任何真实密钥或账号信息
