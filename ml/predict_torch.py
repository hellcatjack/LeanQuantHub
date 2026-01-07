from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover - optional dependency
    lgb = None

from feature_engineering import FeatureConfig, compute_features, required_lookback
from pit_features import apply_pit_features, load_pit_fundamentals
from model_io import load_linear_model
from torch_model import TorchMLP


class CancelledError(RuntimeError):
    pass


def _parse_train_start(config: dict) -> pd.Timestamp | None:
    raw_year = config.get("train_start_year")
    if raw_year is not None:
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            year = None
        if year and 1900 <= year <= 2200:
            return pd.Timestamp(year=year, month=1, day=1)
    raw_date = str(config.get("train_start") or "").strip()
    if raw_date:
        try:
            ts = pd.to_datetime(raw_date, errors="raise")
        except (TypeError, ValueError):
            return None
        if ts is not pd.NaT:
            return ts.normalize()
    return None


def _data_root() -> Path:
    env_root = os.environ.get("DATA_ROOT", "")
    if env_root:
        return Path(env_root)
    return Path.cwd() / "data"


def _load_series(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [col.strip().lower() for col in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["close"])
    df = df[~df.index.duplicated(keep="last")]
    return df


def _load_symbol_life(
    data_root: Path, config: dict
) -> dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]]:
    raw_path = str(config.get("symbol_life_path") or "").strip()
    if not raw_path:
        default_path = data_root / "universe" / "alpha_symbol_life.csv"
        if default_path.exists():
            raw_path = str(default_path)
    if not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = data_root / path
    if not path.exists():
        return {}

    df = pd.read_csv(path)
    life: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        ipo_raw = row.get("ipoDate")
        delist_raw = row.get("delistingDate")
        ipo = pd.to_datetime(ipo_raw, errors="coerce") if ipo_raw else None
        delist = pd.to_datetime(delist_raw, errors="coerce") if delist_raw else None
        if ipo is not None and pd.isna(ipo):
            ipo = None
        if delist is not None and pd.isna(delist):
            delist = None
        life[symbol] = (ipo, delist)
    return life


def _apply_symbol_life(
    df: pd.DataFrame, life: tuple[pd.Timestamp | None, pd.Timestamp | None]
) -> pd.DataFrame:
    ipo, delist = life
    if ipo is not None:
        df = df[df.index >= ipo]
    if delist is not None:
        df = df[df.index <= delist]
    return df


def _parse_dataset_name(path: Path) -> tuple[str, str]:
    stem = path.stem
    parts = stem.split("_", 1)
    dataset_name = parts[1] if len(parts) == 2 else stem
    tokens = dataset_name.split("_")
    vendor = tokens[0] if tokens else ""
    symbol = tokens[1] if len(tokens) > 1 else ""
    return vendor, symbol


def _symbol_candidates(symbol: str) -> list[str]:
    raw = symbol.strip().upper()
    if not raw:
        return []
    aliases = [raw]

    alias_map = {
        "BRK.B": "BRK_B",
        "BF.B": "BF_B",
        "GPUS-PD": "GPUS_PD",
    }
    mapped = alias_map.get(raw)
    if mapped and mapped not in aliases:
        aliases.append(mapped)

    if "." in raw:
        aliases.append(raw.replace(".", "_"))
        aliases.append(raw.replace(".", "-"))
    if "-" in raw:
        aliases.append(raw.replace("-", "_"))
        aliases.append(raw.replace("-", "."))

    ordered = []
    seen = set()
    for item in aliases:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _pick_dataset_file(symbol: str, adjusted_dir: Path, vendor_preference: list[str]) -> Path | None:
    symbol_candidates = _symbol_candidates(symbol)
    if not symbol_candidates:
        return None

    vendor_rank = {vendor.upper(): idx for idx, vendor in enumerate(vendor_preference)}
    best = None
    best_score = None
    for idx, candidate in enumerate(symbol_candidates):
        pattern_matches = list(adjusted_dir.glob(f"*_{candidate}_*.csv"))
        if not pattern_matches:
            pattern_matches = list(adjusted_dir.glob(f"*_{candidate}.csv"))
        for path in pattern_matches:
            vendor, _ = _parse_dataset_name(path)
            rank = vendor_rank.get(vendor.upper(), len(vendor_rank) + 1)
            rows = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1
            score = (idx, rank, -rows)
            if best_score is None or score < best_score:
                best = path
                best_score = score
    return best


def _predict_scores(
    model: TorchMLP, features: np.ndarray, device: torch.device, batch_size: int
) -> np.ndarray:
    if features.size == 0:
        return np.array([], dtype=np.float32)
    scores: list[np.ndarray] = []
    total = len(features)
    for start in range(0, total, batch_size):
        batch = torch.tensor(features[start : start + batch_size], dtype=torch.float32)
        batch = batch.to(device)
        with torch.no_grad():
            output = model(batch).squeeze(-1).detach().cpu().numpy()
        scores.append(np.atleast_1d(output).astype(np.float32, copy=False))
    return np.concatenate(scores) if scores else np.array([], dtype=np.float32)


