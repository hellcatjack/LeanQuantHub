from __future__ import annotations

import csv
import difflib
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.config import settings
from app.db import get_session
from app.models import (
    Algorithm,
    AlgorithmVersion,
    BacktestRun,
    Project,
    ProjectAlgorithmBinding,
    ProjectSystemThemeBinding,
    ProjectVersion,
)
from app.schemas import (
    BacktestOut,
    ProjectConfigCreate,
    ProjectConfigOut,
    ProjectAlgorithmBindCreate,
    ProjectAlgorithmBindOut,
    ProjectDataRefreshRequest,
    ProjectDataRefreshOut,
    ProjectDataStatusOut,
    ProjectDiffOut,
    ProjectCreate,
    ProjectOut,
    ProjectPageOut,
    ProjectVersionCreate,
    ProjectVersionOut,
    ProjectVersionPageOut,
    ProjectThematicBacktestOut,
    ProjectThemeSummaryOut,
    ProjectThemeSymbolsOut,
    ProjectThemeSearchOut,
)
from app.services.audit_log import record_audit

router = APIRouter(prefix="/api/projects", tags=["projects"])

MAX_PAGE_SIZE = 200
PROJECT_CONFIG_TAG = "project_config"
PROJECT_BACKTEST_TAG = "thematic_backtest"
CSV_ENCODING = "utf-8-sig"


