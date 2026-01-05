#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'").strip('"')
    return env


def get_data_root(project_root: Path) -> Path:
    env_path = project_root / "backend" / ".env"
    env = load_env(env_path)
    data_root = env.get("DATA_ROOT")
    if not data_root:
        raise SystemExit("DATA_ROOT is not set in backend/.env")
    return Path(data_root).resolve()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def parse_data_symbols(curated_dir: Path) -> set[str]:
    symbols: set[str] = set()
    if not curated_dir.exists():
        return symbols
    for file in curated_dir.glob("*.csv"):
        parts = file.stem.split("_")
        if len(parts) < 4:
            continue
        symbol_parts = parts[2:-1]
        if not symbol_parts:
            continue
        symbol = "_".join(symbol_parts).strip().upper()
        if symbol:
            symbols.add(symbol)
    return symbols


def classify_action(symbol: str, name: str) -> tuple[str, str]:
    name_lower = (name or "").lower()
    if " " in symbol:
        return "exclude", "nonstandard_symbol"
    keywords = [
        "warrant",
        "warrants",
        "unit",
        "units",
        "right",
        "rights",
        "preferred",
        "depositary",
        "contingent value",
        "cvrs",
        "preference",
    ]
    if any(keyword in name_lower for keyword in keywords):
        return "exclude", "non_common_security"
    if "-" in symbol and symbol.endswith(("W", "WS", "WT", "WTS", "U", "RT")):
        return "exclude", "unit_warrant_suffix"
    if re.search(r"[^A-Z0-9_-]", symbol):
        return "manual_map", "nonstandard_symbol"
    return "fetch", "missing_data"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, default="", help="输出路径")
    parser.add_argument(
        "--listing",
        type=str,
        default="",
        help="Alpha listing 路径（默认 data_root/universe/alpha_symbol_life.csv）",
    )
    parser.add_argument(
        "--curated-dir",
        type=str,
        default="",
        help="行情数据目录（默认 data_root/curated_adjusted）",
    )
    parser.add_argument(
        "--symbol-map",
        type=str,
        default="",
        help="symbol_map 路径（默认 data_root/universe/symbol_map.csv）",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    data_root = get_data_root(project_root)
    listing_path = (
        Path(args.listing).expanduser().resolve()
        if args.listing
        else data_root / "universe" / "alpha_symbol_life.csv"
    )
    curated_dir = (
        Path(args.curated_dir).expanduser().resolve()
        if args.curated_dir
        else data_root / "curated_adjusted"
    )
    symbol_map_path = (
        Path(args.symbol_map).expanduser().resolve()
        if args.symbol_map
        else data_root / "universe" / "symbol_map.csv"
    )
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else data_root / "universe" / "missing_symbol_actions.csv"
    )

    data_symbols = parse_data_symbols(curated_dir)
    map_rows = read_csv(symbol_map_path)
    map_dict = {
        (row.get("symbol") or "").strip().upper(): (row.get("canonical") or "").strip().upper()
        for row in map_rows
        if (row.get("symbol") or "").strip() and (row.get("canonical") or "").strip()
    }

    listing_rows = read_csv(listing_path)
    actions: list[dict[str, str]] = []
    counts = {"fetch": 0, "exclude": 0, "manual_map": 0}
    for row in listing_rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        canonical = map_dict.get(symbol, symbol)
        if canonical in data_symbols:
            continue
        action, reason = classify_action(symbol, row.get("name") or "")
        counts[action] += 1
        actions.append(
            {
                "symbol": symbol,
                "canonical": canonical,
                "asset_type": row.get("assetType") or "",
                "name": row.get("name") or "",
                "action": action,
                "reason": reason,
                "note": row.get("status") or "",
            }
        )

    actions.sort(key=lambda item: (item["action"], item["symbol"]))
    write_csv(
        output_path,
        actions,
        ["symbol", "canonical", "asset_type", "name", "action", "reason", "note"],
    )
    print(f"Missing symbol actions saved: {output_path}")
    print(f"Total: {len(actions)}")
    for key in ("fetch", "exclude", "manual_map"):
        print(f"{key}: {counts[key]}")


if __name__ == "__main__":
    main()
