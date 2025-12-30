from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


DEFAULT_SP500_URL = (
    "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
)
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'").strip('"')
        env[key.strip()] = value
    return env


def get_data_root() -> Path:
    env_path = Path(__file__).resolve().parents[1] / "backend" / ".env"
    env = load_env(env_path)
    data_root = env.get("DATA_ROOT")
    if data_root:
        return Path(data_root).resolve()
    return Path("C:/work/stocks/data").resolve()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def append_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    write_header = not path.exists()
    encoding = "utf-8-sig" if write_header else "utf-8"
    with path.open("a", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def download_csv(url: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(content.splitlines())
    return [dict(row) for row in reader]


def download_sp500_current() -> list[dict[str, str]]:
    rows = download_csv(DEFAULT_SP500_URL)
    items: list[dict[str, str]] = []
    for row in rows:
        symbol = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        items.append(
            {
                "symbol": symbol,
                "name": (row.get("Name") or row.get("name") or "").strip(),
                "sector": (row.get("Sector") or row.get("sector") or "").strip(),
                "source": "datahub",
            }
        )
    return items


def _fetch_wiki_html() -> str:
    try:
        import requests

        resp = requests.get(
            WIKI_SP500_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text
    except Exception:
        request = urllib.request.Request(
            WIKI_SP500_URL, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")


def _clean_symbol(value: str) -> str:
    text = (value or "").strip().upper()
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"[^A-Z0-9\\.]", "", text)
    return text


def _split_symbols(value: str) -> list[str]:
    if not value or str(value).strip() in {"", "-"}:
        return []
    text = str(value)
    text = re.sub(r"\[[^\]]+\]", "", text)
    parts = re.split(r"[;,/]|\\s+and\\s+", text)
    symbols = [_clean_symbol(part) for part in parts]
    return [symbol for symbol in symbols if symbol]


def _flatten_columns(columns) -> list[str]:
    flattened: list[str] = []
    for col in columns:
        if isinstance(col, tuple):
            flattened.append(" ".join(str(value) for value in col if value))
        else:
            flattened.append(str(col))
    return flattened


def build_membership_from_wiki(data_root: Path) -> list[dict[str, str]]:
    import pandas as pd
    from io import StringIO

    html = _fetch_wiki_html()
    frames = pd.read_html(StringIO(html))
    if not frames:
        raise RuntimeError("未能解析维基页面的成分表")

    current = frames[0]
    current_symbols = {
        _clean_symbol(value) for value in current["Symbol"].tolist()
    }
    current_symbols = {symbol for symbol in current_symbols if symbol}
    date_added_map: dict[str, date] = {}
    if "Date added" in current.columns:
        for _, row in current.iterrows():
            symbol = _clean_symbol(row.get("Symbol", ""))
            if not symbol:
                continue
            added_text = str(row.get("Date added", "")).strip()
            added_text = re.sub(r"\[[^\]]+\]", "", added_text).strip()
            if not added_text:
                continue
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
                try:
                    date_added_map[symbol] = datetime.strptime(
                        added_text, fmt
                    ).date()
                    break
                except ValueError:
                    continue

    changes_df = None
    for frame in frames[1:]:
        cols = _flatten_columns(frame.columns)
        lowered = [col.lower() for col in cols]
        has_effective = any("effective date" in col for col in lowered)
        has_added = any("added" in col for col in lowered)
        if has_effective and has_added:
            frame.columns = cols
            changes_df = frame
            break
    if changes_df is None:
        raise RuntimeError("未找到维基成分变更表")

    changes_df = changes_df.rename(
        columns={
            "Effective Date Effective Date": "Effective Date",
            "Added Ticker": "Added Ticker",
            "Removed Ticker": "Removed Ticker",
        }
    )

    def parse_effective(value: str) -> date | None:
        text = str(value)
        text = re.sub(r"\[[^\]]+\]", "", text).strip()
        if not text:
            return None
        for fmt in ("%B %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.strptime(text, "%b %d, %Y").date()
        except ValueError:
            return None

    changes = []
    for _, row in changes_df.iterrows():
        effective = parse_effective(row.get("Effective Date", ""))
        added = _split_symbols(row.get("Added Ticker", ""))
        removed = _split_symbols(row.get("Removed Ticker", ""))
        if not effective or (not added and not removed):
            continue
        changes.append((effective, added, removed))

    changes.sort(key=lambda item: item[0], reverse=True)
    if not changes:
        raise RuntimeError("维基成分变更表为空")
    earliest_date = changes[-1][0]
    if date_added_map:
        earliest_date = min(earliest_date, min(date_added_map.values()))

    intervals: dict[str, list[dict[str, date | None | str]]] = {}
    active = set(current_symbols)
    for symbol in current_symbols:
        intervals[symbol] = [
            {"start_date": None, "end_date": None, "source": ""}
        ]

    def choose_interval(symbol: str) -> dict[str, date | None | str]:
        items = intervals.setdefault(symbol, [])
        open_items = [item for item in items if item["start_date"] is None]
        if not open_items:
            new_item = {"start_date": None, "end_date": None, "source": ""}
            items.append(new_item)
            return new_item
        no_end = [item for item in open_items if item["end_date"] is None]
        if no_end:
            return no_end[0]
        return sorted(
            open_items,
            key=lambda item: item["end_date"] or date.min,
            reverse=True,
        )[0]

    for effective, added, removed in changes:
        for symbol in added:
            interval = choose_interval(symbol)
            if interval["start_date"] is None:
                interval["start_date"] = effective
                interval["source"] = "wikipedia_change"
            if symbol in active:
                active.remove(symbol)
        for symbol in removed:
            if symbol not in active:
                active.add(symbol)
            intervals.setdefault(symbol, []).append(
                {"start_date": None, "end_date": effective, "source": ""}
            )

    for symbol, added_date in date_added_map.items():
        items = intervals.get(symbol)
        if not items:
            continue
        for interval in items:
            if interval["end_date"] is None and interval["start_date"] is None:
                interval["start_date"] = added_date
                interval["source"] = "wikipedia_date_added"
                break

    rows: list[dict[str, str]] = []
    for symbol, items in intervals.items():
        for interval in items:
            start_date = interval["start_date"] or earliest_date
            source = (
                interval.get("source")
                or ("wikipedia_estimated" if interval["start_date"] is None else "wikipedia")
            )
            rows.append(
                {
                    "symbol": symbol,
                    "start_date": start_date.isoformat() if start_date else "",
                    "end_date": interval["end_date"].isoformat()
                    if interval["end_date"]
                    else "",
                    "source": source,
                }
            )
    membership_path = data_root / "universe" / "sp500_membership.csv"
    write_csv(membership_path, rows, ["symbol", "start_date", "end_date", "source"])
    return rows


def load_sp500_membership(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path)
    normalized: list[dict[str, str]] = []
    for row in rows:
        symbol = (row.get("symbol") or row.get("Symbol") or "").strip().upper()
        if not symbol:
            continue
        normalized.append(
            {
                "symbol": symbol,
                "start_date": (row.get("start_date") or row.get("start") or "").strip(),
                "end_date": (row.get("end_date") or row.get("end") or "").strip(),
                "source": (row.get("source") or "custom").strip() or "custom",
            }
        )
    return normalized


def build_membership(data_root: Path, history_path: Path | None) -> list[dict[str, str]]:
    if history_path and history_path.exists():
        return load_sp500_membership(history_path)
    try:
        return build_membership_from_wiki(data_root)
    except Exception:
        current = download_sp500_current()
        rows = [
            {
                "symbol": item["symbol"],
                "start_date": "",
                "end_date": "",
                "source": item["source"],
            }
            for item in current
        ]
        membership_path = data_root / "universe" / "sp500_membership.csv"
        write_csv(membership_path, rows, ["symbol", "start_date", "end_date", "source"])
        return rows


def load_theme_config(path: Path) -> dict:
    if not path.exists():
        return {"categories": [], "defaults": {}, "yahoo": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def load_benchmark_symbols(base_dir: Path, config_path: Path | None = None) -> list[str]:
    if config_path is None:
        env_path = os.environ.get("WEIGHTS_CONFIG_PATH")
        config_path = Path(env_path) if env_path else base_dir / "configs" / "portfolio_weights.json"
    if not config_path.exists():
        return []
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    benchmark = payload.get("benchmark")
    if isinstance(benchmark, list):
        return [str(item).strip().upper() for item in benchmark if str(item).strip()]
    if isinstance(benchmark, str) and benchmark.strip():
        return [benchmark.strip().upper()]
    return []


def yahoo_search(keyword: str, count: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": keyword, "quotesCount": count, "newsCount": 0}
    )
    url = f"{YAHOO_SEARCH_URL}?{params}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    return payload.get("quotes", [])


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def infer_region(symbol: str, default: str) -> str:
    symbol = symbol.upper()
    if symbol.endswith(".HK"):
        return "HK"
    return default


def build_theme_candidates(config: dict) -> list[dict[str, str]]:
    categories = config.get("categories", [])
    yahoo_cfg = config.get("yahoo", {})
    allow_exchanges = set(yahoo_cfg.get("allowExchanges") or [])
    count = int(yahoo_cfg.get("quotesCount") or 25)
    pause = float(yahoo_cfg.get("pauseSeconds") or 0)
    default_region = config.get("defaults", {}).get("region", "US")
    default_asset = config.get("defaults", {}).get("asset_class", "Equity")
    seen: dict[str, dict[str, str]] = {}

    for category in categories:
        key = category.get("key", "").strip()
        label = category.get("label", key)
        if not key:
            continue
        for manual in category.get("manual", []) or []:
            symbol = normalize_symbol(manual)
            if not symbol:
                continue
            seen.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "category": key,
                    "category_label": label,
                    "source": "manual",
                    "keyword": "manual",
                    "region": infer_region(symbol, default_region),
                    "asset_class": default_asset,
                },
            )
        for keyword in category.get("keywords", []) or []:
            try:
                quotes = yahoo_search(keyword, count)
            except Exception:
                continue
            for quote in quotes:
                quote_type = (quote.get("quoteType") or "").upper()
                exchange = (quote.get("exchange") or "").upper()
                if quote_type not in {"EQUITY", "ETF"}:
                    continue
                if allow_exchanges and exchange and exchange not in allow_exchanges:
                    continue
                symbol = normalize_symbol(quote.get("symbol") or "")
                if not symbol or symbol in seen:
                    continue
                seen[symbol] = {
                    "symbol": symbol,
                    "category": key,
                    "category_label": label,
                    "source": "yahoo",
                    "keyword": keyword,
                    "region": infer_region(symbol, default_region),
                    "asset_class": default_asset,
                }
            if pause:
                time.sleep(pause)
    return list(seen.values())


def build_universe(
    data_root: Path, config_path: Path, history_path: Path | None
) -> Path:
    membership = build_membership(data_root, history_path)
    theme_cfg = load_theme_config(config_path)
    themes = build_theme_candidates(theme_cfg)
    theme_by_symbol = {item["symbol"]: item for item in themes}

    rows: list[dict[str, str]] = []
    membership_info: dict[str, dict[str, str]] = {}
    for entry in membership:
        symbol = entry["symbol"]
        theme = theme_by_symbol.get(symbol)
        info = membership_info.setdefault(
            symbol, {"start_date": "", "end_date": "", "source": entry.get("source", "sp500")}
        )
        start_date = entry.get("start_date", "") or ""
        end_date = entry.get("end_date", "") or ""
        if start_date and (not info["start_date"] or start_date < info["start_date"]):
            info["start_date"] = start_date
        if not info["end_date"]:
            if end_date:
                info["end_date"] = end_date
        else:
            if end_date and end_date > info["end_date"]:
                info["end_date"] = end_date

    membership_symbols = set(membership_info.keys())
    for symbol, info in membership_info.items():
        theme = theme_by_symbol.get(symbol)
        if theme:
            category = theme["category"]
            label = theme["category_label"]
        else:
            category = "SP500_OTHER"
            label = "S&P500其他"
        rows.append(
            {
                "symbol": symbol,
                "category": category,
                "category_label": label,
                "region": theme["region"] if theme else "US",
                "asset_class": theme["asset_class"] if theme else "Equity",
                "in_sp500_history": "1",
                "start_date": info["start_date"],
                "end_date": info["end_date"],
                "source": info["source"],
                "theme_source": theme.get("source", "") if theme else "",
                "theme_keyword": theme.get("keyword", "") if theme else "",
            }
        )

    for theme in themes:
        symbol = theme["symbol"]
        if symbol in membership_symbols:
            continue
        rows.append(
            {
                "symbol": symbol,
                "category": theme["category"],
                "category_label": theme["category_label"],
                "region": theme["region"],
                "asset_class": theme["asset_class"],
                "in_sp500_history": "0",
                "start_date": "",
                "end_date": "",
                "source": "theme_only",
                "theme_source": theme["source"],
                "theme_keyword": theme["keyword"],
            }
        )

    universe_path = data_root / "universe" / "universe.csv"
    write_csv(
        universe_path,
        rows,
        [
            "symbol",
            "category",
            "category_label",
            "region",
            "asset_class",
            "in_sp500_history",
            "start_date",
            "end_date",
            "source",
            "theme_source",
            "theme_keyword",
        ],
    )

    theme_path = data_root / "universe" / "themes.csv"
    write_csv(
        theme_path,
        themes,
        [
            "symbol",
            "category",
            "category_label",
            "source",
            "keyword",
            "region",
            "asset_class",
        ],
    )
    return universe_path


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(values), size):
        yield values[idx : idx + size]


def to_yahoo_symbol(symbol: str, region: str) -> str:
    symbol = symbol.upper()
    if region == "HK" and not symbol.endswith(".HK"):
        return f"{symbol}.HK"
    return symbol


def fetch_yahoo_quotes(symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    params = urllib.parse.urlencode({"symbols": ",".join(symbols)})
    url = f"{YAHOO_QUOTE_URL}?{params}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    return payload.get("quoteResponse", {}).get("result", [])


def fetch_metrics(data_root: Path, universe_path: Path, limit: int | None) -> Path:
    import yfinance as yf

    rows = read_csv(universe_path)
    metrics_path = data_root / "metrics" / "yahoo_quotes.csv"
    existing = read_csv(metrics_path)
    processed = {row.get("symbol", "").strip().upper() for row in existing}
    missing: list[str] = []
    fieldnames = [
        "symbol",
        "yahoo_symbol",
        "short_name",
        "long_name",
        "exchange",
        "quote_type",
        "currency",
        "sector",
        "industry",
        "market_cap",
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "beta",
        "fifty_two_week_high",
        "fifty_two_week_low",
        "average_volume",
        "average_volume_10d",
        "regular_market_price",
        "regular_market_change_pct",
    ]
    appended = 0
    for row in rows:
        symbol = row.get("symbol", "").strip().upper()
        region = row.get("region", "US").strip().upper()
        if not symbol:
            continue
        if symbol in processed:
            continue
        yahoo_symbol = to_yahoo_symbol(symbol, region)
        try:
            info = yf.Ticker(yahoo_symbol).info
        except Exception:
            missing.append(yahoo_symbol)
            continue
        if not info:
            missing.append(yahoo_symbol)
            continue
        row_out = {
            "symbol": symbol,
            "yahoo_symbol": yahoo_symbol,
            "short_name": str(info.get("shortName") or ""),
            "long_name": str(info.get("longName") or ""),
            "exchange": str(info.get("exchange") or ""),
            "quote_type": str(info.get("quoteType") or ""),
            "currency": str(info.get("currency") or ""),
            "sector": str(info.get("sector") or ""),
            "industry": str(info.get("industry") or ""),
            "market_cap": str(info.get("marketCap") or ""),
            "trailing_pe": str(info.get("trailingPE") or ""),
            "forward_pe": str(info.get("forwardPE") or ""),
            "price_to_book": str(info.get("priceToBook") or ""),
            "beta": str(info.get("beta") or ""),
            "fifty_two_week_high": str(info.get("fiftyTwoWeekHigh") or ""),
            "fifty_two_week_low": str(info.get("fiftyTwoWeekLow") or ""),
            "average_volume": str(info.get("averageVolume") or ""),
            "average_volume_10d": str(info.get("averageDailyVolume10Day") or ""),
            "regular_market_price": str(info.get("regularMarketPrice") or ""),
            "regular_market_change_pct": str(
                info.get("regularMarketChangePercent") or ""
            ),
        }
        append_csv(metrics_path, [row_out], fieldnames)
        appended += 1
        time.sleep(0.2)
        if limit and appended >= limit:
            break

    if missing:
        missing_path = data_root / "metrics" / "yahoo_missing.csv"
        write_csv(missing_path, [{"symbol": s} for s in missing], ["symbol"])
    return metrics_path


def to_stooq_symbol(symbol: str, region: str) -> str:
    symbol = symbol.strip().lower()
    if region == "HK" and not symbol.endswith(".hk"):
        return f"{symbol}.hk"
    if region != "HK" and not symbol.endswith(".us"):
        return f"{symbol}.us"
    return symbol


def fetch_stooq_history(symbol: str, region: str, target: Path) -> bool:
    stooq_symbol = to_stooq_symbol(symbol, region)
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                return False
            data = response.read()
    except Exception:
        return False
    if not data or b"Date" not in data:
        return False
    ensure_dir(target.parent)
    target.write_bytes(data)
    return True


def fetch_yahoo_history(symbol: str, region: str, target: Path) -> bool:
    import yfinance as yf

    yahoo_symbol = to_yahoo_symbol(symbol, region)
    try:
        df = yf.Ticker(yahoo_symbol).history(period="max", auto_adjust=False)
    except Exception:
        return False
    if df is None or df.empty:
        return False
    df = df.reset_index()
    if "Date" not in df.columns or "Close" not in df.columns:
        return False
    ensure_dir(target.parent)
    df.to_csv(target, index=False, encoding="utf-8")
    return True


def fetch_prices(
    data_root: Path, universe_path: Path, overwrite: bool, limit: int | None
) -> Path:
    rows = read_csv(universe_path)
    base_dir = Path(__file__).resolve().parents[1]
    benchmark_symbols = set(load_benchmark_symbols(base_dir))
    seen_symbols = set()
    fetch_list: list[tuple[str, str]] = []
    for symbol in sorted(benchmark_symbols):
        if not symbol:
            continue
        fetch_list.append((symbol, "US"))
        seen_symbols.add(symbol)
    for row in rows:
        symbol = row.get("symbol", "").strip().upper()
        region = row.get("region", "US").strip().upper()
        if not symbol:
            continue
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        fetch_list.append((symbol, region))
    stooq_dir = data_root / "prices" / "stooq"
    yahoo_dir = data_root / "prices" / "yahoo"
    ensure_dir(stooq_dir)
    ensure_dir(yahoo_dir)
    results: list[dict[str, str]] = []
    processed = 0
    for symbol, region in fetch_list:
        stooq_target = stooq_dir / f"{symbol}.csv"
        yahoo_target = yahoo_dir / f"{symbol}.csv"
        if (stooq_target.exists() or yahoo_target.exists()) and not overwrite:
            results.append({"symbol": symbol, "status": "cached", "vendor": "cached"})
            continue
        ok = fetch_stooq_history(symbol, region, stooq_target)
        if ok:
            results.append({"symbol": symbol, "status": "ok", "vendor": "stooq"})
        else:
            ok = fetch_yahoo_history(symbol, region, yahoo_target)
            results.append(
                {
                    "symbol": symbol,
                    "status": "ok" if ok else "failed",
                    "vendor": "yahoo" if ok else "none",
                }
            )
        time.sleep(0.2)
        processed += 1
        if limit and processed >= limit:
            break
    status_path = data_root / "prices" / "price_fetch_status.csv"
    write_csv(status_path, results, ["symbol", "status", "vendor"])
    return status_path


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def load_membership_ranges(rows: list[dict[str, str]]) -> dict[str, list[tuple[date | None, date | None]]]:
    ranges: dict[str, list[tuple[date | None, date | None]]] = {}
    for row in rows:
        symbol = row.get("symbol", "").strip().upper()
        if not symbol:
            continue
        start = parse_date(row.get("start_date", ""))
        end = parse_date(row.get("end_date", ""))
        ranges.setdefault(symbol, []).append((start, end))
    return ranges


def active_in_ranges(ranges: list[tuple[date | None, date | None]], check: date) -> bool:
    for start, end in ranges:
        if start and check < start:
            continue
        if end and check > end:
            continue
        return True
    return False


def calc_metrics(series, risk_free: float) -> dict[str, float]:
    if series.empty:
        return {}
    start = series.index[0]
    end = series.index[-1]
    years = (end - start).days / 365.25
    total = series.iloc[-1]
    cagr = total ** (1 / years) - 1 if years > 0 else 0.0
    daily = series.pct_change().dropna()
    vol = daily.std() * math.sqrt(252)
    sharpe = 0.0
    if vol and not math.isnan(vol):
        sharpe = (daily.mean() * 252 - risk_free) / vol
    drawdown = (series / series.cummax() - 1).min()
    return {
        "cagr": float(cagr),
        "volatility": float(vol),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown),
    }


def run_backtest(data_root: Path, universe_path: Path, config_path: Path) -> Path:
    import pandas as pd

    weights_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    benchmark = weights_cfg.get("benchmark", "SPY")
    category_weights: dict[str, float] = weights_cfg.get("category_weights", {})
    risk_free = float(weights_cfg.get("risk_free_rate", 0.0))

    universe = read_csv(universe_path)
    membership_rows = read_csv(data_root / "universe" / "sp500_membership.csv")
    membership_ranges = load_membership_ranges(membership_rows)
    category_by_symbol = {
        row.get("symbol", "").strip().upper(): row.get("category", "")
        for row in universe
    }
    stooq_dir = data_root / "prices" / "stooq"
    yahoo_dir = data_root / "prices" / "yahoo"

    frames = []
    for row in universe:
        symbol = row.get("symbol", "").strip().upper()
        if not symbol:
            continue
        path = stooq_dir / f"{symbol}.csv"
        if not path.exists():
            alt_path = yahoo_dir / f"{symbol}.csv"
            if alt_path.exists():
                path = alt_path
            else:
                continue
        df = pd.read_csv(path)
        if "Date" not in df.columns or "Close" not in df.columns:
            continue
        df = df[["Date", "Close"]].rename(columns={"Date": "date", "Close": symbol})
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None)
        frames.append(df.set_index("date"))

    if not frames:
        raise SystemExit("未找到可用的价格数据")

    prices = pd.concat(frames, axis=1).sort_index()
    prices = prices.dropna(how="all")
    returns = prices.pct_change(fill_method=None).fillna(0.0)

    raw_rebalance = prices.resample("ME").last().index
    rebalance_dates = []
    for ts in raw_rebalance:
        idx = prices.index.get_indexer([ts], method="pad")
        if idx.size and idx[0] >= 0:
            rebalance_dates.append(prices.index[idx[0]])
    rebalance_dates = sorted(set(rebalance_dates))
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    for idx, rebalance in enumerate(rebalance_dates):
        check_date = rebalance.date()
        active_symbols = []
        for symbol in prices.columns:
            ranges = membership_ranges.get(symbol)
            if ranges and not active_in_ranges(ranges, check_date):
                continue
            if math.isnan(prices.at[rebalance, symbol]):
                continue
            active_symbols.append(symbol)
        if not active_symbols:
            continue
        symbols_by_category: dict[str, list[str]] = {}
        for symbol in active_symbols:
            category = category_by_symbol.get(symbol, "SP500_OTHER") or "SP500_OTHER"
            symbols_by_category.setdefault(category, []).append(symbol)
        available_categories = {
            key: value for key, value in symbols_by_category.items() if value
        }
        raw_weight_sum = sum(
            category_weights.get(key, 0.0) for key in available_categories
        )
        if raw_weight_sum <= 0:
            continue
        normalized_weights = {
            key: category_weights.get(key, 0.0) / raw_weight_sum
            for key in available_categories
        }
        weight_row = {symbol: 0.0 for symbol in prices.columns}
        for category, symbols in available_categories.items():
            if not symbols:
                continue
            share = normalized_weights.get(category, 0.0) / len(symbols)
            for symbol in symbols:
                weight_row[symbol] = share
        start_idx = prices.index.get_loc(rebalance)
        end_idx = (
            prices.index.get_loc(rebalance_dates[idx + 1])
            if idx + 1 < len(rebalance_dates)
            else len(prices.index)
        )
        weights.iloc[start_idx:end_idx] = pd.Series(weight_row)

    portfolio_returns = (weights.shift(1) * returns).sum(axis=1)
    portfolio_equity = (1 + portfolio_returns).cumprod()

    benchmark_path = stooq_dir / f"{benchmark.upper()}.csv"
    if not benchmark_path.exists():
        alt_path = yahoo_dir / f"{benchmark.upper()}.csv"
        if alt_path.exists():
            benchmark_path = alt_path
    if benchmark.upper() not in prices.columns and benchmark_path.exists():
        bench_df = pd.read_csv(benchmark_path)
        if "Date" in bench_df.columns and "Close" in bench_df.columns:
            bench_df = bench_df[["Date", "Close"]].rename(
                columns={"Date": "date", "Close": benchmark.upper()}
            )
            bench_df["date"] = pd.to_datetime(bench_df["date"], utc=True).dt.tz_convert(None)
            bench_series = bench_df.set_index("date")[benchmark.upper()].sort_index()
            bench_series = bench_series.reindex(portfolio_equity.index).ffill()
        else:
            bench_series = None
    else:
        bench_series = prices.get(benchmark.upper())
        if bench_series is not None:
            bench_series = bench_series.reindex(portfolio_equity.index).ffill()
    if bench_series is None:
        bench_series = portfolio_equity.copy()
    benchmark_equity = (
        1 + bench_series.pct_change(fill_method=None).fillna(0.0)
    ).cumprod()

    out_dir = data_root / "backtest" / "thematic"
    ensure_dir(out_dir)
    equity_path = out_dir / "equity_curve.csv"
    equity_df = pd.DataFrame(
        {
            "date": portfolio_equity.index,
            "portfolio": portfolio_equity.values,
            "benchmark": benchmark_equity.values,
        }
    )
    equity_df.to_csv(equity_path, index=False, encoding="utf-8")

    summary = {
        "portfolio": calc_metrics(portfolio_equity, risk_free),
        "benchmark": calc_metrics(benchmark_equity, risk_free),
        "start": str(portfolio_equity.index[0].date()),
        "end": str(portfolio_equity.index[-1].date()),
        "benchmark_symbol": benchmark,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build_cmd = sub.add_parser("build-universe")
    build_cmd.add_argument(
        "--history-file", type=str, default="", help="S&P500 历史成分文件路径"
    )

    metrics_cmd = sub.add_parser("fetch-metrics")
    metrics_cmd.add_argument("--limit", type=int, default=0, help="限制处理条数")
    fetch_prices_cmd = sub.add_parser("fetch-prices")
    fetch_prices_cmd.add_argument("--overwrite", action="store_true")
    fetch_prices_cmd.add_argument("--limit", type=int, default=0, help="限制处理条数")
    sub.add_parser("backtest")

    args = parser.parse_args()
    base = Path(__file__).resolve().parents[1]
    theme_env = os.environ.get("THEME_CONFIG_PATH")
    weight_env = os.environ.get("WEIGHTS_CONFIG_PATH")
    config_path = Path(theme_env) if theme_env else base / "configs" / "theme_keywords.json"
    weights_path = Path(weight_env) if weight_env else base / "configs" / "portfolio_weights.json"
    data_root = get_data_root()
    history_path = Path(args.history_file).resolve() if getattr(args, "history_file", "") else None

    if args.command == "build-universe":
        universe_path = build_universe(data_root, config_path, history_path)
        print(f"Universe saved: {universe_path}")
    elif args.command == "fetch-metrics":
        universe_path = data_root / "universe" / "universe.csv"
        if not universe_path.exists():
            raise SystemExit("请先运行 build-universe")
        limit = args.limit if getattr(args, "limit", 0) else None
        metrics_path = fetch_metrics(data_root, universe_path, limit)
        print(f"Metrics saved: {metrics_path}")
    elif args.command == "fetch-prices":
        universe_path = data_root / "universe" / "universe.csv"
        if not universe_path.exists():
            raise SystemExit("请先运行 build-universe")
        limit = args.limit if getattr(args, "limit", 0) else None
        status_path = fetch_prices(
            data_root, universe_path, overwrite=getattr(args, "overwrite", False), limit=limit
        )
        print(f"Price fetch status: {status_path}")
    elif args.command == "backtest":
        universe_path = data_root / "universe" / "universe.csv"
        if not universe_path.exists():
            raise SystemExit("请先运行 build-universe")
        summary_path = run_backtest(data_root, universe_path, weights_path)
        print(f"Backtest summary: {summary_path}")


if __name__ == "__main__":
    main()
