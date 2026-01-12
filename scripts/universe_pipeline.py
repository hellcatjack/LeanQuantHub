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
from bisect import bisect_right
from datetime import date, datetime, timedelta
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


def write_theme_config(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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


def normalize_symbol_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result = []
    for item in items:
        symbol = normalize_symbol(str(item))
        if symbol:
            result.append(symbol)
    return result


def normalize_asset_type(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip().upper()
    if not text:
        return "UNKNOWN"
    mapping = {
        "EQUITY": "STOCK",
        "STOCK": "STOCK",
        "COMMON STOCK": "STOCK",
        "ETF": "ETF",
        "ETN": "ETN",
        "ADR": "ADR",
        "REIT": "REIT",
        "FUND": "FUND",
        "INDEX": "INDEX",
    }
    return mapping.get(text, text)


def coerce_priority(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def build_symbol_type_map(config: dict) -> dict[str, str]:
    raw_map = config.get("symbol_types") or {}
    if not isinstance(raw_map, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw_map.items():
        symbol = normalize_symbol(str(key))
        if not symbol:
            continue
        kind = str(value or "").strip().upper()
        if kind:
            result[symbol] = kind
    return result


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
    symbol_types = build_symbol_type_map(config)
    candidates: dict[str, list[dict[str, str]]] = {}

    def add_candidate(symbol: str, payload: dict[str, str]) -> None:
        candidates.setdefault(symbol, []).append(payload)

    for order, category in enumerate(categories):
        key = category.get("key", "").strip()
        label = category.get("label", key)
        if not key:
            continue
        priority = coerce_priority(category.get("priority"), 0)
        exclude_symbols = set(normalize_symbol_list(category.get("exclude") or []))
        pinned_symbols = normalize_symbol_list(category.get("manualPinned") or [])
        manual_symbols = normalize_symbol_list(category.get("manual") or [])
        ordered_manuals: list[str] = []
        for symbol in pinned_symbols + manual_symbols:
            normalized = normalize_symbol(symbol)
            if normalized and normalized not in ordered_manuals:
                ordered_manuals.append(normalized)
        category_seen: set[str] = set()
        for manual in ordered_manuals:
            symbol = normalize_symbol(manual)
            if not symbol or symbol in exclude_symbols or symbol in category_seen:
                continue
            asset_class = symbol_types.get(symbol) or default_asset
            add_candidate(
                symbol,
                {
                    "symbol": symbol,
                    "category": key,
                    "category_label": label,
                    "source": "manual",
                    "keyword": "manual",
                    "region": infer_region(symbol, default_region),
                    "asset_class": asset_class,
                    "priority": str(priority),
                    "source_rank": "1",
                    "order": str(order),
                },
            )
            category_seen.add(symbol)
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
                if not symbol or symbol in exclude_symbols or symbol in category_seen:
                    continue
                asset_class = symbol_types.get(symbol)
                if not asset_class:
                    if quote_type == "ETF":
                        asset_class = "ETF"
                    elif quote_type == "EQUITY":
                        asset_class = "Equity"
                    else:
                        asset_class = default_asset
                add_candidate(
                    symbol,
                    {
                        "symbol": symbol,
                        "category": key,
                        "category_label": label,
                        "source": "yahoo",
                        "keyword": keyword,
                        "region": infer_region(symbol, default_region),
                        "asset_class": asset_class,
                        "priority": str(priority),
                        "source_rank": "0",
                        "order": str(order),
                    },
                )
                category_seen.add(symbol)
            if pause:
                time.sleep(pause)

    winners: list[dict[str, str]] = []

    def rank(item: dict[str, str]) -> tuple[int, int, int]:
        return (
            coerce_priority(item.get("priority"), 0),
            coerce_priority(item.get("source_rank"), 0),
            -coerce_priority(item.get("order"), 0),
        )

    for symbol, items in candidates.items():
        if not items:
            continue
        winner = max(items, key=rank)
        winner.pop("priority", None)
        winner.pop("source_rank", None)
        winner.pop("order", None)
        winners.append(winner)
    return winners


def refresh_theme_manuals(
    config_path: Path,
    keys: list[str],
    manual_limit: int | None,
) -> dict[str, list[str]]:
    config = load_theme_config(config_path)
    categories = config.get("categories", [])
    yahoo_cfg = config.get("yahoo", {})
    allow_exchanges = set(yahoo_cfg.get("allowExchanges") or [])
    count = int(yahoo_cfg.get("quotesCount") or 25)
    pause = float(yahoo_cfg.get("pauseSeconds") or 0)
    default_limit = int(yahoo_cfg.get("manualMax") or 40)
    limit = manual_limit if manual_limit and manual_limit > 0 else default_limit
    manual_mode = str(yahoo_cfg.get("manualMode") or "merge").strip().lower()
    selected = {key.strip().upper() for key in keys if key.strip()}
    updated: dict[str, list[str]] = {}

    def collect_symbols(category: dict) -> list[str]:
        keywords = category.get("keywords", []) or []
        exclude_symbols = set(normalize_symbol_list(category.get("exclude") or []))
        pinned = [
            symbol
            for symbol in normalize_symbol_list(category.get("manualPinned") or [])
            if symbol not in exclude_symbols
        ]
        base_manual = [
            symbol
            for symbol in normalize_symbol_list(category.get("manual") or [])
            if symbol not in exclude_symbols
        ]
        if manual_mode == "replace":
            base_manual = []
        merged_base: list[str] = []
        for symbol in pinned + base_manual:
            if symbol not in merged_base:
                merged_base.append(symbol)
        scores: dict[str, int] = {}
        for keyword in keywords:
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
                if not symbol or symbol in exclude_symbols:
                    continue
                scores[symbol] = scores.get(symbol, 0) + 1
            if pause:
                time.sleep(pause)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        symbols = [symbol for symbol, _ in ranked if symbol not in exclude_symbols]
        merged = merged_base + [
            symbol for symbol in symbols if symbol not in merged_base
        ]
        if limit and len(merged) > limit:
            merged = merged[:limit]
        return merged

    for category in categories:
        key = str(category.get("key", "")).strip().upper()
        if not key or (selected and key not in selected):
            continue
        symbols = collect_symbols(category)
        category["manual"] = symbols
        updated[key] = symbols

    write_theme_config(config_path, config)
    return updated


def build_universe(
    data_root: Path, config_path: Path, history_path: Path | None
) -> Path:
    membership = build_membership(data_root, history_path)
    current_symbols = {
        entry["symbol"]
        for entry in membership
        if entry.get("symbol")
        and not (entry.get("end_date") or "").strip()
    }
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
            if symbol in current_symbols:
                category = "SP500_CURRENT"
                label = "S&P500现有成分"
            else:
                category = "SP500_FORMER"
                label = "S&P500历史成分（现存）"
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


def load_symbol_map(
    path: Path,
) -> dict[str, list[tuple[date | None, date | None, str]]]:
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]] = {}
    if not path.exists():
        return symbol_map
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            canonical = (row.get("canonical") or "").strip().upper()
            if not symbol or not canonical:
                continue
            start = parse_date(row.get("start_date") or row.get("from_date") or "")
            end = parse_date(row.get("end_date") or row.get("to_date") or "")
            symbol_map.setdefault(symbol, []).append((start, end, canonical))
    for entries in symbol_map.values():
        entries.sort(key=lambda item: item[0] or date.min)
    return symbol_map


def resolve_symbol_alias(
    symbol: str,
    as_of: date | None,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> str:
    entries = symbol_map.get(symbol)
    if not entries:
        return symbol
    if as_of:
        match = None
        for start, end, canonical in entries:
            if start and as_of < start:
                continue
            if end and as_of > end:
                continue
            match = canonical
        if match:
            return match
    return entries[-1][2]


def build_alias_map(
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    for alias, entries in symbol_map.items():
        for _, _, canonical in entries:
            alias_map.setdefault(canonical, set()).add(alias)
    return alias_map


def merge_symbol_life(
    symbol_life: dict[str, tuple[date | None, date | None]],
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> dict[str, tuple[date | None, date | None]]:
    merged = dict(symbol_life)
    for alias, entries in symbol_map.items():
        life = symbol_life.get(alias)
        if not life:
            continue
        for _, _, canonical in entries:
            existing = merged.get(canonical)
            if not existing:
                merged[canonical] = life
                continue
            ipo = min([d for d in (existing[0], life[0]) if d], default=None)
            delist = max([d for d in (existing[1], life[1]) if d], default=None)
            merged[canonical] = (ipo, delist)
    return merged


def remap_membership_ranges(
    ranges: dict[str, list[tuple[date | None, date | None]]],
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> dict[str, list[tuple[date | None, date | None]]]:
    if not symbol_map:
        return ranges
    remapped: dict[str, list[tuple[date | None, date | None]]] = {}
    for symbol, items in ranges.items():
        for start, end in items:
            pivot = start or end
            mapped = resolve_symbol_alias(symbol, pivot, symbol_map)
            remapped.setdefault(mapped, []).append((start, end))
    return remapped


def load_symbol_life(path: Path) -> dict[str, tuple[date | None, date | None]]:
    life: dict[str, tuple[date | None, date | None]] = {}
    if not path.exists():
        return life
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            ipo = parse_date(row.get("ipoDate") or row.get("ipo_date") or row.get("ipo") or "")
            delist = parse_date(
                row.get("delistingDate") or row.get("delisting_date") or row.get("delist") or ""
            )
            life[symbol] = (ipo, delist)
    return life


def load_symbol_asset_types(
    path: Path,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]] | None = None,
) -> dict[str, str]:
    types: dict[str, str] = {}
    if not path.exists():
        return types
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            asset_type = normalize_asset_type(row.get("assetType") or row.get("asset_type") or "")
            if not asset_type or asset_type == "UNKNOWN":
                continue
            if symbol_map:
                symbol = resolve_symbol_alias(symbol, None, symbol_map)
            types[symbol] = asset_type
    return types


def load_symbol_life_overrides(path: Path) -> dict[str, tuple[date | None, date | None]]:
    overrides: dict[str, tuple[date | None, date | None]] = {}
    if not path.exists():
        return overrides
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            ipo = parse_date(row.get("ipoDate") or row.get("ipo_date") or row.get("ipo") or "")
            delist = parse_date(
                row.get("delistingDate") or row.get("delisting_date") or row.get("delist") or ""
            )
            overrides[symbol] = (ipo, delist)
    return overrides


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


def resolve_backtest_output_dir(data_root: Path, weights_cfg: dict[str, object]) -> Path:
    output_override = str(weights_cfg.get("output_dir") or "").strip()
    env_override = (
        os.getenv("THEMATIC_BACKTEST_OUTPUT_DIR") or os.getenv("BACKTEST_OUTPUT_DIR") or ""
    ).strip()
    if env_override:
        output_override = env_override
    if output_override:
        out = Path(output_override)
        if not out.is_absolute():
            out = data_root / out
        return out
    return data_root / "backtest" / "thematic"


def run_backtest(data_root: Path, universe_path: Path, config_path: Path) -> Path:
    import pandas as pd

    weights_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    benchmark = weights_cfg.get("benchmark", "SPY")
    rebalance_cfg = str(weights_cfg.get("rebalance", "W")).strip().upper()
    rebalance_mode = str(weights_cfg.get("rebalance_mode", "week_open")).strip().lower()
    use_pit = bool(weights_cfg.get("use_pit_weekly", True))
    category_weights: dict[str, float] = weights_cfg.get("category_weights", {})
    risk_free = float(weights_cfg.get("risk_free_rate", 0.0))
    price_source_policy = str(weights_cfg.get("price_source_policy", "adjusted_only")).strip().lower()
    if price_source_policy not in {"adjusted_only", "adjusted_prefer", "raw_only"}:
        raise SystemExit("price_source_policy must be adjusted_only, adjusted_prefer, or raw_only")
    vendor_preference = weights_cfg.get("price_vendor_preference") or weights_cfg.get(
        "vendor_preference"
    )
    if not vendor_preference:
        vendor_preference = ["Alpha"]
    if isinstance(vendor_preference, str):
        vendor_preference = [item.strip() for item in vendor_preference.split(",") if item.strip()]
    vendor_preference = [
        item for item in vendor_preference if str(item).strip().upper() == "ALPHA"
    ] or ["Alpha"]
    if price_source_policy != "adjusted_only":
        price_source_policy = "adjusted_only"
    signal_mode = str(weights_cfg.get("signal_mode") or "theme_weights").strip().lower()
    if signal_mode not in {"theme_weights", "ml_scores"}:
        raise SystemExit("signal_mode must be theme_weights or ml_scores")
    project_root = Path(__file__).resolve().parents[1]
    score_path_raw = str(weights_cfg.get("score_csv_path") or "").strip()
    score_path = Path(score_path_raw) if score_path_raw else project_root / "ml" / "models" / "scores.csv"
    if not score_path.is_absolute():
        score_path = project_root / score_path
    score_top_n = int(weights_cfg.get("score_top_n") or 0)
    score_weighting = str(weights_cfg.get("score_weighting") or "score").strip().lower()
    if score_weighting not in {"score", "equal"}:
        raise SystemExit("score_weighting must be score or equal")
    score_min_raw = weights_cfg.get("score_min")
    if score_min_raw in (None, ""):
        score_min = None
    else:
        score_min = float(score_min_raw)
    score_max_raw = weights_cfg.get("score_max_weight")
    if score_max_raw in (None, ""):
        score_max_weight = None
    else:
        score_max_weight = float(score_max_raw)
    score_fallback = str(weights_cfg.get("score_fallback") or "theme_weights").strip().lower()
    if score_fallback not in {"theme_weights", "universe", "skip"}:
        raise SystemExit("score_fallback must be theme_weights, universe, or skip")
    min_avg_volume = max(float(weights_cfg.get("min_avg_volume") or 0.0), 0.0)
    min_avg_dollar_volume = max(float(weights_cfg.get("min_avg_dollar_volume") or 0.0), 0.0)
    liquidity_window_days = max(int(weights_cfg.get("liquidity_window_days") or 20), 1)
    halt_volume_threshold = max(float(weights_cfg.get("halt_volume_threshold") or 0.0), 0.0)
    record_universe = bool(weights_cfg.get("record_universe", True))
    universe_output_dir = str(weights_cfg.get("universe_output_dir") or "").strip()
    out_dir = resolve_backtest_output_dir(data_root, weights_cfg)
    execution_cfg = weights_cfg.get("execution", {}) if isinstance(weights_cfg.get("execution"), dict) else {}
    max_holdings = int(execution_cfg.get("max_holdings") or weights_cfg.get("max_holdings") or 0)
    max_position_raw = execution_cfg.get("max_position_weight", weights_cfg.get("max_position_weight"))
    if max_position_raw in (None, ""):
        max_position_weight = None
    else:
        max_position_weight = float(max_position_raw)
    turnover_raw = execution_cfg.get("turnover_limit", weights_cfg.get("turnover_limit"))
    if turnover_raw in (None, ""):
        turnover_limit = None
    else:
        turnover_limit = float(turnover_raw)
    trade_weekdays_raw = execution_cfg.get("trade_weekdays", weights_cfg.get("trade_weekdays"))
    trade_day_policy = str(
        execution_cfg.get(
            "trade_day_policy", weights_cfg.get("trade_day_policy", "shift")
        )
    ).strip().lower()
    if trade_day_policy not in {"shift", "skip"}:
        raise SystemExit("trade_day_policy must be shift or skip")
    max_shift_raw = execution_cfg.get("max_shift_days", weights_cfg.get("max_shift_days"))
    if max_shift_raw in (None, ""):
        max_shift_days = None
    else:
        max_shift_days = max(int(max_shift_raw), 0)

    def _parse_asset_types(value: object) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]
        normalized = {normalize_asset_type(item) for item in items if str(item).strip()}
        return {item for item in normalized if item and item != "UNKNOWN"}

    allowed_asset_types = _parse_asset_types(weights_cfg.get("asset_types"))
    pit_universe_only = bool(
        weights_cfg.get("pit_universe_only")
        or weights_cfg.get("pit_only_universe")
        or weights_cfg.get("pit_universe")
    )
    backtest_start = parse_date(str(weights_cfg.get("backtest_start") or weights_cfg.get("start") or ""))
    backtest_end = parse_date(str(weights_cfg.get("backtest_end") or weights_cfg.get("end") or ""))

    plugins = weights_cfg.get("backtest_plugins")
    if not isinstance(plugins, dict):
        plugins = {}

    def _coerce_int(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_float(value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    score_delay_days = max(
        _coerce_int(
            plugins.get("score_delay_days", weights_cfg.get("score_delay_days", 0)), 0
        ),
        0,
    )
    score_smoothing_cfg = plugins.get("score_smoothing") if isinstance(plugins.get("score_smoothing"), dict) else {}
    score_smoothing_enabled = bool(score_smoothing_cfg.get("enabled", False))
    score_smoothing_method = str(score_smoothing_cfg.get("method") or "").strip().lower()
    if score_smoothing_enabled and not score_smoothing_method:
        score_smoothing_method = "ema"
    score_smoothing_alpha = _coerce_float(score_smoothing_cfg.get("alpha"), 0.0)
    if score_smoothing_alpha < 0:
        score_smoothing_alpha = 0.0
    if score_smoothing_alpha > 1:
        score_smoothing_alpha = 1.0
    score_smoothing_carry = bool(score_smoothing_cfg.get("carry_missing", True))

    score_hysteresis_cfg = (
        plugins.get("score_hysteresis") if isinstance(plugins.get("score_hysteresis"), dict) else {}
    )
    score_hysteresis_enabled = bool(score_hysteresis_cfg.get("enabled", False))
    score_retain_top_n = (
        _coerce_int(score_hysteresis_cfg.get("retain_top_n", 0), 0)
        if score_hysteresis_enabled
        else 0
    )

    weight_smoothing_cfg = (
        plugins.get("weight_smoothing") if isinstance(plugins.get("weight_smoothing"), dict) else {}
    )
    weight_smoothing_alpha = _coerce_float(weight_smoothing_cfg.get("alpha"), 0.0)
    if weight_smoothing_alpha < 0:
        weight_smoothing_alpha = 0.0
    if weight_smoothing_alpha > 1:
        weight_smoothing_alpha = 1.0
    weight_smoothing_enabled = bool(weight_smoothing_cfg.get("enabled", False))

    risk_cfg = plugins.get("risk_control") if isinstance(plugins.get("risk_control"), dict) else {}
    risk_enabled = bool(risk_cfg.get("enabled", False)) if risk_cfg else bool(weights_cfg.get("market_filter", False))
    market_filter = bool(risk_cfg.get("market_filter", risk_enabled))
    market_ma_window = _coerce_int(
        risk_cfg.get("market_ma_window", weights_cfg.get("market_ma_window", 200)), 200
    )
    risk_off_mode = str(risk_cfg.get("risk_off_mode") or weights_cfg.get("risk_off_mode") or "cash").strip().lower()
    max_exposure = _coerce_float(risk_cfg.get("max_exposure", weights_cfg.get("max_exposure", 1.0)), 1.0)
    if max_exposure <= 0:
        max_exposure = 0.0
    if max_exposure > 1:
        max_exposure = 1.0

    universe = read_csv(universe_path)
    symbol_map_path = str(weights_cfg.get("symbol_map_path") or "").strip()
    symbol_map_file = (
        Path(symbol_map_path).expanduser().resolve()
        if symbol_map_path
        else data_root / "universe" / "symbol_map.csv"
    )
    symbol_map = load_symbol_map(symbol_map_file) if symbol_map_file.exists() else {}
    alias_map = build_alias_map(symbol_map)

    membership_rows = read_csv(data_root / "universe" / "sp500_membership.csv")
    membership_ranges = load_membership_ranges(membership_rows)
    if symbol_map:
        membership_ranges = remap_membership_ranges(membership_ranges, symbol_map)
    symbol_life_path = weights_cfg.get("symbol_life_path")
    life_path = (
        Path(symbol_life_path).expanduser().resolve()
        if symbol_life_path
        else data_root / "universe" / "alpha_symbol_life.csv"
    )
    symbol_life = load_symbol_life(life_path) if life_path.exists() else {}
    if symbol_map:
        symbol_life = merge_symbol_life(symbol_life, symbol_map)
    override_path_raw = str(weights_cfg.get("symbol_life_override_path") or "").strip()
    if override_path_raw:
        override_path = Path(override_path_raw).expanduser().resolve()
    else:
        override_path = data_root / "universe" / "symbol_life_override.csv"
    symbol_life_overrides = (
        load_symbol_life_overrides(override_path) if override_path.exists() else {}
    )
    if symbol_life_overrides:
        if symbol_map:
            remapped: dict[str, tuple[date | None, date | None]] = {}
            for symbol, values in symbol_life_overrides.items():
                mapped = resolve_symbol_alias(symbol, None, symbol_map)
                remapped[mapped] = values
            symbol_life_overrides = remapped
        for symbol, values in symbol_life_overrides.items():
            symbol_life[symbol] = values
    asset_type_path_raw = str(weights_cfg.get("asset_type_path") or "").strip()
    asset_type_path = (
        Path(asset_type_path_raw).expanduser().resolve()
        if asset_type_path_raw
        else life_path
    )
    asset_type_map = (
        load_symbol_asset_types(asset_type_path, symbol_map)
        if asset_type_path.exists()
        else {}
    )
    exclude_symbols_path = str(weights_cfg.get("exclude_symbols_path") or "").strip()
    if exclude_symbols_path:
        exclude_path = Path(exclude_symbols_path).expanduser().resolve()
    else:
        exclude_path = data_root / "universe" / "exclude_symbols.csv"
    exclude_symbols = set()
    if exclude_path.exists():
        for row in read_csv(exclude_path):
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol:
                exclude_symbols.add(symbol)
    category_by_symbol: dict[str, str] = {}
    asset_type_by_symbol: dict[str, str] = dict(asset_type_map)
    for row in universe:
        raw_symbol = row.get("symbol", "").strip().upper()
        if not raw_symbol:
            continue
        mapped = resolve_symbol_alias(raw_symbol, None, symbol_map)
        category_by_symbol[mapped] = row.get("category", "")
        if mapped not in asset_type_by_symbol:
            asset_type = asset_type_map.get(mapped) or asset_type_map.get(raw_symbol)
            if not asset_type:
                asset_type = normalize_asset_type(row.get("asset_class") or "")
            asset_type_by_symbol[mapped] = asset_type or "UNKNOWN"
    stooq_dir = data_root / "prices" / "stooq"
    yahoo_dir = data_root / "prices" / "yahoo"
    curated_dir = data_root / "curated"
    curated_adjusted_dir = data_root / "curated_adjusted"
    normalized_dir = data_root / "normalized"

    def build_symbol_map(source_dir: Path) -> dict[str, Path]:
        symbol_map: dict[str, Path] = {}
        if not source_dir.exists():
            return symbol_map
        for file in source_dir.glob("*.csv"):
            parts = file.stem.split("_")
            if len(parts) < 4:
                continue
            symbol_parts = parts[2:-1]
            if not symbol_parts:
                continue
            symbol = "_".join(symbol_parts).strip().upper()
            if symbol and symbol not in symbol_map:
                symbol_map[symbol] = file
        return symbol_map

    def build_adjusted_vendor_map(source_dir: Path) -> dict[str, dict[str, Path]]:
        symbol_map: dict[str, dict[str, Path]] = {}
        if not source_dir.exists():
            return symbol_map
        for file in source_dir.glob("*.csv"):
            parts = file.stem.split("_")
            if len(parts) < 4:
                continue
            vendor = parts[1].strip().upper()
            symbol_parts = parts[2:-1]
            if not symbol_parts:
                continue
            symbol = "_".join(symbol_parts).strip().upper()
            if not symbol:
                continue
            symbol_map.setdefault(symbol, {})[vendor] = file
        return symbol_map

    curated_map = build_symbol_map(curated_dir)
    curated_adjusted_map = build_adjusted_vendor_map(curated_adjusted_dir)
    normalized_map = build_symbol_map(normalized_dir)

    def _pick_vendor_path(vendor_map: dict[str, Path]) -> Path | None:
        if not vendor_map:
            return None
        for vendor in vendor_preference:
            candidate = vendor_map.get(str(vendor).strip().upper())
            if candidate:
                return candidate
        return None

    def _expand_symbol_variants(value: str) -> list[str]:
        variants = [value]
        if "." in value:
            variants.append(value.replace(".", "_"))
            variants.append(value.replace(".", "-"))
        if "-" in value:
            variants.append(value.replace("-", "_"))
        return [item for item in variants if item]

    def resolve_symbol_path(symbol: str, mapped_symbol: str) -> tuple[Path | None, str, str]:
        candidates: list[str] = []
        if mapped_symbol:
            candidates.extend(_expand_symbol_variants(mapped_symbol))
        if symbol and symbol != mapped_symbol:
            candidates.extend(_expand_symbol_variants(symbol))
        for alias in sorted(alias_map.get(mapped_symbol, set())):
            candidates.extend(_expand_symbol_variants(alias))
        for alias in sorted(alias_map.get(symbol, set())):
            candidates.extend(_expand_symbol_variants(alias))
        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            adjusted_path = _pick_vendor_path(curated_adjusted_map.get(candidate, {}))
            if price_source_policy != "raw_only" and adjusted_path:
                return adjusted_path, "adjusted", candidate
            if price_source_policy == "adjusted_only":
                continue
            curated_path = curated_map.get(candidate) or normalized_map.get(candidate)
            if curated_path:
                return curated_path, "raw", candidate
            stooq_path = stooq_dir / f"{candidate}.csv"
            if stooq_path.exists():
                return stooq_path, "raw", candidate
            yahoo_path = yahoo_dir / f"{candidate}.csv"
            if yahoo_path.exists():
                return yahoo_path, "raw", candidate
        return None, "raw", mapped_symbol or symbol

    frames = []
    open_frames = []
    volume_frames = []
    used_modes: set[str] = set()
    seen_symbols: set[str] = set()
    price_source_counts = {"adjusted": 0, "raw": 0}
    missing_adjusted: list[str] = []
    volume_missing: set[str] = set()
    open_missing: set[str] = set()
    need_volume = any(
        value > 0 for value in (min_avg_volume, min_avg_dollar_volume, halt_volume_threshold)
    )
    for row in universe:
        raw_symbol = row.get("symbol", "").strip().upper()
        if not raw_symbol:
            continue
        mapped_symbol = resolve_symbol_alias(raw_symbol, None, symbol_map)
        if mapped_symbol in seen_symbols:
            continue
        if mapped_symbol in exclude_symbols:
            continue
        asset_type = asset_type_by_symbol.get(mapped_symbol, "UNKNOWN")
        if allowed_asset_types and asset_type not in allowed_asset_types:
            continue
        path, mode, resolved_symbol = resolve_symbol_path(raw_symbol, mapped_symbol)
        if not path or not path.exists():
            if price_source_policy == "adjusted_only":
                missing_adjusted.append(mapped_symbol)
            continue
        df = pd.read_csv(path)
        column_map = {col.lower(): col for col in df.columns}
        date_col = column_map.get("date")
        close_col = column_map.get("close")
        open_col = column_map.get("open")
        if not date_col or not close_col:
            continue
        columns = [date_col, close_col]
        if open_col:
            columns.append(open_col)
        volume_col = column_map.get("volume") if need_volume else None
        if volume_col:
            columns.append(volume_col)
        df = df[columns]
        df = df.rename(columns={date_col: "date"})
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None)
        df = df.set_index("date")
        frames.append(df[[close_col]].rename(columns={close_col: mapped_symbol}))
        if open_col:
            open_frames.append(df[[open_col]].rename(columns={open_col: mapped_symbol}))
        else:
            open_missing.add(mapped_symbol)
        if need_volume:
            if volume_col:
                volume_frames.append(df[[volume_col]].rename(columns={volume_col: mapped_symbol}))
            else:
                volume_missing.add(mapped_symbol)
        used_modes.add(mode)
        if mode in price_source_counts:
            price_source_counts[mode] += 1
        seen_symbols.add(mapped_symbol)

    if not frames:
        raise SystemExit("未找到可用的价格数据")

    prices = pd.concat(frames, axis=1).sort_index()
    prices = prices.dropna(how="all")
    price_symbol_set = set(prices.columns)
    if open_frames:
        open_prices = pd.concat(open_frames, axis=1).sort_index()
        open_prices = open_prices.reindex(prices.index)
    else:
        open_prices = pd.DataFrame(index=prices.index)
    open_prices = open_prices.reindex(columns=prices.columns)
    if open_missing:
        for symbol in open_missing:
            if symbol in prices.columns:
                open_prices[symbol] = prices[symbol]
    if open_prices.empty:
        open_prices = prices.copy()
    else:
        open_prices = open_prices.combine_first(prices)
    volumes = None
    if need_volume and volume_frames:
        volumes = pd.concat(volume_frames, axis=1).sort_index()
        volumes = volumes.reindex(prices.index)
    trade_price_mode = str(weights_cfg.get("trade_price") or weights_cfg.get("trade_price_mode") or "").strip().lower()
    if not trade_price_mode:
        trade_price_mode = "open" if "open" in rebalance_mode else "close"
    if trade_price_mode not in {"open", "close"}:
        raise SystemExit("trade_price must be open or close")
    trade_prices = open_prices if trade_price_mode == "open" else prices

    benchmark_symbol = resolve_symbol_alias(benchmark.upper(), None, symbol_map)
    benchmark_series = prices.get(benchmark_symbol)
    if benchmark_series is None or benchmark_series.dropna().empty:
        benchmark_path, _, _ = resolve_symbol_path(benchmark.upper(), benchmark_symbol)
        if benchmark_path and benchmark_path.exists():
            bench_df = pd.read_csv(benchmark_path)
            bench_column_map = {col.lower(): col for col in bench_df.columns}
            bench_date_col = bench_column_map.get("date")
            bench_price_col = bench_column_map.get("close")
            if bench_date_col and bench_price_col:
                bench_df = bench_df[[bench_date_col, bench_price_col]].rename(
                    columns={bench_date_col: "date", bench_price_col: benchmark_symbol}
                )
                bench_df["date"] = pd.to_datetime(bench_df["date"], utc=True).dt.tz_convert(None)
                benchmark_series = bench_df.set_index("date")[benchmark_symbol].sort_index()
    if benchmark_series is None or benchmark_series.dropna().empty:
        benchmark_series = trade_prices.get(benchmark_symbol)
    if benchmark_series is not None:
        benchmark_series = benchmark_series.reindex(prices.index).ffill()
    benchmark_sma = (
        benchmark_series.rolling(market_ma_window).mean()
        if market_filter and benchmark_series is not None
        else None
    )
    returns = trade_prices.shift(-1) / trade_prices - 1
    returns = returns.fillna(0.0)
    min_history_days = int(weights_cfg.get("min_history_days") or 0)
    min_price = float(weights_cfg.get("min_price") or 0.0)
    valid_counts = prices.notna().cumsum()
    cost_cfg = weights_cfg.get("costs", {}) if isinstance(weights_cfg.get("costs"), dict) else {}
    plugin_costs = plugins.get("costs") if isinstance(plugins.get("costs"), dict) else {}
    if plugin_costs:
        cost_cfg = {**cost_cfg, **plugin_costs}
    fee_bps = float(cost_cfg.get("fee_bps", weights_cfg.get("fee_bps", 0.0)) or 0.0)
    slippage_bps = float(
        cost_cfg.get("slippage_bps", weights_cfg.get("slippage_bps", 0.0)) or 0.0
    )
    impact_bps = float(
        cost_cfg.get("impact_bps", weights_cfg.get("impact_bps", 0.0)) or 0.0
    )
    total_cost_bps = max(fee_bps + slippage_bps + impact_bps, 0.0)
    cost_rate = total_cost_bps / 10000.0

    def load_pit_weekly_snapshots() -> tuple[dict[date, set[str]], dict[date, date]]:
        pit_dir = weights_cfg.get("pit_weekly_dir")
        pit_root = Path(pit_dir).expanduser().resolve() if pit_dir else data_root / "universe" / "pit_weekly"
        if not pit_root.exists():
            return {}, {}
        pit_map: dict[date, set[str]] = {}
        snapshot_map: dict[date, date] = {}
        for path in pit_root.glob("pit_*.csv"):
            with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    symbol = (row.get("symbol") or "").strip().upper()
                    rebalance_raw = (row.get("rebalance_date") or "").strip()
                    snapshot_raw = (row.get("snapshot_date") or "").strip()
                    if not symbol or not rebalance_raw:
                        continue
                    try:
                        rebalance_date = datetime.strptime(rebalance_raw, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    snapshot_date = None
                    if snapshot_raw:
                        try:
                            snapshot_date = datetime.strptime(snapshot_raw, "%Y-%m-%d").date()
                            snapshot_map[rebalance_date] = snapshot_date
                        except ValueError:
                            pass
                    mapped_symbol = resolve_symbol_alias(
                        symbol, snapshot_date or rebalance_date, symbol_map
                    )
                    pit_map.setdefault(rebalance_date, set()).add(mapped_symbol)
        return pit_map, snapshot_map

    def _load_scores(path: Path) -> tuple[dict[date, dict[str, float]], list[date]]:
        scores: dict[date, dict[str, float]] = {}
        if not path.exists():
            return scores, []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                date_str = (row.get("date") or "").strip()
                symbol = (row.get("symbol") or "").strip().upper()
                if not date_str or not symbol:
                    continue
                try:
                    score_val = float(row.get("score", ""))
                except ValueError:
                    continue
                try:
                    score_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                mapped_symbol = resolve_symbol_alias(symbol, score_date, symbol_map)
                scores.setdefault(score_date, {})[mapped_symbol] = score_val
        score_dates = sorted(scores.keys())
        return scores, score_dates

    def _closest_score_date(dates: list[date], target: date) -> date | None:
        if not dates:
            return None
        idx = bisect_right(dates, target) - 1
        if idx < 0:
            return None
        return dates[idx]

    def _cap_and_normalize(weights: dict[str, float], cap: float) -> dict[str, float]:
        capped: dict[str, float] = {}
        remaining = dict(weights)
        for _ in range(len(remaining) + 1):
            over = {symbol: w for symbol, w in remaining.items() if w > cap}
            if not over:
                break
            for symbol in over:
                capped[symbol] = cap
                remaining.pop(symbol, None)
            remainder = 1.0 - sum(capped.values())
            if remainder <= 0 or not remaining:
                remaining = {}
                break
            total = sum(remaining.values())
            if total <= 0:
                remaining = {}
                break
            for symbol in list(remaining.keys()):
                remaining[symbol] = remaining[symbol] / total * remainder
        merged = {**remaining, **capped}
        total = sum(merged.values())
        if total > 0:
            merged = {symbol: weight / total for symbol, weight in merged.items()}
        return merged

    def _parse_weekdays(value) -> set[int]:
        if value is None or value == "":
            return set()
        if isinstance(value, list):
            tokens = value
        elif isinstance(value, str):
            tokens = [token.strip().lower() for token in value.split(",") if token.strip()]
        else:
            tokens = [value]
        mapping = {
            "mon": 0,
            "monday": 0,
            "tue": 1,
            "tues": 1,
            "tuesday": 1,
            "wed": 2,
            "wednesday": 2,
            "thu": 3,
            "thurs": 3,
            "thursday": 3,
            "fri": 4,
            "friday": 4,
            "sat": 5,
            "saturday": 5,
            "sun": 6,
            "sunday": 6,
        }
        weekdays: set[int] = set()
        for token in tokens:
            if isinstance(token, int):
                if 0 <= token <= 6:
                    weekdays.add(token)
                continue
            if isinstance(token, str):
                if token.isdigit():
                    num = int(token)
                    if 0 <= num <= 6:
                        weekdays.add(num)
                    continue
                mapped = mapping.get(token)
                if mapped is not None:
                    weekdays.add(mapped)
        return weekdays

    def _adjust_rebalance_dates(
        dates: list[date],
        trading_index: pd.DatetimeIndex,
        allowed_weekdays: set[int],
        policy: str,
        max_shift: int | None,
        pit_map: dict[date, set[str]] | None = None,
        pit_snapshot_map: dict[date, date] | None = None,
    ) -> tuple[list[date], dict[date, set[str]] | None, dict[date, date] | None, int, int]:
        if not allowed_weekdays:
            return dates, pit_map, pit_snapshot_map, 0, 0
        trading_days = [ts.date() for ts in trading_index]
        by_week: dict[tuple[int, int], list[date]] = {}
        for day in trading_days:
            by_week.setdefault(day.isocalendar()[:2], []).append(day)
        for key in by_week:
            by_week[key].sort()
        shifted = 0
        skipped = 0
        adjusted: list[date] = []
        new_pit = {} if pit_map is not None else None
        new_snapshots = {} if pit_snapshot_map is not None else None
        for rebalance in dates:
            target = rebalance
            if rebalance.weekday() not in allowed_weekdays:
                if policy == "skip":
                    skipped += 1
                    continue
                week_key = rebalance.isocalendar()[:2]
                candidates = [
                    day
                    for day in by_week.get(week_key, [])
                    if day.weekday() in allowed_weekdays and day >= rebalance
                ]
                if not candidates:
                    skipped += 1
                    continue
                target = candidates[0]
                if max_shift is not None:
                    shift_days = (target - rebalance).days
                    if shift_days > max_shift:
                        skipped += 1
                        continue
                if target != rebalance:
                    shifted += 1
            adjusted.append(target)
            if new_pit is not None and pit_map is not None:
                new_pit.setdefault(target, set()).update(pit_map.get(rebalance, set()))
            if new_snapshots is not None and pit_snapshot_map is not None:
                if rebalance in pit_snapshot_map:
                    new_snapshots[target] = pit_snapshot_map[rebalance]
        adjusted = sorted(set(adjusted))
        if new_pit is not None:
            new_pit = {key: new_pit.get(key, set()) for key in adjusted}
        if new_snapshots is not None:
            new_snapshots = {key: new_snapshots.get(key, key) for key in adjusted}
        return adjusted, new_pit, new_snapshots, shifted, skipped

    def _apply_max_holdings(
        weights: dict[str, float], limit: int
    ) -> tuple[dict[str, float], list[str]]:
        if limit <= 0 or len(weights) <= limit:
            return weights, []
        ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
        keep = dict(ranked[:limit])
        dropped = [symbol for symbol, _ in ranked[limit:]]
        total = sum(keep.values())
        if total > 0:
            keep = {symbol: weight / total for symbol, weight in keep.items()}
        return keep, dropped

    def _apply_turnover_limit(
        target: pd.Series, prev: pd.Series, limit: float
    ) -> tuple[pd.Series, float, float]:
        delta = target - prev
        buy_turnover = float(delta.clip(lower=0.0).sum())
        if limit <= 0 or buy_turnover <= limit:
            return target, buy_turnover, 1.0
        scale = limit / buy_turnover if buy_turnover > 0 else 1.0
        adjusted = prev + delta * scale
        return adjusted, buy_turnover, scale

    def pick_week_open_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
        if index.empty:
            return []
        dates = []
        last_week: tuple[int, int] | None = None
        for ts in index:
            week_key = ts.isocalendar()[:2]
            if week_key != last_week:
                dates.append(ts)
                last_week = week_key
        return dates

    scores_by_date: dict[date, dict[str, float]] = {}
    score_dates: list[date] = []
    if signal_mode == "ml_scores":
        scores_by_date, score_dates = _load_scores(score_path)
    has_scores = bool(scores_by_date)

    pit_map, pit_snapshot_map = load_pit_weekly_snapshots() if use_pit else ({}, {})
    if pit_map:
        rebalance_dates = sorted(pit_map.keys())
        pit_used = True
    else:
        pit_used = False
        if rebalance_cfg == "W":
            raw_rebalance = pick_week_open_dates(prices.index)
        else:
            raw_rebalance = prices.resample("ME").last().index
        rebalance_dates = []
        for ts in raw_rebalance:
            idx = prices.index.get_indexer([ts], method="pad")
            if idx.size and idx[0] >= 0:
                rebalance_dates.append(prices.index[idx[0]].date())
        rebalance_dates = sorted(set(rebalance_dates))
    allowed_weekdays = _parse_weekdays(trade_weekdays_raw)
    trade_day_shifted = 0
    trade_day_skipped = 0
    if allowed_weekdays:
        rebalance_dates, pit_map, pit_snapshot_map, trade_day_shifted, trade_day_skipped = (
            _adjust_rebalance_dates(
                rebalance_dates,
                prices.index,
                allowed_weekdays,
                trade_day_policy,
                max_shift_days,
                pit_map if pit_used else None,
                pit_snapshot_map if pit_used else None,
            )
        )
        if not pit_used and pit_map is None:
            pit_map = {}
    if backtest_start or backtest_end:
        rebalance_dates = [
            rebalance
            for rebalance in rebalance_dates
            if (not backtest_start or rebalance >= backtest_start)
            and (not backtest_end or rebalance <= backtest_end)
        ]
        if pit_map is not None:
            pit_map = {rebalance: pit_map.get(rebalance, set()) for rebalance in rebalance_dates}
        if pit_snapshot_map is not None:
            pit_snapshot_map = {
                rebalance: pit_snapshot_map.get(rebalance, rebalance)
                for rebalance in rebalance_dates
            }
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    signal_rows: list[dict[str, str]] = []
    weight_rows: list[dict[str, str]] = []

    universe_records: list[dict[str, str]] = []
    universe_excluded: list[dict[str, str]] = []
    universe_dir = None
    if record_universe:
        universe_dir = Path(universe_output_dir) if universe_output_dir else out_dir / "universe"
        if not universe_dir.is_absolute():
            universe_dir = data_root / universe_dir
        ensure_dir(universe_dir)

    filter_counts: dict[str, int] = {}
    prev_weights_row = pd.Series(0.0, index=prices.columns)
    smoothed_scores: dict[str, float] = {}
    max_holdings_trimmed = 0
    turnover_limited = 0
    turnover_scale_sum = 0.0
    cash_weight_sum = 0.0
    risk_off_count = 0

    for idx, rebalance in enumerate(rebalance_dates):
        snapshot_date = pit_snapshot_map.get(rebalance, rebalance)
        check_date = snapshot_date
        snapshot_ts = pd.Timestamp(snapshot_date)
        snapshot_idx = prices.index.get_indexer([snapshot_ts], method="pad")
        if not snapshot_idx.size or snapshot_idx[0] < 0:
            continue
        snapshot_pos = snapshot_idx[0]
        counts_at_snapshot = (
            valid_counts.iloc[snapshot_pos] if min_history_days > 0 else None
        )
        snapshot_prices = prices.iloc[snapshot_pos]
        window_start = max(0, snapshot_pos - liquidity_window_days + 1)
        window_prices = prices.iloc[window_start : snapshot_pos + 1]
        avg_volume = None
        avg_dollar = None
        snapshot_volumes = None
        if need_volume and volumes is not None and not volumes.empty:
            window_volumes = volumes.iloc[window_start : snapshot_pos + 1]
            avg_volume = window_volumes.mean()
            avg_dollar = (window_volumes * window_prices).mean()
            snapshot_volumes = volumes.iloc[snapshot_pos]
        active_symbols = []
        if pit_used and pit_universe_only:
            symbol_pool = pit_map.get(rebalance, set())
            if symbol_pool:
                symbol_pool = symbol_pool.intersection(price_symbol_set)
        else:
            symbol_pool = prices.columns
        for symbol in symbol_pool:
            reasons: list[str] = []
            asset_type = asset_type_by_symbol.get(symbol, "UNKNOWN")
            if allowed_asset_types and asset_type not in allowed_asset_types:
                reasons.append("asset_type")
                filter_counts["asset_type"] = filter_counts.get("asset_type", 0) + 1
                if record_universe:
                    snapshot_price = snapshot_prices.get(symbol)
                    universe_excluded.append(
                        {
                            "symbol": symbol,
                            "snapshot_date": snapshot_date.isoformat(),
                            "rebalance_date": rebalance.isoformat(),
                            "reason": "asset_type",
                            "snapshot_price": f"{snapshot_price:.6f}"
                            if snapshot_price is not None and not math.isnan(snapshot_price)
                            else "",
                        }
                    )
                continue
            if symbol in exclude_symbols:
                reasons.append("excluded")
            if pit_used and not pit_universe_only and symbol not in pit_map.get(rebalance, set()):
                reasons.append("not_in_pit")
            life = symbol_life.get(symbol)
            if life:
                ipo, delist = life
                if ipo and check_date < ipo:
                    reasons.append("before_ipo")
                if delist and check_date > delist:
                    reasons.append("after_delist")
            ranges = membership_ranges.get(symbol)
            if ranges and not active_in_ranges(ranges, check_date):
                reasons.append("not_in_membership")
            rebalance_ts = pd.Timestamp(rebalance)
            if rebalance_ts not in trade_prices.index:
                reasons.append("missing_rebalance_price")
            price = (
                trade_prices.at[rebalance_ts, symbol]
                if rebalance_ts in trade_prices.index and symbol in trade_prices.columns
                else float("nan")
            )
            if math.isnan(price):
                reasons.append("missing_rebalance_price")
            snapshot_price = snapshot_prices.get(symbol)
            if snapshot_price is None or math.isnan(snapshot_price):
                reasons.append("missing_snapshot_price")
            if min_price > 0 and snapshot_price is not None and not math.isnan(snapshot_price):
                if snapshot_price < min_price:
                    reasons.append("min_price")
            if min_history_days > 0 and counts_at_snapshot is not None:
                if counts_at_snapshot.get(symbol, 0) < min_history_days:
                    reasons.append("min_history")
            if need_volume:
                if symbol in volume_missing or volumes is None or symbol not in volumes.columns:
                    reasons.append("volume_missing")
                else:
                    snapshot_volume = (
                        snapshot_volumes.get(symbol) if snapshot_volumes is not None else None
                    )
                    if snapshot_volume is None or math.isnan(snapshot_volume):
                        reasons.append("volume_missing")
                    if (
                        halt_volume_threshold > 0
                        and snapshot_volume is not None
                        and not math.isnan(snapshot_volume)
                        and snapshot_volume <= halt_volume_threshold
                    ):
                        reasons.append("halted")
                    if min_avg_volume > 0 and avg_volume is not None:
                        avg_vol = avg_volume.get(symbol)
                        if avg_vol is None or math.isnan(avg_vol) or avg_vol < min_avg_volume:
                            reasons.append("min_avg_volume")
                    if min_avg_dollar_volume > 0 and avg_dollar is not None:
                        avg_dv = avg_dollar.get(symbol)
                        if avg_dv is None or math.isnan(avg_dv) or avg_dv < min_avg_dollar_volume:
                            reasons.append("min_avg_dollar_volume")

            if reasons:
                for reason in reasons:
                    filter_counts[reason] = filter_counts.get(reason, 0) + 1
                if record_universe:
                    universe_excluded.append(
                        {
                            "symbol": symbol,
                            "snapshot_date": snapshot_date.isoformat(),
                            "rebalance_date": rebalance.isoformat(),
                            "reason": "|".join(sorted(set(reasons))),
                            "snapshot_price": f"{snapshot_price:.6f}"
                            if snapshot_price is not None and not math.isnan(snapshot_price)
                            else "",
                        }
                    )
                continue
            active_symbols.append(symbol)
            if record_universe:
                universe_records.append(
                    {
                        "symbol": symbol,
                        "snapshot_date": snapshot_date.isoformat(),
                        "rebalance_date": rebalance.isoformat(),
                    }
                )
        if not active_symbols:
            continue
        weights_for_symbols: dict[str, float] = {}
        signal_mode_used = signal_mode
        score_date = None
        selected_symbols: list[str] = []
        selected_scores: dict[str, float] = {}
        risk_off = False
        if market_filter and benchmark_sma is not None and benchmark_series is not None:
            try:
                bench_price = float(benchmark_series.iloc[snapshot_pos])
                bench_sma = float(benchmark_sma.iloc[snapshot_pos])
            except (ValueError, TypeError):
                bench_price = float("nan")
                bench_sma = float("nan")
            if not math.isnan(bench_price) and not math.isnan(bench_sma):
                if bench_price < bench_sma:
                    risk_off = True

        if risk_off:
            risk_off_count += 1
            signal_mode_used = "risk_off"
            if risk_off_mode == "benchmark" and benchmark_symbol in prices.columns:
                weights_for_symbols = {benchmark_symbol: 1.0}
            else:
                weights_for_symbols = {}

        if not risk_off and signal_mode == "ml_scores":
            if not has_scores:
                if score_fallback == "theme_weights":
                    signal_mode_used = "theme_weights"
                elif score_fallback == "universe":
                    selected_symbols = list(active_symbols)
                else:
                    continue
            else:
                score_target = snapshot_date - timedelta(days=score_delay_days) if score_delay_days else snapshot_date
                score_date = _closest_score_date(score_dates, score_target)
                if score_date:
                    scores_for_date = scores_by_date.get(score_date, {})
                    scores_used = scores_for_date
                    if (
                        score_smoothing_enabled
                        and score_smoothing_method == "ema"
                        and score_smoothing_alpha > 0
                    ):
                        for symbol, score in scores_for_date.items():
                            prev = smoothed_scores.get(symbol, score)
                            smoothed_scores[symbol] = (
                                score_smoothing_alpha * score
                                + (1.0 - score_smoothing_alpha) * prev
                            )
                        if score_smoothing_carry:
                            scores_used = smoothed_scores
                        else:
                            scores_used = {
                                symbol: smoothed_scores[symbol] for symbol in scores_for_date
                            }
                    ranked = [
                        (symbol, scores_used[symbol])
                        for symbol in active_symbols
                        if symbol in scores_used
                    ]
                    ranked.sort(key=lambda item: item[1], reverse=True)
                    prev_selected = set(prev_weights_row[prev_weights_row > 0].index)
                    retain_limit = (
                        score_retain_top_n if score_top_n > 0 and score_retain_top_n > score_top_n else 0
                    )
                    if retain_limit and prev_selected:
                        for symbol, score in ranked[:retain_limit]:
                            if score_min is not None and score < score_min:
                                continue
                            if symbol in prev_selected:
                                selected_symbols.append(symbol)
                                selected_scores[symbol] = score
                    for symbol, score in ranked:
                        if score_min is not None and score < score_min:
                            continue
                        if symbol in selected_symbols:
                            continue
                        selected_symbols.append(symbol)
                        selected_scores[symbol] = score
                        if score_top_n > 0 and len(selected_symbols) >= score_top_n:
                            break
                if not selected_symbols:
                    if score_fallback == "theme_weights":
                        signal_mode_used = "theme_weights"
                    elif score_fallback == "universe":
                        selected_symbols = list(active_symbols)
                    else:
                        continue
            if signal_mode_used == "ml_scores":
                if not selected_symbols:
                    continue
                if score_weighting == "score":
                    min_score = score_min if score_min is not None else 0.0
                    raw = [
                        max(float(selected_scores.get(symbol, 0.0)) - min_score, 0.0)
                        for symbol in selected_symbols
                    ]
                    total = sum(raw)
                    if total <= 0:
                        weights_for_symbols = {
                            symbol: 1.0 / len(selected_symbols) for symbol in selected_symbols
                        }
                    else:
                        weights_for_symbols = {
                            symbol: raw[idx] / total
                            for idx, symbol in enumerate(selected_symbols)
                        }
                else:
                    weights_for_symbols = {
                        symbol: 1.0 / len(selected_symbols) for symbol in selected_symbols
                    }
                if score_max_weight and score_max_weight > 0:
                    weights_for_symbols = _cap_and_normalize(
                        weights_for_symbols, float(score_max_weight)
                    )

        if not risk_off and signal_mode_used != "ml_scores":
            symbols_by_category: dict[str, list[str]] = {}
            for symbol in active_symbols:
                category = category_by_symbol.get(symbol) or "SP500_FORMER"
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
            for category, symbols in available_categories.items():
                if not symbols:
                    continue
                share = normalized_weights.get(category, 0.0) / len(symbols)
                for symbol in symbols:
                    weights_for_symbols[symbol] = share

        if not weights_for_symbols and risk_off:
            weight_series = pd.Series(0.0, index=prices.columns)
            start_idx = prices.index.get_loc(pd.Timestamp(rebalance))
            end_idx = (
                prices.index.get_loc(pd.Timestamp(rebalance_dates[idx + 1]))
                if idx + 1 < len(rebalance_dates)
                else len(prices.index)
            )
            weights.iloc[start_idx:end_idx] = weight_series
            prev_weights_row = weight_series
            cash_weight_sum += 1.0
            continue
        if not weights_for_symbols:
            continue

        if max_holdings > 0:
            weights_for_symbols, dropped_symbols = _apply_max_holdings(
                weights_for_symbols, max_holdings
            )
            max_holdings_trimmed += len(dropped_symbols)
            if not weights_for_symbols:
                continue
        if max_position_weight and max_position_weight > 0:
            weights_for_symbols = _cap_and_normalize(
                weights_for_symbols, max_position_weight
            )
        total_weight = sum(weights_for_symbols.values())
        if total_weight <= 0:
            continue
        weights_for_symbols = {
            symbol: weight / total_weight for symbol, weight in weights_for_symbols.items()
        }
        if max_exposure < 1.0:
            weights_for_symbols = {
                symbol: weight * max_exposure for symbol, weight in weights_for_symbols.items()
            }

        weight_row = {symbol: 0.0 for symbol in prices.columns}
        for symbol, weight in weights_for_symbols.items():
            weight_row[symbol] = weight
            score_value = ""
            if signal_mode_used == "ml_scores":
                score_value = (
                    f"{selected_scores.get(symbol, 0.0):.6f}"
                    if symbol in selected_scores
                    else ""
                )
            signal_rows.append(
                {
                    "symbol": symbol,
                    "snapshot_date": snapshot_date.isoformat(),
                    "rebalance_date": rebalance.isoformat(),
                    "signal_mode": signal_mode_used,
                    "score_date": score_date.isoformat() if score_date else "",
                    "score": score_value,
                }
            )
        weight_series = pd.Series(weight_row)
        if not risk_off and weight_smoothing_enabled and 0 < weight_smoothing_alpha < 1:
            weight_series = prev_weights_row * (1.0 - weight_smoothing_alpha) + weight_series * weight_smoothing_alpha
            total_weight = float(weight_series.sum())
            if total_weight > 0:
                weight_series = weight_series / total_weight
        if turnover_limit and turnover_limit > 0:
            weight_series, planned_turnover, scale = _apply_turnover_limit(
                weight_series, prev_weights_row, turnover_limit
            )
            if scale < 1.0:
                turnover_limited += 1
                turnover_scale_sum += scale
            cash_weight_sum += max(0.0, 1.0 - float(weight_series.sum()))
        for symbol, weight in weight_series.items():
            if weight <= 0:
                continue
            score_value = ""
            if signal_mode_used == "ml_scores":
                score_value = (
                    f"{selected_scores.get(symbol, 0.0):.6f}"
                    if symbol in selected_scores
                    else ""
                )
            weight_rows.append(
                {
                    "symbol": symbol,
                    "snapshot_date": snapshot_date.isoformat(),
                    "rebalance_date": rebalance.isoformat(),
                    "signal_mode": signal_mode_used,
                    "weight": f"{weight:.8f}",
                    "score": score_value,
                }
            )
        start_idx = prices.index.get_loc(pd.Timestamp(rebalance))
        end_idx = (
            prices.index.get_loc(pd.Timestamp(rebalance_dates[idx + 1]))
            if idx + 1 < len(rebalance_dates)
            else len(prices.index)
        )
        weights.iloc[start_idx:end_idx] = weight_series
        prev_weights_row = weight_series

    portfolio_returns = (weights * returns).sum(axis=1)
    turnover_by_date: dict[str, float] = {}
    if cost_rate > 0 and rebalance_dates:
        prev_weights = pd.Series(0.0, index=weights.columns)
        for rebalance in rebalance_dates:
            ts = pd.Timestamp(rebalance)
            if ts not in weights.index:
                continue
            new_weights = weights.loc[ts].fillna(0.0)
            delta = new_weights - prev_weights
            trade_notional = float(delta.clip(lower=0.0).sum())
            if trade_notional > 0:
                portfolio_returns.loc[ts] -= trade_notional * cost_rate
            turnover_by_date[rebalance.isoformat()] = trade_notional
            prev_weights = new_weights
    portfolio_equity = (1 + portfolio_returns).cumprod()

    benchmark_symbol = resolve_symbol_alias(benchmark.upper(), None, symbol_map)
    benchmark_path, benchmark_mode, _ = resolve_symbol_path(benchmark.upper(), benchmark_symbol)
    if benchmark_symbol not in prices.columns and benchmark_path and benchmark_path.exists():
        bench_df = pd.read_csv(benchmark_path)
        bench_column_map = {col.lower(): col for col in bench_df.columns}
        bench_date_col = bench_column_map.get("date")
        bench_price_col = bench_column_map.get(trade_price_mode)
        if bench_date_col and bench_price_col:
            bench_df = bench_df[[bench_date_col, bench_price_col]].rename(
                columns={bench_date_col: "date", bench_price_col: benchmark_symbol}
            )
            bench_df["date"] = pd.to_datetime(bench_df["date"], utc=True).dt.tz_convert(None)
            bench_series = bench_df.set_index("date")[benchmark_symbol].sort_index()
            bench_series = bench_series.reindex(portfolio_equity.index).ffill()
        else:
            bench_series = None
    else:
        bench_series = trade_prices.get(benchmark_symbol)
        if bench_series is not None:
            bench_series = bench_series.reindex(portfolio_equity.index).ffill()
    if bench_series is None:
        bench_series = portfolio_equity.copy()
    benchmark_returns = bench_series.shift(-1) / bench_series - 1
    benchmark_equity = (1 + benchmark_returns.fillna(0.0)).cumprod()

    equity_window = pd.DataFrame(
        {"portfolio": portfolio_equity, "benchmark": benchmark_equity}
    )
    if backtest_start:
        equity_window = equity_window.loc[equity_window.index >= pd.Timestamp(backtest_start)]
    if backtest_end:
        equity_window = equity_window.loc[equity_window.index <= pd.Timestamp(backtest_end)]
    if equity_window.empty:
        equity_window = pd.DataFrame(
            {"portfolio": portfolio_equity, "benchmark": benchmark_equity}
        )

    ensure_dir(out_dir)
    equity_path = out_dir / "equity_curve.csv"
    equity_df = pd.DataFrame(
        {
            "date": equity_window.index,
            "portfolio": equity_window["portfolio"].values,
            "benchmark": equity_window["benchmark"].values,
        }
    )
    equity_df.to_csv(equity_path, index=False, encoding="utf-8")

    price_mode = "raw"
    if used_modes == {"adjusted"}:
        price_mode = "adjusted"
    elif used_modes and "adjusted" in used_modes:
        price_mode = "mixed"
    rebalance_label = "weekly" if pit_used or rebalance_cfg == "W" else "monthly"
    summary = {
        "portfolio": calc_metrics(equity_window["portfolio"], risk_free),
        "benchmark": calc_metrics(equity_window["benchmark"], risk_free),
        "start": str(equity_window.index[0].date()),
        "end": str(equity_window.index[-1].date()),
        "benchmark_symbol": benchmark_symbol,
        "price_mode": price_mode,
        "benchmark_mode": benchmark_mode if benchmark_mode else price_mode,
        "trade_price": trade_price_mode,
        "open_fallback_count": len(open_missing),
        "signal_mode": signal_mode,
        "score_csv_path": str(score_path) if signal_mode == "ml_scores" else "",
        "score_top_n": score_top_n,
        "score_weighting": score_weighting,
        "score_min": score_min if score_min is not None else "",
        "score_max_weight": score_max_weight if score_max_weight is not None else "",
        "score_fallback": score_fallback,
        "score_delay_days": score_delay_days,
        "score_smoothing": score_smoothing_method if score_smoothing_enabled else "",
        "score_smoothing_alpha": score_smoothing_alpha if score_smoothing_enabled else "",
        "score_smoothing_carry": score_smoothing_carry if score_smoothing_enabled else "",
        "score_retain_top_n": score_retain_top_n if score_retain_top_n else "",
        "weight_smoothing_alpha": weight_smoothing_alpha if weight_smoothing_enabled else "",
        "backtest_start": backtest_start.isoformat() if backtest_start else "",
        "backtest_end": backtest_end.isoformat() if backtest_end else "",
        "asset_type_filter": sorted(allowed_asset_types) if allowed_asset_types else "",
        "pit_universe_only": pit_universe_only,
        "price_source_policy": price_source_policy,
        "price_source_counts": price_source_counts,
        "missing_adjusted_count": len(missing_adjusted),
        "exclude_symbols_path": str(exclude_path) if exclude_symbols else "",
        "exclude_symbols_count": len(exclude_symbols),
        "symbol_life_override_path": str(override_path) if symbol_life_overrides else "",
        "symbol_life_override_count": len(symbol_life_overrides),
        "rebalance": rebalance_label,
        "rebalance_mode": rebalance_mode,
        "pit_weekly": pit_used,
        "min_history_days": min_history_days,
        "min_price": min_price,
        "min_avg_volume": min_avg_volume,
        "min_avg_dollar_volume": min_avg_dollar_volume,
        "liquidity_window_days": liquidity_window_days,
        "halt_volume_threshold": halt_volume_threshold,
        "record_universe": record_universe,
        "market_filter": market_filter,
        "market_ma_window": market_ma_window,
        "risk_off_mode": risk_off_mode,
        "max_exposure": max_exposure,
        "risk_off_count": risk_off_count,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "impact_bps": impact_bps,
        "total_cost_bps": total_cost_bps,
        "max_holdings": max_holdings,
        "max_position_weight": max_position_weight if max_position_weight is not None else "",
        "turnover_limit": turnover_limit if turnover_limit is not None else "",
        "trade_weekdays": sorted(allowed_weekdays) if allowed_weekdays else "",
        "trade_day_policy": trade_day_policy,
        "trade_day_max_shift_days": max_shift_days if max_shift_days is not None else "",
        "trade_day_shifted": trade_day_shifted,
        "trade_day_skipped": trade_day_skipped,
        "turnover_limited_count": turnover_limited,
        "turnover_limit_avg_scale": (
            turnover_scale_sum / turnover_limited if turnover_limited else 1.0
        ),
        "cash_weight_avg": (
            cash_weight_sum / len(rebalance_dates) if rebalance_dates else 0.0
        ),
        "max_holdings_trimmed": max_holdings_trimmed,
        "turnover_avg": (
            sum(turnover_by_date.values()) / len(turnover_by_date)
            if turnover_by_date
            else 0.0
        ),
    }
    if missing_adjusted:
        missing_path = out_dir / "missing_adjusted.csv"
        write_csv(missing_path, [{"symbol": s} for s in missing_adjusted], ["symbol"])
        summary["missing_adjusted_path"] = str(missing_path)
    if record_universe and universe_dir:
        active_path = universe_dir / "universe_active.csv"
        excluded_path = universe_dir / "universe_excluded.csv"
        write_csv(
            active_path,
            universe_records,
            ["symbol", "snapshot_date", "rebalance_date"],
        )
        write_csv(
            excluded_path,
            universe_excluded,
            ["symbol", "snapshot_date", "rebalance_date", "reason", "snapshot_price"],
        )
        summary["universe_active_path"] = str(active_path)
        summary["universe_excluded_path"] = str(excluded_path)
        summary["filter_counts"] = filter_counts
    if signal_rows:
        signals_path = out_dir / "signals.csv"
        write_csv(
            signals_path,
            signal_rows,
            ["symbol", "snapshot_date", "rebalance_date", "signal_mode", "score_date", "score"],
        )
        summary["signals_path"] = str(signals_path)
        summary["signals_count"] = len(signal_rows)
    if weight_rows:
        weights_path = out_dir / "weights.csv"
        write_csv(
            weights_path,
            weight_rows,
            ["symbol", "snapshot_date", "rebalance_date", "signal_mode", "weight", "score"],
        )
        summary["weights_path"] = str(weights_path)
        summary["weights_count"] = len(weight_rows)
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
    refresh_theme_cmd = sub.add_parser("refresh-theme-manuals")
    refresh_theme_cmd.add_argument(
        "--keys",
        type=str,
        default="AI_CORE,AI_INFRA,ENERGY_FUSION",
        help="更新的主题组合（逗号分隔）",
    )
    refresh_theme_cmd.add_argument(
        "--limit",
        type=int,
        default=0,
        help="每个主题保留的最大成分数（0 代表使用配置默认值）",
    )

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
    elif args.command == "refresh-theme-manuals":
        keys = [key.strip().upper() for key in args.keys.split(",") if key.strip()]
        updated = refresh_theme_manuals(config_path, keys, args.limit)
        for key, symbols in updated.items():
            print(f"{key}: {len(symbols)} symbols")
        print(f"Theme config updated: {config_path}")

    elif args.command == "backtest":
        universe_path = data_root / "universe" / "universe.csv"
        if not universe_path.exists():
            raise SystemExit("请先运行 build-universe")
        summary_path = run_backtest(data_root, universe_path, weights_path)
        print(f"Backtest summary: {summary_path}")


if __name__ == "__main__":
    main()
