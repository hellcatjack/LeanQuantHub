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


def load_listing_symbols(path: Path) -> set[str]:
    rows = read_csv(path)
    symbols: set[str] = set()
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if symbol:
            symbols.add(symbol)
    return symbols


def build_symbol_map(
    listing_symbols: set[str],
    data_symbols: set[str],
    existing_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    existing_aliases = {row.get("symbol", "").strip().upper() for row in existing_rows}
    auto_rows: list[dict[str, str]] = []
    stats = {
        "hyphen_to_underscore": 0,
        "dot_to_underscore": 0,
        "normalized_match": 0,
    }
    normalized_map: dict[str, set[str]] = {}
    for symbol in data_symbols:
        normalized = re.sub(r"[^A-Z0-9]", "", symbol)
        if not normalized:
            continue
        normalized_map.setdefault(normalized, set()).add(symbol)
    for symbol in sorted(listing_symbols):
        if symbol in data_symbols:
            continue
        if symbol in existing_aliases:
            continue
        if "-" in symbol:
            candidate = symbol.replace("-", "_")
            if candidate in data_symbols:
                auto_rows.append(
                    {
                        "symbol": symbol,
                        "canonical": candidate,
                        "start_date": "",
                        "end_date": "",
                        "source": "auto",
                        "note": "hyphen_to_underscore",
                    }
                )
                stats["hyphen_to_underscore"] += 1
                continue
        if "." in symbol:
            candidate = symbol.replace(".", "_")
            if candidate in data_symbols:
                auto_rows.append(
                    {
                        "symbol": symbol,
                        "canonical": candidate,
                        "start_date": "",
                        "end_date": "",
                        "source": "auto",
                        "note": "dot_to_underscore",
                    }
                )
                stats["dot_to_underscore"] += 1
                continue
        normalized = re.sub(r"[^A-Z0-9]", "", symbol)
        candidates = normalized_map.get(normalized, set())
        if len(candidates) == 1:
            candidate = next(iter(candidates))
            if candidate != symbol:
                auto_rows.append(
                    {
                        "symbol": symbol,
                        "canonical": candidate,
                        "start_date": "",
                        "end_date": "",
                        "source": "auto",
                        "note": "normalized_match",
                    }
                )
                stats["normalized_match"] += 1
    merged = existing_rows + auto_rows
    return merged, stats


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
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else data_root / "universe" / "symbol_map.csv"
    )

    listing_symbols = load_listing_symbols(listing_path)
    data_symbols = parse_data_symbols(curated_dir)
    existing_rows = read_csv(output_path)
    merged, stats = build_symbol_map(listing_symbols, data_symbols, existing_rows)
    write_csv(
        output_path,
        merged,
        ["symbol", "canonical", "start_date", "end_date", "source", "note"],
    )
    print(f"Symbol map saved: {output_path}")
    print(f"Auto mappings: {sum(stats.values())}")
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