def _check_cancel(cancel_path: Path | None) -> None:
    if cancel_path and cancel_path.exists():
        raise CancelledError("cancel_requested")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ml/config.json")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--output", default="ml/models/scores.csv")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cancel-path", default="")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    train_start = _parse_train_start(config)
    cancel_path = Path(args.cancel_path) if args.cancel_path else None
    data_root = Path(args.data_root) if args.data_root else _data_root()
    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"缺少目录: {adjusted_dir}")

    symbol_life = _load_symbol_life(data_root, config)

    model_dir = Path(config.get("output_dir") or "ml/models")
    payload_path = model_dir / "torch_payload.json"
    payload = load_linear_model(payload_path)
    model_type = str(payload.model_type or "torch_mlp").strip().lower()
    torch_config = config.get("torch", {})

    if model_type == "lgbm_ranker":
        if lgb is None:
            raise RuntimeError("missing_lightgbm")
        model_path = model_dir / "lgbm_model.txt"
        if not model_path.exists():
            raise RuntimeError(f"missing model file: {model_path}")
        model = lgb.Booster(model_file=str(model_path))
        device = None
    else:
        model_path = model_dir / "torch_model.pt"
        model = TorchMLP(
            input_dim=len(payload.features),
            hidden=torch_config.get("hidden", [64, 32]),
            dropout=float(torch_config.get("dropout", 0.1)),
        )
        state = torch.load(model_path, map_location="cpu")
        model.load_state_dict(state)
        model.eval()
        device = torch.device(
            "cuda" if (args.device == "auto" and torch.cuda.is_available()) else "cpu"
        )
        model.to(device)

    vendor_pref = config.get("vendor_preference", ["Alpha", "Stooq", "Lean"])
    benchmark_symbol = config.get("benchmark_symbol", "SPY")
    symbols = config.get("symbols", [])
    if benchmark_symbol not in symbols:
        symbols = [benchmark_symbol] + list(symbols)

    feature_windows = config.get("feature_windows", {})
    feat_config = FeatureConfig(
        return_windows=list(feature_windows.get("returns", [5, 10, 20, 60, 120, 252])),
        ma_windows=list(feature_windows.get("ma", [20, 60, 120, 200])),
        vol_windows=list(feature_windows.get("vol", [10, 20, 60])),
    )
    lookback = required_lookback(feat_config, payload.label_horizon_days)
    pit_cfg = config.get("pit_fundamentals", {})
    if not isinstance(pit_cfg, dict):
        pit_cfg = {}
    pit_enabled = bool(pit_cfg.get("enabled", False))
    pit_sample_on_snapshot = bool(pit_cfg.get("sample_on_snapshot", True))
    pit_missing_policy = str(pit_cfg.get("missing_policy", "fill_zero"))
    pit_fields: list[str] = []
    pit_map: dict[str, pd.DataFrame] = {}
    if pit_enabled:
        pit_dir = Path(pit_cfg.get("dir") or data_root / "factors" / "pit_weekly_fundamentals")
        if not pit_dir.is_absolute():
            pit_dir = data_root / pit_dir
        pit_min_coverage = float(pit_cfg.get("min_coverage", 0.05))
        pit_coverage_action = str(pit_cfg.get("coverage_action", "warn"))
        pit_start = pit_cfg.get("start")
        pit_end = pit_cfg.get("end")
        pit_map, pit_fields, _ = load_pit_fundamentals(
            pit_dir,
            symbols,
            start=pit_start,
            end=pit_end,
            min_coverage=pit_min_coverage,
            coverage_action=pit_coverage_action,
        )

    spy_path = _pick_dataset_file(benchmark_symbol, adjusted_dir, vendor_pref)
    if not spy_path:
        raise RuntimeError("缺少基准数据")
    spy_df = _load_series(spy_path)
    life = symbol_life.get(benchmark_symbol)
    if life:
        spy_df = _apply_symbol_life(spy_df, life)

    rows: list[pd.DataFrame] = []
    batch_size = int(torch_config.get("batch_size", 4096)) or 4096
    mean_vec = np.array([payload.mean.get(name, 0.0) for name in payload.features], dtype=np.float32)
    std_vec = np.array(
        [payload.std.get(name, 1.0) or 1.0 for name in payload.features], dtype=np.float32
    )

    for symbol in symbols:
        _check_cancel(cancel_path)
        symbol_path = _pick_dataset_file(symbol, adjusted_dir, vendor_pref)
        if not symbol_path:
            continue
        df = _load_series(symbol_path)
        life = symbol_life.get(symbol)
        if life:
            df = _apply_symbol_life(df, life)
            if df.empty:
                continue
        if len(df) < lookback:
            continue
        features = compute_features(df, spy_df, feat_config)
        if pit_enabled:
            pit_frame = pit_map.get(symbol)
            features = apply_pit_features(
                features,
                pit_frame,
                pit_fields,
                pit_sample_on_snapshot,
                pit_missing_policy,
            )
        if "vol_z_20" in features.columns:
            features["vol_z_20"] = features["vol_z_20"].fillna(0.0)
        if train_start is not None:
            features = features[features.index >= train_start]
            if features.empty:
                continue
        features = features.dropna()
        if features.empty:
            continue
        feature_frame = features.reindex(columns=payload.features).dropna()
        if feature_frame.empty:
            continue
        matrix = feature_frame.to_numpy(dtype=np.float32, copy=True)
        matrix = (matrix - mean_vec) / std_vec
        if model_type == "lgbm_ranker":
            scores = model.predict(matrix)
        else:
            scores = _predict_scores(model, matrix, device, batch_size)
        if scores.size == 0:
            continue
        rows.append(
            pd.DataFrame(
                {
                    "date": feature_frame.index.date.astype(str),
                    "symbol": symbol,
                    "score": scores,
                }
            )
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        pd.concat(rows, ignore_index=True).to_csv(output_path, index=False)
    else:
        pd.DataFrame(columns=["date", "symbol", "score"]).to_csv(output_path, index=False)
    print(f"saved scores: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except CancelledError:
        print("scoring canceled")
        sys.exit(130)
