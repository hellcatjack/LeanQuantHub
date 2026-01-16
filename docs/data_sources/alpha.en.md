# Alpha Vantage Data Source (English Companion)

> This is the English companion of `docs/data_sources/alpha.md`.

## Basics
- Docs: https://www.alphavantage.co/documentation/
- Base URL: https://www.alphavantage.co/query
- Auth: API Key via `ALPHA_VANTAGE_API_KEY`
- Use cases: historical prices + fundamentals + events/news; not suitable for ultra-low-latency live trading

## Coverage (by category)
- Prices
  - `TIME_SERIES_INTRADAY`, `TIME_SERIES_DAILY`, `TIME_SERIES_DAILY_ADJUSTED`
  - `TIME_SERIES_WEEKLY`, `TIME_SERIES_WEEKLY_ADJUSTED`
  - `TIME_SERIES_MONTHLY`, `TIME_SERIES_MONTHLY_ADJUSTED`
  - `GLOBAL_QUOTE`, `REALTIME_BULK_QUOTES`
- Fundamentals
  - `OVERVIEW`, `EARNINGS`
  - `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`
  - `DIVIDENDS`, `SPLITS`, `SHARES_OUTSTANDING`, `ETF_PROFILE`
- Events / Calendar / News
  - `EARNINGS_CALENDAR`, `IPO_CALENDAR`
  - `INSIDER_TRANSACTIONS`, `EARNINGS_CALL_TRANSCRIPT`
  - `NEWS_SENTIMENT`
- Options
  - `HISTORICAL_OPTIONS`, `REALTIME_OPTIONS`
- FX / Crypto / Macro / Commodities
  - `FX_*`, `DIGITAL_CURRENCY_*`, `CRYPTO_INTRADAY`
  - `TREASURY_YIELD`, `CPI`, `INFLATION`, `UNEMPLOYMENT`, `FEDERAL_FUNDS_RATE`
  - `WTI`, `BRENT`, `NATURAL_GAS`, `COPPER`, `CORN`, etc.
- Technical Indicators
  - `SMA`, `EMA`, `RSI`, `MACD`, `BBANDS`, `ADX`, `STOCH`, etc.

## Project Mapping
- Listing / lifecycle
  - API: `LISTING_STATUS`
  - Output: `data/universe/alpha_symbol_life.csv`
- Fundamentals raw cache
  - APIs: `OVERVIEW`, `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`, `EARNINGS`, `SHARES_OUTSTANDING`
  - Output: `data/fundamentals/alpha/<SYMBOL>/*.json`
- PIT weekly snapshots
  - Input: `data/universe/pit_weekly/*.csv`
  - Output: `data/factors/pit_weekly_fundamentals/*.csv`

## Alpha-only Constraints
- Config enforces `data.primary_vendor=alpha` and empty `fallback_vendor`
- UI only shows Alpha (read-only) to prevent Stooq/Yahoo usage
- Training/backtests use Alpha as the single data source

## Rate Limits & Retry
- Common rate-limit fields: `Note` / `Information` / `Error Message`
- Rule: rate-limit responses are retryable, controlled by `rate_limit_sleep` and `rate_limit_retries`
- Recommendation: keep `min_delay_seconds` ≥ 0.8 for batch jobs (or tune by subscription)

## Verified APIs (with local .env key)
- `GLOBAL_QUOTE`
- `TIME_SERIES_DAILY_ADJUSTED`
- `TIME_SERIES_INTRADAY`
- `OVERVIEW`
- `EARNINGS`
- `INCOME_STATEMENT`
- `BALANCE_SHEET`
- `CASH_FLOW`

## Notes
- Add new vendor docs under `docs/data_sources/<vendor>.md`
- Never include real credentials in docs
