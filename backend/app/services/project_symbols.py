from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from app.models import Project
from app.routes.projects import (
    _build_symbol_type_index,
    _build_theme_index,
    _get_data_root,
    _resolve_project_config,
    _resolve_theme_memberships,
    _safe_read_csv,
)


def _extract_asset_type_filter(config: dict) -> set[str]:
    asset_types = config.get("asset_types")
    if not asset_types and isinstance(config.get("universe"), dict):
        asset_types = config.get("universe", {}).get("asset_types")
    if not asset_types:
        return set()
    if isinstance(asset_types, str):
        items = [asset_types]
    elif isinstance(asset_types, (list, tuple, set)):
        items = asset_types
    else:
        return set()
    return {str(item).strip().upper() for item in items if str(item).strip()}


def _build_theme_weight_index(config: dict) -> dict[str, float]:
    weights: dict[str, float] = {}
    themes = config.get("themes") or []
    if themes:
        for item in themes:
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            raw_weight = item.get("weight")
            if raw_weight is None:
                continue
            try:
                weights[key] = float(raw_weight)
            except (TypeError, ValueError):
                continue
    else:
        for key, raw_weight in (config.get("weights") or {}).items():
            key = str(key).strip()
            if not key:
                continue
            try:
                weights[key] = float(raw_weight)
            except (TypeError, ValueError):
                continue
    return weights


def collect_project_symbols(config: dict) -> list[str]:
    theme_index = _build_theme_index(config)
    if not theme_index:
        return []
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    resolved = _resolve_theme_memberships(rows, theme_index)
    asset_filter = _extract_asset_type_filter(config)
    symbol_types = _build_symbol_type_index(rows, config) if asset_filter else {}
    weights = _build_theme_weight_index(config)
    has_weights = bool(weights)
    symbols: set[str] = set()
    for key in theme_index.keys():
        weight = weights.get(key)
        if has_weights and weight is not None and weight <= 0:
            continue
        for symbol in resolved.get(key, set()):
            if asset_filter and symbol_types.get(symbol, "UNKNOWN") not in asset_filter:
                continue
            symbols.add(symbol)
    return sorted(symbols)


def collect_project_theme_map(config: dict) -> tuple[dict[str, str], dict[str, float]]:
    theme_index = _build_theme_index(config)
    if not theme_index:
        return {}, {}
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    resolved = _resolve_theme_memberships(rows, theme_index)
    asset_filter = _extract_asset_type_filter(config)
    symbol_types = _build_symbol_type_index(rows, config) if asset_filter else {}
    symbol_theme_map: dict[str, str] = {}
    for key, symbols in resolved.items():
        for symbol in symbols:
            if not symbol:
                continue
            symbol_text = str(symbol).strip().upper()
            if asset_filter and symbol_types.get(symbol_text, "UNKNOWN") not in asset_filter:
                continue
            symbol_theme_map[symbol_text] = str(key).strip().upper()
    theme_weights = _build_theme_weight_index(config)
    normalized_weights = {
        str(key).strip().upper(): float(weight)
        for key, weight in theme_weights.items()
        if str(key).strip()
    }
    return symbol_theme_map, normalized_weights


def collect_active_project_symbols(session) -> tuple[list[str], list[str]]:
    projects = session.query(Project).filter(Project.is_archived.is_(False)).all()
    symbols: set[str] = set()
    benchmarks: set[str] = set()
    for project in projects:
        config = _resolve_project_config(session, project.id)
        symbols.update(collect_project_symbols(config))
        benchmark = str(config.get("benchmark") or "SPY").strip().upper()
        if benchmark:
            benchmarks.add(benchmark)
    symbols.update(benchmarks)
    return sorted(symbols), sorted(benchmarks)


def write_symbol_list(path: Path, symbols: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol"])
        for symbol in symbols:
            symbol = str(symbol).strip().upper()
            if symbol:
                writer.writerow([symbol])
    tmp_path.replace(path)