def _get_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.environ.get("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("C:/work/stocks/data")


def _safe_read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


def _load_default_config(session=None) -> dict[str, Any]:
    base_dir = Path(__file__).resolve().parents[3]
    weights_path = base_dir / "configs" / "portfolio_weights.json"
    categories: list[dict[str, str]] = []
    theme_items: list[dict[str, Any]] = []
    default_key = "SP500_CURRENT"
    default_label = "S&P500现有成分"
    if session is None:
        categories.append({"key": default_key, "label": default_label})
        theme_items.append(
            {
                "key": default_key,
                "label": default_label,
                "keywords": [],
                "manual": [],
                "exclude": [],
            }
        )
    else:
        from app.routes import system_themes as system_theme_routes
        from app.models import SystemTheme

        system_theme_routes._ensure_system_themes(session)
        theme = (
            session.query(SystemTheme)
            .filter(SystemTheme.key == default_key)
            .first()
        )
        if theme:
            latest = system_theme_routes._get_latest_version(session, theme.id)
            base_payload = latest.payload if latest and latest.payload else {}
            system_base = system_theme_routes._build_system_base(base_payload)
            label = system_base.get("label") or theme.label or default_label
            categories.append({"key": default_key, "label": label})
            theme_items.append(
                {
                    "key": default_key,
                    "label": label,
                    "weight": 1.0,
                    "keywords": [],
                    "manual": [],
                    "exclude": [],
                    "system": {
                        "theme_id": theme.id,
                        "version_id": latest.id if latest else None,
                        "version": latest.version if latest else None,
                        "source": theme.source,
                        "mode": "follow_latest",
                    },
                    "system_base": system_base,
                }
            )
        else:
            categories.append({"key": default_key, "label": default_label})
            theme_items.append(
                {
                    "key": default_key,
                    "label": default_label,
                    "keywords": [],
                    "manual": [],
                    "exclude": [],
                }
            )
    weights: dict[str, float] = {}
    benchmark = "SPY"
    rebalance = "M"
    risk_free_rate = 0.0
    if weights_path.exists():
        try:
            weight_data = json.loads(weights_path.read_text(encoding="utf-8"))
            weights = weight_data.get("category_weights", {}) or {}
            benchmark = weight_data.get("benchmark", benchmark)
            rebalance = weight_data.get("rebalance", rebalance)
            risk_free_rate = float(weight_data.get("risk_free_rate", risk_free_rate))
        except json.JSONDecodeError:
            pass
    sp500_weight = float(weights.get(default_key, 1.0))
    if len(theme_items) == 1:
        sp500_weight = 1.0
    weights = {default_key: sp500_weight}
    for item in theme_items:
        key = str(item.get("key", "")).strip()
        item["weight"] = float(weights.get(key, 0.0)) if key else 0.0
    return {
        "template": "sp500_current",
        "universe": {"mode": "sp500_current", "include_history": False},
        "data": {"primary_vendor": "alpha", "fallback_vendor": "alpha", "frequency": "daily"},
        "weights": weights,
        "benchmark": benchmark,
        "rebalance": rebalance,
        "risk_free_rate": risk_free_rate,
        "categories": categories,
        "themes": theme_items,
    }


def _load_theme_defaults() -> dict[str, Any]:
    base_dir = Path(__file__).resolve().parents[3]
    theme_path = base_dir / "configs" / "theme_keywords.json"
    if not theme_path.exists():
        return {"categories": [], "defaults": {"region": "US", "asset_class": "Equity"}, "yahoo": {}}
    try:
        return json.loads(theme_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"categories": [], "defaults": {"region": "US", "asset_class": "Equity"}, "yahoo": {}}


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _build_theme_config(config: dict[str, Any]) -> dict[str, Any]:
    base_theme = _load_theme_defaults()
    base_categories = {
        str(item.get("key", "")).strip(): item for item in base_theme.get("categories", [])
    }
    defaults = base_theme.get("defaults") or {"region": "US", "asset_class": "Equity"}
    yahoo_cfg = base_theme.get("yahoo") or {}

    themes = config.get("themes") or []
    categories = config.get("categories") or []
    result_categories: list[dict[str, Any]] = []

    if themes:
        theme_items = themes
    elif categories:
        theme_items = categories
    else:
        theme_items = base_theme.get("categories", [])

    for item in theme_items:
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        base_item = base_categories.get(key, {})
        system_base = item.get("system_base") if isinstance(item.get("system_base"), dict) else {}
        has_system = bool(item.get("system") or system_base)
        label = str(
            system_base.get("label") or item.get("label") or base_item.get("label") or key
        ).strip()
        if has_system:
            keywords = _coerce_list(system_base.get("keywords") or base_item.get("keywords"))
            base_manual = _coerce_list(system_base.get("manual"))
            base_exclude = _coerce_list(system_base.get("exclude"))
            override_manual = _coerce_list(item.get("manual"))
            override_exclude = _coerce_list(item.get("exclude"))
            manual = sorted(set(base_manual + override_manual))
            exclude = sorted(set(base_exclude + override_exclude))
        else:
            keywords = _coerce_list(item.get("keywords") or base_item.get("keywords"))
            manual = _coerce_list(item.get("manual") or base_item.get("manual"))
            exclude = _coerce_list(item.get("exclude") or base_item.get("exclude"))
        priority = _coerce_int(item.get("priority") or base_item.get("priority") or 0)
        result_categories.append(
            {
                "key": key,
                "label": label or key,
                "keywords": keywords,
                "manual": manual,
                "exclude": exclude,
                "priority": priority,
            }
        )

    return {
        "categories": result_categories,
        "defaults": defaults,
        "yahoo": yahoo_cfg,
        "symbol_types": config.get("symbol_types") or base_theme.get("symbol_types") or {},
    }


def _build_weights_config(config: dict[str, Any]) -> dict[str, Any]:
    weights: dict[str, float] = {}
    themes = config.get("themes") or []
    if themes:
        for item in themes:
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            weight = float(item.get("weight") or 0.0)
            weights[key] = weight
    else:
        weights = {str(k): float(v) for k, v in (config.get("weights") or {}).items()}
    return {
        "benchmark": config.get("benchmark") or "SPY",
        "rebalance": config.get("rebalance") or "M",
        "risk_free_rate": float(config.get("risk_free_rate") or 0.0),
        "category_weights": weights,
    }


def _write_project_config_files(project_id: int, config: dict[str, Any]) -> tuple[Path, Path]:
    output_dir = Path(settings.artifact_root) / f"project_{project_id}" / "config"
    output_dir.mkdir(parents=True, exist_ok=True)
    theme_path = output_dir / "theme_config.json"
    weights_path = output_dir / "weights_config.json"
    theme_payload = _build_theme_config(config)
    weights_payload = _build_weights_config(config)
    theme_path.write_text(
        json.dumps(theme_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    weights_path.write_text(
        json.dumps(weights_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return theme_path, weights_path


def _resolve_project_config(session, project_id: int) -> dict[str, Any]:
    version = _get_latest_version(session, project_id, PROJECT_CONFIG_TAG)
    if version and version.content:
        try:
            config = json.loads(version.content)
            if isinstance(config, dict) and config:
                return config
        except json.JSONDecodeError:
            pass
    return _load_default_config(session)


def _get_latest_version(
    session, project_id: int, description: str
) -> ProjectVersion | None:
    return (
        session.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project_id,
            ProjectVersion.description == description,
        )
        .order_by(ProjectVersion.created_at.desc())
        .first()
    )


def _save_project_version(
    session,
    project_id: int,
    description: str,
    content: str,
    version: str | None = None,
) -> ProjectVersion:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version_obj = ProjectVersion(
        project_id=project_id,
        version=version,
        description=description,
        content=content,
        content_hash=content_hash,
    )
    session.add(version_obj)
    session.commit()
    session.refresh(version_obj)
    return version_obj


def _sync_system_theme_bindings(
    session, project_id: int, config: dict[str, Any]
) -> None:
    themes = config.get("themes") or []
    active_ids: set[int] = set()
    for item in themes:
        system_meta = item.get("system") or {}
        theme_id = system_meta.get("theme_id")
        version_id = system_meta.get("version_id")
        mode = system_meta.get("mode") or "follow_latest"
        if not theme_id or not version_id:
            continue
        active_ids.add(theme_id)
        binding = (
            session.query(ProjectSystemThemeBinding)
            .filter(
                ProjectSystemThemeBinding.project_id == project_id,
                ProjectSystemThemeBinding.theme_id == theme_id,
            )
            .first()
        )
        if not binding:
            binding = ProjectSystemThemeBinding(
                project_id=project_id,
                theme_id=theme_id,
                version_id=version_id,
                mode=mode,
            )
            session.add(binding)
        else:
            binding.version_id = version_id
            binding.mode = mode
    bindings = (
        session.query(ProjectSystemThemeBinding)
        .filter(ProjectSystemThemeBinding.project_id == project_id)
        .all()
    )
    for binding in bindings:
        if binding.theme_id not in active_ids:
            session.delete(binding)


def _collect_data_status(project_id: int) -> dict[str, Any]:
    data_root = _get_data_root()
    universe_dir = data_root / "universe"
    universe_path = universe_dir / "universe.csv"
    membership_path = universe_dir / "sp500_membership.csv"
    themes_path = universe_dir / "themes.csv"
    metrics_path = data_root / "metrics" / "yahoo_quotes.csv"
    price_root = data_root / "prices"
    stooq_dir = price_root / "stooq"
    yahoo_dir = price_root / "yahoo"
    backtest_summary = data_root / "backtest" / "thematic" / "summary.json"

    membership_rows = _safe_read_csv(membership_path)
    membership_symbols = {row.get("symbol", "").strip() for row in membership_rows if row.get("symbol")}
    membership_start = None
    membership_end = None
    for row in membership_rows:
        start = _parse_date(row.get("start_date"))
        end = _parse_date(row.get("end_date"))
        if start and (membership_start is None or start < membership_start):
            membership_start = start
        if end and (membership_end is None or end > membership_end):
            membership_end = end

    universe_rows = _safe_read_csv(universe_path)
    sp500_count = sum(1 for row in universe_rows if row.get("in_sp500_history") == "1")
    theme_count = sum(1 for row in universe_rows if row.get("category", "").startswith("AI") or row.get("category") == "ENERGY_FUSION")

    theme_rows = _safe_read_csv(themes_path)
    theme_categories = sorted(
        {row.get("category", "").strip() for row in theme_rows if row.get("category")}
    )

    metrics_rows = _safe_read_csv(metrics_path)

    stooq_files = list(stooq_dir.glob("*.csv")) if stooq_dir.exists() else []
    yahoo_files = list(yahoo_dir.glob("*.csv")) if yahoo_dir.exists() else []
    price_mtimes = [
        file.stat().st_mtime for file in (stooq_files + yahoo_files) if file.exists()
    ]
    price_last_update = (
        datetime.fromtimestamp(max(price_mtimes)).isoformat() if price_mtimes else None
    )

    backtest_payload = None
    if backtest_summary.exists():
        try:
            backtest_payload = json.loads(backtest_summary.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backtest_payload = None

    return {
        "project_id": project_id,
        "data_root": str(data_root),
        "membership": {
            "records": len(membership_rows),
            "symbols": len(membership_symbols),
            "start": membership_start.date().isoformat() if membership_start else None,
            "end": membership_end.date().isoformat() if membership_end else None,
            "updated_at": _format_mtime(membership_path),
        },
        "universe": {
            "records": len(universe_rows),
            "sp500_count": sp500_count,
            "theme_count": theme_count,
            "updated_at": _format_mtime(universe_path),
        },
        "themes": {
            "records": len(theme_rows),
            "categories": theme_categories,
            "updated_at": _format_mtime(themes_path),
        },
        "metrics": {
            "records": len(metrics_rows),
            "updated_at": _format_mtime(metrics_path),
        },
        "prices": {
            "stooq_files": len(stooq_files),
            "yahoo_files": len(yahoo_files),
            "updated_at": price_last_update,
        },
        "backtest": {
            "updated_at": _format_mtime(backtest_summary),
            "summary": backtest_payload,
        },
    }


def _build_theme_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    themes = config.get("themes") or []
    if not themes:
        themes = config.get("categories") or []
    index: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(themes):
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        label = str(item.get("label", "")).strip() or key
        manual = [
            str(symbol).strip().upper()
            for symbol in _coerce_list(item.get("manual"))
            if str(symbol).strip()
        ]
        exclude = [
            str(symbol).strip().upper()
            for symbol in _coerce_list(item.get("exclude"))
            if str(symbol).strip()
        ]
        priority = _coerce_int(item.get("priority") or 0)
        index[key] = {
            "label": label,
            "manual_symbols": manual,
            "exclude_symbols": exclude,
            "priority": priority,
            "order": idx,
        }
    return index


def _resolve_theme_memberships(
    rows: list[dict[str, str]], theme_index: dict[str, dict[str, Any]]
) -> dict[str, set[str]]:
    theme_keys = {row.get("category", "").strip() for row in rows if row.get("category", "").strip()}
    theme_keys |= set(theme_index.keys())
    default_order = len(theme_index) + 1000
    resolved: dict[str, set[str]] = {key: set() for key in theme_keys}
    candidates: dict[str, list[dict[str, Any]]] = {}

    def add_candidate(symbol: str, key: str, source_rank: int) -> None:
        meta = theme_index.get(key, {})
        exclude = set(meta.get("exclude_symbols") or [])
        if symbol in exclude:
            return
        candidates.setdefault(symbol, []).append(
            {
                "key": key,
                "priority": meta.get("priority", 0),
                "order": meta.get("order", default_order),
                "source_rank": source_rank,
            }
        )

    for row in rows:
        key = row.get("category", "").strip()
        symbol = row.get("symbol", "").strip().upper()
        if not key or not symbol:
            continue
        add_candidate(symbol, key, 0)

    for key, meta in theme_index.items():
        for symbol in meta.get("manual_symbols") or []:
            if symbol:
                add_candidate(symbol, key, 1)

    def rank(candidate: dict[str, Any]) -> tuple[int, int, int]:
        return (
            int(candidate.get("priority") or 0),
            int(candidate.get("source_rank") or 0),
            -int(candidate.get("order") or default_order),
        )

    for symbol, items in candidates.items():
        winner = max(items, key=rank)
        resolved.setdefault(winner["key"], set()).add(symbol)

    return resolved


def _normalize_security_type(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip().upper()
    if not text:
        return "UNKNOWN"
    mapping = {
        "EQUITY": "STOCK",
        "STOCK": "STOCK",
        "ETF": "ETF",
        "ETN": "ETN",
        "ADR": "ADR",
        "REIT": "REIT",
        "FUND": "FUND",
        "INDEX": "INDEX",
    }
    return mapping.get(text, text)


def _build_symbol_type_index(rows: list[dict[str, str]], config: dict[str, Any]) -> dict[str, str]:
    types: dict[str, str] = {}
    for row in rows:
        symbol = row.get("symbol", "").strip().upper()
        if not symbol:
            continue
        asset_class = row.get("asset_class", "").strip()
        if asset_class:
            types[symbol] = _normalize_security_type(asset_class)
    overrides = config.get("symbol_types") or {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            symbol = str(key).strip().upper()
            if not symbol:
                continue
            types[symbol] = _normalize_security_type(value)
    return types


def _collect_theme_summary(project_id: int, config: dict[str, Any]) -> dict[str, Any]:
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    theme_index = _build_theme_index(config)
    allowed_keys = set(theme_index.keys())
    if not allowed_keys:
        return {
            "project_id": project_id,
            "updated_at": _format_mtime(universe_path),
            "total_symbols": 0,
            "themes": [],
        }
    resolved = _resolve_theme_memberships(rows, theme_index)
    symbol_types = _build_symbol_type_index(rows, config)
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("category", "").strip()
        if not key or key not in allowed_keys:
            continue
        symbol = row.get("symbol", "").strip().upper()
        if not symbol:
            continue
        label = row.get("category_label", "").strip() or theme_index.get(key, {}).get("label") or key
        entry = by_key.setdefault(key, {"label": label, "symbols": []})
        entry["symbols"].append(symbol)

    for key, meta in theme_index.items():
        by_key.setdefault(key, {"label": meta.get("label") or key, "symbols": []})

    ordered_keys = list(theme_index.keys())

    items: list[dict[str, Any]] = []
    total_symbols = 0
    for key in ordered_keys:
        entry = by_key[key]
        manual_symbols = set(theme_index.get(key, {}).get("manual_symbols", []))
        exclude_symbols = set(theme_index.get(key, {}).get("exclude_symbols", []))
        combined = sorted(resolved.get(key, set()))
        total_symbols += len(combined)
        sample_types = {
            symbol: symbol_types.get(symbol, "UNKNOWN") for symbol in combined[:8]
        }
        items.append(
            {
                "key": key,
                "label": entry["label"],
                "symbols": len(combined),
                "sample": combined[:8],
                "sample_types": sample_types,
                "manual_symbols": sorted(manual_symbols),
                "exclude_symbols": sorted(exclude_symbols),
            }
        )

    return {
        "project_id": project_id,
        "updated_at": _format_mtime(universe_path),
        "total_symbols": total_symbols,
        "themes": items,
    }


def _collect_theme_symbols(
    project_id: int, category: str, config: dict[str, Any]
) -> dict[str, Any]:
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    theme_index = _build_theme_index(config)
    allowed_keys = set(theme_index.keys())
    if category not in allowed_keys:
        return {
            "project_id": project_id,
            "category": category,
            "label": None,
            "symbols": [],
            "auto_symbols": [],
            "manual_symbols": [],
            "exclude_symbols": [],
            "symbol_types": {},
        }
    resolved = _resolve_theme_memberships(rows, theme_index)
    auto_symbols = sorted(
        {
            row.get("symbol", "").strip().upper()
            for row in rows
            if row.get("category", "").strip() == category
            and row.get("symbol", "").strip()
        }
    )
    manual_symbols = sorted(set(theme_index.get(category, {}).get("manual_symbols", [])))
    exclude_symbols = sorted(set(theme_index.get(category, {}).get("exclude_symbols", [])))
    combined = sorted(resolved.get(category, set()))
    symbol_types_index = _build_symbol_type_index(rows, config)
    symbol_types = {
        symbol: symbol_types_index.get(symbol, "UNKNOWN")
        for symbol in (set(combined) | set(manual_symbols) | set(exclude_symbols))
    }
    label = None
    for row in rows:
        if row.get("category", "").strip() == category:
            label = row.get("category_label", "").strip() or None
            if label:
                break
    if not label:
        label = theme_index.get(category, {}).get("label")
    return {
        "project_id": project_id,
        "category": category,
        "label": label,
        "symbols": combined,
        "auto_symbols": auto_symbols,
        "manual_symbols": manual_symbols,
        "exclude_symbols": exclude_symbols,
        "symbol_types": symbol_types,
    }


def _collect_theme_search(
    project_id: int, symbol: str, config: dict[str, Any]
) -> dict[str, Any]:
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    theme_index = _build_theme_index(config)
    allowed_keys = set(theme_index.keys())
    target = symbol.strip().upper()
    themes: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("symbol", "").strip().upper() != target:
            continue
        key = row.get("category", "").strip()
        if not key or key not in allowed_keys:
            continue
        label = row.get("category_label", "").strip() or theme_index.get(key, {}).get("label") or key
        themes[key] = {"label": label, "is_manual": False}
    for key, meta in theme_index.items():
        manual_symbols = set(meta.get("manual_symbols") or [])
        if target in manual_symbols:
            entry = themes.setdefault(key, {"label": meta.get("label") or key, "is_manual": True})
            entry["is_manual"] = True
        exclude_symbols = set(meta.get("exclude_symbols") or [])
        if target in exclude_symbols:
            entry = themes.setdefault(key, {"label": meta.get("label") or key})
            entry["is_excluded"] = True
    items = [
        {
            "key": key,
            "label": payload["label"],
            "is_manual": payload.get("is_manual", False),
            "is_excluded": payload.get("is_excluded", False),
        }
        for key, payload in sorted(themes.items())
    ]
    return {"project_id": project_id, "symbol": target, "themes": items}


def _run_pipeline_steps(project_id: int, steps: list[str], config: dict[str, Any]) -> None:
    data_root = _get_data_root()
    base_dir = Path(__file__).resolve().parents[3]
    script_path = base_dir / "scripts" / "universe_pipeline.py"
    if not script_path.exists():
        return
    theme_path, weights_path = _write_project_config_files(project_id, config)
    output_dir = Path(settings.artifact_root) / f"project_{project_id}" / "data_refresh"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"refresh_{int(time.time())}.log"
    with log_path.open("w", encoding="utf-8") as handle:
        for step in steps:
            if step not in {"build-universe", "fetch-metrics", "fetch-prices"}:
                continue
            cmd = [
                sys.executable,
                str(script_path),
                step,
            ]
            subprocess.run(
                cmd,
                cwd=str(base_dir),
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
                env={
                    **os.environ,
                    "DATA_ROOT": str(data_root),
                    "THEME_CONFIG_PATH": str(theme_path),
                    "WEIGHTS_CONFIG_PATH": str(weights_path),
                },
            )


def _run_thematic_backtest(
    project_id: int, config: dict[str, Any]
) -> dict[str, Any] | None:
    data_root = _get_data_root()
    base_dir = Path(__file__).resolve().parents[3]
    script_path = base_dir / "scripts" / "universe_pipeline.py"
    if not script_path.exists():
        return None
    theme_path, weights_path = _write_project_config_files(project_id, config)
    output_dir = Path(settings.artifact_root) / f"project_{project_id}" / "thematic_backtest"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"backtest_{int(time.time())}.log"
    with log_path.open("w", encoding="utf-8") as handle:
        subprocess.run(
            [sys.executable, str(script_path), "backtest"],
            cwd=str(base_dir),
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
            env={
                **os.environ,
                "DATA_ROOT": str(data_root),
                "THEME_CONFIG_PATH": str(theme_path),
                "WEIGHTS_CONFIG_PATH": str(weights_path),
            },
        )
    summary_path = data_root / "backtest" / "thematic" / "summary.json"
    if not summary_path.exists():
        error_message = None
        try:
            log_lines = log_path.read_text(encoding="utf-8").splitlines()
            for line in reversed(log_lines):
                if line.strip():
                    error_message = line.strip()
                    break
        except OSError:
            error_message = None
        return {
            "status": "failed",
            "error": error_message or "backtest_failed",
            "log": log_path.name,
        }
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _run_thematic_backtest_task(project_id: int) -> None:
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        config = _resolve_project_config(session, project_id)
    finally:
        session.close()

    summary = _run_thematic_backtest(project_id, config)
    if not summary:
        return
    try:
        session = SessionLocal()
        project = session.get(Project, project_id)
        if not project:
            return
        content = json.dumps(summary, ensure_ascii=False, indent=2)
        version = _save_project_version(
            session,
            project_id=project_id,
            description=PROJECT_BACKTEST_TAG,
            content=content,
            version=summary.get("end") if isinstance(summary, dict) else None,
        )
        record_audit(
            session,
            action="project.backtest.thematic",
            resource_type="project",
            resource_id=project_id,
            detail={"version_id": version.id},
        )
        session.commit()
    finally:
        session.close()


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("", response_model=list[ProjectOut])
def list_projects():
    with get_session() as session:
        return session.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/page", response_model=ProjectPageOut)
def list_projects_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(Project).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(Project)
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return ProjectPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )

@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate):
    with get_session() as session:
        existing = session.query(Project).filter(Project.name == payload.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="项目名称已存在")
        project = Project(name=payload.name, description=payload.description)
        session.add(project)
        session.commit()
        session.refresh(project)
        record_audit(
            session,
            action="project.create",
            resource_type="project",
            resource_id=project.id,
            detail={"name": project.name},
        )
        session.commit()
        return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return project


@router.get("/{project_id}/backtests", response_model=list[BacktestOut])
def list_project_backtests(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return (
            session.query(BacktestRun)
            .filter(BacktestRun.project_id == project_id)
            .order_by(BacktestRun.created_at.desc())
            .all()
        )


@router.get("/{project_id}/versions", response_model=list[ProjectVersionOut])
def list_project_versions(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return (
            session.query(ProjectVersion)
            .filter(ProjectVersion.project_id == project_id)
            .order_by(ProjectVersion.created_at.desc())
            .all()
        )


@router.get("/{project_id}/versions/page", response_model=ProjectVersionPageOut)
def list_project_versions_page(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        total = (
            session.query(ProjectVersion)
            .filter(ProjectVersion.project_id == project_id)
            .count()
        )
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(ProjectVersion)
            .filter(ProjectVersion.project_id == project_id)
            .order_by(ProjectVersion.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return ProjectVersionPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.post("/{project_id}/versions", response_model=ProjectVersionOut)
def create_project_version(project_id: int, payload: ProjectVersionCreate):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        content = payload.content or project.description or ""
        content_hash = None
        if content:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        version = ProjectVersion(
            project_id=project_id,
            version=payload.version,
            description=payload.description,
            content=content,
            content_hash=content_hash,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        record_audit(
            session,
            action="project.version.create",
            resource_type="project_version",
            resource_id=version.id,
            detail={"project_id": project_id, "version": version.version},
        )
        session.commit()
        return version


@router.get("/{project_id}/diff", response_model=ProjectDiffOut)
def diff_project_versions(
    project_id: int,
    from_id: int = Query(...),
    to_id: int = Query(...),
):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        from_version = session.get(ProjectVersion, from_id)
        to_version = session.get(ProjectVersion, to_id)
        if not from_version or not to_version:
            raise HTTPException(status_code=404, detail="版本不存在")
        if (
            from_version.project_id != project_id
            or to_version.project_id != project_id
        ):
            raise HTTPException(status_code=400, detail="版本不属于该项目")

        before = (from_version.content or "").splitlines()
        after = (to_version.content or "").splitlines()
        diff_lines = difflib.unified_diff(
            before,
            after,
            fromfile=f"version_{from_version.id}",
            tofile=f"version_{to_version.id}",
            lineterm="",
        )
        diff = "\n".join(diff_lines)

        return ProjectDiffOut(
            project_id=project_id,
            from_version_id=from_id,
            to_version_id=to_id,
            diff=diff or "无差异",
        )


@router.get("/{project_id}/algorithm-binding", response_model=ProjectAlgorithmBindOut)
def get_project_algorithm_binding(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        binding = (
            session.query(ProjectAlgorithmBinding)
            .filter(ProjectAlgorithmBinding.project_id == project_id)
            .first()
        )
        if not binding:
            return ProjectAlgorithmBindOut(project_id=project_id, exists=False)
        algo = session.get(Algorithm, binding.algorithm_id)
        algo_version = session.get(AlgorithmVersion, binding.algorithm_version_id)
        return ProjectAlgorithmBindOut(
            project_id=project_id,
            exists=True,
            algorithm_id=binding.algorithm_id,
            algorithm_version_id=binding.algorithm_version_id,
            algorithm_name=algo.name if algo else None,
            algorithm_version=algo_version.version if algo_version else None,
            is_locked=binding.is_locked,
            updated_at=binding.updated_at,
        )


@router.post("/{project_id}/algorithm-binding", response_model=ProjectAlgorithmBindOut)
def set_project_algorithm_binding(project_id: int, payload: ProjectAlgorithmBindCreate):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        algo = session.get(Algorithm, payload.algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        algo_version = session.get(AlgorithmVersion, payload.algorithm_version_id)
        if not algo_version:
            raise HTTPException(status_code=404, detail="算法版本不存在")
        if algo_version.algorithm_id != payload.algorithm_id:
            raise HTTPException(status_code=400, detail="算法版本与算法不匹配")

        binding = (
            session.query(ProjectAlgorithmBinding)
            .filter(ProjectAlgorithmBinding.project_id == project_id)
            .first()
        )
        if not binding:
            binding = ProjectAlgorithmBinding(
                project_id=project_id,
                algorithm_id=payload.algorithm_id,
                algorithm_version_id=payload.algorithm_version_id,
                is_locked=payload.is_locked,
            )
            session.add(binding)
        else:
            binding.algorithm_id = payload.algorithm_id
            binding.algorithm_version_id = payload.algorithm_version_id
            binding.is_locked = payload.is_locked
        session.commit()
        session.refresh(binding)
        record_audit(
            session,
            action="project.algorithm.bind",
            resource_type="project",
            resource_id=project_id,
            detail={
                "algorithm_id": binding.algorithm_id,
                "algorithm_version_id": binding.algorithm_version_id,
            },
        )
        session.commit()
        return ProjectAlgorithmBindOut(
            project_id=project_id,
            exists=True,
            algorithm_id=binding.algorithm_id,
            algorithm_version_id=binding.algorithm_version_id,
            algorithm_name=algo.name,
            algorithm_version=algo_version.version,
            is_locked=binding.is_locked,
            updated_at=binding.updated_at,
        )


@router.get("/{project_id}/config", response_model=ProjectConfigOut)
def get_project_config(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        version = _get_latest_version(session, project_id, PROJECT_CONFIG_TAG)
        if version and version.content:
            try:
                config = json.loads(version.content)
                source = "version"
            except json.JSONDecodeError:
                config = _load_default_config(session)
                source = "default"
            updated_at = version.created_at.isoformat()
            version_id = version.id
        else:
            config = _load_default_config(session)
            source = "default"
            updated_at = None
            version_id = None
        return ProjectConfigOut(
            project_id=project_id,
            config=config,
            source=source,
            updated_at=updated_at,
            version_id=version_id,
        )


@router.post("/{project_id}/config", response_model=ProjectConfigOut)
def save_project_config(project_id: int, payload: ProjectConfigCreate):
    if not isinstance(payload.config, dict) or not payload.config:
        raise HTTPException(status_code=400, detail="配置不能为空")
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        content = json.dumps(payload.config, ensure_ascii=False, indent=2)
        version = _save_project_version(
            session,
            project_id=project_id,
            description=PROJECT_CONFIG_TAG,
            content=content,
            version=payload.version,
        )
        _sync_system_theme_bindings(session, project_id, payload.config)
        record_audit(
            session,
            action="project.config.save",
            resource_type="project",
            resource_id=project_id,
            detail={"version_id": version.id},
        )
        session.commit()
        return ProjectConfigOut(
            project_id=project_id,
            config=payload.config,
            source="version",
            updated_at=version.created_at.isoformat(),
            version_id=version.id,
        )


@router.get("/{project_id}/data-status", response_model=ProjectDataStatusOut)
def get_project_data_status(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
    status = _collect_data_status(project_id)
    return ProjectDataStatusOut(**status)


@router.get("/{project_id}/themes/summary", response_model=ProjectThemeSummaryOut)
def get_project_theme_summary(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="椤圭洰涓嶅瓨鍦?")
        config = _resolve_project_config(session, project_id)
    summary = _collect_theme_summary(project_id, config)
    return ProjectThemeSummaryOut(**summary)


@router.get("/{project_id}/themes/symbols", response_model=ProjectThemeSymbolsOut)
def get_project_theme_symbols(project_id: int, category: str = Query(...)):
    category = category.strip()
    if not category:
        raise HTTPException(status_code=400, detail="主题分类不能为空")
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="椤圭洰涓嶅瓨鍦?")
        config = _resolve_project_config(session, project_id)
    payload = _collect_theme_symbols(project_id, category, config)
    return ProjectThemeSymbolsOut(**payload)


@router.get("/{project_id}/themes/search", response_model=ProjectThemeSearchOut)
def search_project_theme_symbol(project_id: int, symbol: str = Query(...)):
    symbol = symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="股票代码不能为空")
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        config = _resolve_project_config(session, project_id)
    payload = _collect_theme_search(project_id, symbol, config)
    return ProjectThemeSearchOut(**payload)


@router.post("/{project_id}/actions/refresh-data", response_model=ProjectDataRefreshOut)
def refresh_project_data(
    project_id: int, payload: ProjectDataRefreshRequest, background_tasks: BackgroundTasks
):
    steps = payload.steps or ["build-universe", "fetch-metrics", "fetch-prices"]
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        config = _resolve_project_config(session, project_id)
        record_audit(
            session,
            action="project.data.refresh",
            resource_type="project",
            resource_id=project_id,
            detail={"steps": steps},
        )
        session.commit()
    background_tasks.add_task(_run_pipeline_steps, project_id, steps, config)
    return ProjectDataRefreshOut(
        project_id=project_id,
        steps=steps,
        status="queued",
    )


@router.get("/{project_id}/thematic-backtest", response_model=ProjectThematicBacktestOut)
def get_project_thematic_backtest(project_id: int):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        version = _get_latest_version(session, project_id, PROJECT_BACKTEST_TAG)
        if version and version.content:
            try:
                summary = json.loads(version.content)
            except json.JSONDecodeError:
                summary = None
            if not summary:
                status = "invalid"
            elif isinstance(summary, dict) and (
                summary.get("status") == "failed" or summary.get("error")
            ):
                status = "failed"
            else:
                status = "ready"
            return ProjectThematicBacktestOut(
                project_id=project_id,
                status=status,
                summary=summary,
                updated_at=version.created_at.isoformat(),
                source="version",
            )
    status = _collect_data_status(project_id)
    summary = status.get("backtest", {}).get("summary")
    updated_at = status.get("backtest", {}).get("updated_at")
    return ProjectThematicBacktestOut(
        project_id=project_id,
        status="ready" if summary else "empty",
        summary=summary,
        updated_at=updated_at,
        source="file" if summary else None,
    )


@router.post(
    "/{project_id}/actions/thematic-backtest",
    response_model=ProjectThematicBacktestOut,
)
def run_project_thematic_backtest(
    project_id: int, background_tasks: BackgroundTasks
):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        record_audit(
            session,
            action="project.backtest.thematic.start",
            resource_type="project",
            resource_id=project_id,
            detail={},
        )
        session.commit()
    background_tasks.add_task(_run_thematic_backtest_task, project_id)
    return ProjectThematicBacktestOut(
        project_id=project_id,
        status="queued",
        summary=None,
        updated_at=None,
        source=None,
    )
