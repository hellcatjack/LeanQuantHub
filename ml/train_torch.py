from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:  # pragma: no cover - optional dependency
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover - optional dependency
    lgb = None

from feature_engineering import FeatureConfig, compute_features, compute_label, required_lookback
from pit_features import apply_pit_features, load_pit_fundamentals
from model_io import LinearModelPayload, save_linear_model
try:
    from torch_model import TorchMLP
except ImportError:  # pragma: no cover - optional dependency
    TorchMLP = None


@dataclass
class Window:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


class CancelledError(RuntimeError):
    pass


def _require_torch() -> None:
    if (
        torch is None
        or nn is None
        or DataLoader is None
        or TensorDataset is None
        or TorchMLP is None
    ):
        raise RuntimeError("torch_missing:请安装torch或切换到lgbm模型")


def _parse_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _data_root_from_config(config: dict) -> Path:
    value = (config.get("data_root") or "").strip()
    if value:
        return Path(value)
    env_root = os.environ.get("DATA_ROOT", "")
    if env_root:
        return Path(env_root)
    return Path.cwd() / "data"


def _parse_dataset_name(path: Path) -> tuple[str, str]:
    stem = path.stem
    parts = stem.split("_", 1)
    dataset_name = parts[1] if len(parts) == 2 else stem
    tokens = dataset_name.split("_")
    vendor = tokens[0] if tokens else ""
    symbol = tokens[1] if len(tokens) > 1 else ""
    return vendor, symbol


def _count_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for _ in handle:
            count += 1
    return max(count - 1, 0)


def _pick_dataset_file(
    symbol: str, adjusted_dir: Path, vendor_preference: list[str]
) -> Path | None:
    symbol = symbol.upper()
    candidates = list(adjusted_dir.glob(f"*_{symbol}_*.csv"))
    if not candidates:
        candidates = list(adjusted_dir.glob(f"*_{symbol}.csv"))
    if not candidates:
        return None

    vendor_rank = {vendor.upper(): idx for idx, vendor in enumerate(vendor_preference)}
    best = None
    best_score = None

    for path in candidates:
        vendor, _ = _parse_dataset_name(path)
        rank = vendor_rank.get(vendor.upper(), len(vendor_rank) + 1)
        rows = _count_rows(path)
        score = (rank, -rows)
        if best_score is None or score < best_score:
            best = path
            best_score = score
    return best


def _load_series(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [col.strip().lower() for col in df.columns]
    if "date" not in df.columns:
        raise ValueError(f"missing date column: {path}")
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


def _build_window(dates: Iterable[pd.Timestamp], config: dict, warmup_days: int) -> Window:
    dates = sorted(set(dates))
    if not dates:
        raise RuntimeError("样本为空")
    end = dates[-1]
    valid_months = int(config["valid_months"])
    train_years = int(config["train_years"])

    valid_end = end
    valid_start = valid_end - pd.DateOffset(months=valid_months)
    train_end = valid_start
    train_start = max(dates[0] + pd.Timedelta(days=warmup_days), train_end - pd.DateOffset(years=train_years))
    return Window(
        train_start=train_start,
        train_end=train_end,
        valid_start=valid_start,
        valid_end=valid_end,
    )


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_walk_forward_windows(
    dates: Iterable[pd.Timestamp],
    config: dict,
    warmup_days: int,
    horizon_days: int,
    max_test_date: pd.Timestamp | None = None,
) -> list[WalkForwardWindow]:
    dates = sorted(set(dates))
    if not dates:
        raise RuntimeError("样本为空")

    min_date = dates[0] + pd.Timedelta(days=warmup_days)
    last_date = max_test_date or dates[-1]

    train_years = _coerce_int(config.get("train_years"), 8)
    valid_months = _coerce_int(config.get("valid_months"), 12)
    test_months = _coerce_int(config.get("test_months"), 0)
    step_months = _coerce_int(config.get("step_months"), test_months)
    allow_overlap = bool(config.get("allow_overlap", False))

    if not allow_overlap and test_months > 0 and step_months < test_months:
        step_months = test_months

    if test_months <= 0 or step_months <= 0:
        return []

    anchor = min_date + pd.DateOffset(years=train_years, months=valid_months)
    windows: list[WalkForwardWindow] = []
    gap_days = max(int(horizon_days), 0)

    while anchor < last_date:
        valid_end = anchor
        valid_start = max(min_date, valid_end - pd.DateOffset(months=valid_months))
        train_end = valid_start
        train_start = max(min_date, train_end - pd.DateOffset(years=train_years))
        test_start = valid_end + pd.Timedelta(days=gap_days)
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > last_date:
            test_end = last_date

        if train_start >= train_end or valid_start >= valid_end:
            anchor += pd.DateOffset(months=step_months)
            continue
        if test_end <= test_start:
            break

        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                valid_start=valid_start,
                valid_end=valid_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        if test_end >= last_date:
            break
        anchor += pd.DateOffset(months=step_months)

    return windows


def _standardize(
    df: pd.DataFrame, feature_cols: list[str]
) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    mean = df[feature_cols].mean().to_dict()
    std = df[feature_cols].std().replace(0, np.nan).to_dict()
    scaled = df.copy()
    for col in feature_cols:
        scaled[col] = (scaled[col] - mean[col]) / (std[col] if std[col] else 1.0)
    return scaled, mean, std


def _resolve_model_type(config: dict) -> str:
    raw = config.get("model_type") or (config.get("model") or {}).get("type") or "torch_mlp"
    value = str(raw).strip().lower()
    if value in {"lgbm_rank", "lgbm_ranker", "lightgbm_rank", "rank_lgbm"}:
        return "lgbm_ranker"
    return "torch_mlp"


def _build_rank_groups(frame: pd.DataFrame) -> list[int]:
    if frame.empty:
        return []
    ordered = frame.sort_index()
    return ordered.groupby(ordered.index.date).size().tolist()


def _lgbm_params(config: dict) -> dict:
    params: dict[str, object] = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "n_estimators": 200,
        "min_data_in_leaf": 50,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
    }
    raw = config.get("model_params")
    if isinstance(raw, dict):
        params.update({k: v for k, v in raw.items() if k != "rank_label_bins"})
    device = str(config.get("device") or "").strip().lower()
    if device in {"cuda", "gpu"} and "device_type" not in params:
        params["device_type"] = "gpu"
    if device in {"cpu"} and "device_type" not in params:
        params["device_type"] = "cpu"
    if "gpu_platform_id" not in params and config.get("gpu_platform_id") is not None:
        params["gpu_platform_id"] = int(config.get("gpu_platform_id"))
    if "gpu_device_id" not in params and config.get("gpu_device_id") is not None:
        params["gpu_device_id"] = int(config.get("gpu_device_id"))
    return params


def _extract_lgbm_curve(
    model: "lgb.LGBMRanker",
) -> tuple[str | None, list[float], list[float]]:
    evals = getattr(model, "evals_result_", None) or {}
    if not isinstance(evals, dict) or not evals:
        return None, [], []

    def _pick_metric(series: dict) -> str:
        for key in ("ndcg@50", "ndcg@10", "ndcg@100"):
            if key in series:
                return key
        return next(iter(series.keys()))

    metric_name = None
    for key in ("valid", "valid_0", "train", "training"):
        series = evals.get(key)
        if isinstance(series, dict) and series:
            metric_name = _pick_metric(series)
            break
    if not metric_name:
        return None, [], []

    def _series(keys: tuple[str, ...]) -> list[float]:
        for key in keys:
            series = evals.get(key)
            if not isinstance(series, dict):
                continue
            values = series.get(metric_name)
            if values is None and series:
                values = next(iter(series.values()))
            if values:
                return [float(item) for item in values]
        return []

    train_curve = _series(("train", "training"))
    valid_curve = _series(("valid", "valid_0"))
    return metric_name, train_curve, valid_curve


def _aggregate_curves(curves: list[list[float]]) -> list[float]:
    curves = [curve for curve in curves if curve]
    if not curves:
        return []
    min_len = min(len(curve) for curve in curves)
    if min_len <= 0:
        return []
    return [float(np.mean([curve[i] for curve in curves])) for i in range(min_len)]


def _build_curve_payload(
    metric: str | None, train_curve: list[float], valid_curve: list[float]
) -> dict | None:
    if not train_curve and not valid_curve:
        return None
    if train_curve and valid_curve:
        length = min(len(train_curve), len(valid_curve))
        train_curve = train_curve[:length]
        valid_curve = valid_curve[:length]
    else:
        length = len(train_curve) or len(valid_curve)
    if length <= 0:
        return None
    return {
        "metric": metric or "",
        "iterations": list(range(1, length + 1)),
        "train": train_curve,
        "valid": valid_curve,
    }


def _build_loss_curve(history: list[dict]) -> dict | None:
    if not history:
        return None
    values = []
    iterations = []
    for idx, item in enumerate(history, start=1):
        raw = item.get("valid_loss")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        values.append(value)
        iterations.append(int(item.get("epoch") or idx))
    if not values:
        return None
    return {"metric": "valid_loss", "iterations": iterations, "train": [], "valid": values}


def _resolve_eval_at_list(config: dict, base_eval: int) -> list[int]:
    values: list[int] = []
    raw_list = config.get("rank_eval_at_list") or config.get("rank_eval_ats")
    if isinstance(raw_list, (list, tuple)):
        for item in raw_list:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number > 0:
                values.append(number)
    if base_eval:
        values.append(int(base_eval))
    values.extend([10, 50, 100])
    deduped = sorted({value for value in values if value > 0})
    return deduped or [max(int(base_eval or 1), 1)]


def _extract_ndcg_scores(model: "lgb.LGBMRanker") -> dict[str, float]:
    best = getattr(model, "best_score_", None) or {}
    if not isinstance(best, dict):
        return {}
    valid = best.get("valid") or best.get("valid_0") or {}
    if not isinstance(valid, dict):
        return {}
    result: dict[str, float] = {}
    for k in (10, 50, 100):
        key = f"ndcg@{k}"
        if key in valid:
            try:
                result[f"ndcg_at_{k}"] = float(valid[key])
            except (TypeError, ValueError):
                continue
    return result


def _safe_corr(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 2 or y.size < 2:
        return None
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 2 or y.size < 2:
        return None
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _rank_values(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=np.float32)


def _compute_ic_scores(pred: np.ndarray, actual: np.ndarray) -> tuple[float | None, float | None]:
    if pred.size == 0 or actual.size == 0:
        return None, None
    mask = np.isfinite(pred) & np.isfinite(actual)
    pred = pred[mask]
    actual = actual[mask]
    if pred.size < 2 or actual.size < 2:
        return None, None
    ic = _safe_corr(pred, actual)
    rank_ic = _safe_corr(_rank_values(pred), _rank_values(actual))
    return ic, rank_ic


def _rank_labels(frame: pd.DataFrame, bins: int) -> np.ndarray:
    if frame.empty:
        return np.array([], dtype=np.int32)
    bins = max(int(bins), 2)
    labels = np.zeros(len(frame), dtype=np.int32)
    values = frame["label"].to_numpy()
    groups = frame.groupby(frame.index.date).indices
    for idx_list in groups.values():
        if len(idx_list) == 0:
            continue
        if len(idx_list) == 1:
            labels[idx_list[0]] = 0
            continue
        group_vals = values[idx_list]
        ranks = group_vals.argsort().argsort()
        pct = ranks / max(len(group_vals) - 1, 1)
        bucket = np.floor(pct * bins).astype(int)
        bucket = np.clip(bucket, 0, bins - 1)
        labels[idx_list] = bucket
    return labels


def _train_lgbm_ranker(
    config: dict,
    x_train: np.ndarray,
    y_train: np.ndarray,
    train_groups: list[int],
    x_valid: np.ndarray,
    y_valid: np.ndarray,
    valid_groups: list[int],
    eval_at: list[int],
) -> "lgb.LGBMRanker":
    if lgb is None:
        raise RuntimeError("missing_lightgbm")
    params = _lgbm_params(config)
    early_rounds = params.pop("early_stopping_rounds", None)
    model = lgb.LGBMRanker(**params)
    callbacks = []
    if early_rounds:
        callbacks.append(lgb.early_stopping(int(early_rounds), verbose=False))
    model.fit(
        x_train,
        y_train,
        group=train_groups,
        eval_set=[(x_train, y_train), (x_valid, y_valid)],
        eval_group=[train_groups, valid_groups],
        eval_names=["train", "valid"],
        eval_at=[int(item) for item in eval_at if int(item) > 0] or [1],
        callbacks=callbacks or None,
    )
    return model


def _predict_scores(
    model: nn.Module, features: np.ndarray, device: torch.device, batch_size: int
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


def _write_progress(path: Path | None, payload: dict) -> None:
    if not path:
        return
    data = dict(payload)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_cancel(
    cancel_path: Path | None, progress_path: Path | None, payload: dict | None = None
) -> None:
    if not cancel_path or not cancel_path.exists():
        return
    if progress_path:
        data = {"phase": "canceled"}
        if payload:
            data.update(payload)
        _write_progress(progress_path, data)
    raise CancelledError("cancel_requested")


def _train_loop(
    model: nn.Module,
    train_loader: DataLoader,
    valid_loader: DataLoader,
    config: dict,
    device: torch.device,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_cb: Callable[[], None] | None = None,
) -> dict:
    lr = float(config.get("lr", 1e-3))
    weight_decay = float(config.get("weight_decay", 1e-4))
    epochs = int(config.get("epochs", 50))
    patience = int(config.get("patience", 6))

    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    loss_fn = nn.MSELoss()

    best_loss = None
    best_state = None
    patience_left = patience
    history = []

    for epoch in range(1, epochs + 1):
        if cancel_cb:
            cancel_cb()
        model.train()
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad()
            preds = model(batch_x)
            loss = loss_fn(preds, batch_y)
            loss.backward()
            optimizer.step()

        model.eval()
        losses = []
        with torch.no_grad():
            for batch_x, batch_y in valid_loader:
                batch_x = batch_x.to(device)
                batch_y = batch_y.to(device)
                preds = model(batch_x)
                loss = loss_fn(preds, batch_y)
                losses.append(loss.item())
        valid_loss = float(np.mean(losses)) if losses else float("inf")
        history.append({"epoch": epoch, "valid_loss": valid_loss})
        if progress_cb:
            progress_cb(epoch, epochs)

        if best_loss is None or valid_loss < best_loss:
            best_loss = valid_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_state:
        model.load_state_dict(best_state)
    return {"history": history, "best_loss": best_loss}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ml/config.json")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--scores-output", default="")
    parser.add_argument("--progress-path", default="")
    parser.add_argument("--cancel-path", default="")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = _parse_config(config_path)
    progress_path = Path(args.progress_path) if args.progress_path else None
    cancel_path = Path(args.cancel_path) if args.cancel_path else None
    _write_progress(progress_path, {"phase": "prepare", "progress": 0.0})
    _check_cancel(cancel_path, progress_path, {"progress": 0.0})
    data_root = Path(args.data_root) if args.data_root else _data_root_from_config(config)
    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"缺少目录: {adjusted_dir}")

    symbol_life = _load_symbol_life(data_root, config)

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
    horizon = int(config.get("label_horizon_days", 20))
    label_price = str(config.get("label_price", "open")).strip().lower()
    if label_price not in {"open", "close"}:
        label_price = "close"
    label_start_offset = int(config.get("label_start_offset", 1))
    train_start = _parse_train_start(config)

    pit_cfg = config.get("pit_fundamentals", {})
    if not isinstance(pit_cfg, dict):
        pit_cfg = {}
    pit_enabled = bool(pit_cfg.get("enabled", False))
    pit_sample_on_snapshot = bool(pit_cfg.get("sample_on_snapshot", True))
    pit_missing_policy = str(pit_cfg.get("missing_policy", "fill_zero"))
    pit_fields: list[str] = []
    pit_map: dict[str, pd.DataFrame] = {}
    pit_summary: dict[str, float] = {}
    if pit_enabled:
        pit_dir = Path(pit_cfg.get("dir") or data_root / "factors" / "pit_weekly_fundamentals")
        if not pit_dir.is_absolute():
            pit_dir = data_root / pit_dir
        pit_min_coverage = float(pit_cfg.get("min_coverage", 0.05))
        pit_coverage_action = str(pit_cfg.get("coverage_action", "warn"))
        pit_start = pit_cfg.get("start")
        pit_end = pit_cfg.get("end")
        pit_map, pit_fields, pit_summary = load_pit_fundamentals(
            pit_dir,
            symbols,
            start=pit_start,
            end=pit_end,
            min_coverage=pit_min_coverage,
            coverage_action=pit_coverage_action,
        )
        print(
            "pit fundamentals: rows={total_rows} coverage={coverage:.4f}".format(
                **{
                    "total_rows": pit_summary.get("total_rows", 0.0),
                    "coverage": pit_summary.get("coverage", 0.0),
                }
            )
        )

    spy_path = _pick_dataset_file(benchmark_symbol, adjusted_dir, vendor_pref)
    if not spy_path:
        raise RuntimeError(f"未找到基准数据: {benchmark_symbol}")
    spy_df = _load_series(spy_path)
    life = symbol_life.get(benchmark_symbol)
    if life:
        spy_df = _apply_symbol_life(spy_df, life)

    dataset = []
    features_map: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        _check_cancel(cancel_path, progress_path)
        symbol_path = _pick_dataset_file(symbol, adjusted_dir, vendor_pref)
        if not symbol_path:
            continue
        df = _load_series(symbol_path)
        life = symbol_life.get(symbol)
        if life:
            df = _apply_symbol_life(df, life)
            if df.empty:
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
        if train_start is not None:
            features = features[features.index >= train_start]
            if features.empty:
                continue
        score_features = features.copy()
        if "vol_z_20" in score_features.columns:
            score_features["vol_z_20"] = score_features["vol_z_20"].fillna(0.0)
        features_map[symbol] = score_features
        label = compute_label(
            df,
            spy_df,
            horizon,
            start_offset=label_start_offset,
            price_column=label_price,
        )
        merged = features.join(label.rename("label")).dropna()
        if merged.empty:
            continue
        merged["symbol"] = symbol
        dataset.append(merged)

    if not dataset:
        raise RuntimeError("未生成有效训练样本")

    data = pd.concat(dataset).sort_index()
    feature_cols = [col for col in data.columns if col not in {"label", "symbol"}]

    lookback = required_lookback(feat_config, horizon)
    walk_config = config.get("walk_forward", {})
    max_feature_date = None
    if features_map:
        feature_maxes = [frame.index.max() for frame in features_map.values() if not frame.empty]
        if feature_maxes:
            max_feature_date = max(feature_maxes)

    windows = _build_walk_forward_windows(
        data.index, walk_config, lookback, horizon, max_test_date=max_feature_date
    )
    if windows:
        _write_progress(
            progress_path,
            {
                "phase": "train",
                "progress": 0.0,
                "window": 0,
                "window_total": len(windows),
            },
        )

    output_dir = Path(config.get("output_dir", "ml/models"))
    output_dir.mkdir(parents=True, exist_ok=True)
    model_type = _resolve_model_type(config)

    if model_type == "lgbm_ranker":
        scores_output = args.scores_output.strip()
        scores_path = Path(scores_output) if scores_output else output_dir / "scores.csv"
        eval_at = int(config.get("rank_eval_at") or config.get("score_top_n") or 50)
        eval_at_list = _resolve_eval_at_list(config, eval_at)
        rank_bins = int(
            config.get("rank_label_bins")
            or (config.get("model_params") or {}).get("rank_label_bins")
            or 5
        )

        if not windows:
            window = _build_window(data.index, walk_config, lookback)
            train_df = data[(data.index >= window.train_start) & (data.index < window.train_end)]
            valid_df = data[(data.index >= window.valid_start) & (data.index <= window.valid_end)]
            if train_df.empty or valid_df.empty:
                raise RuntimeError("训练/验证窗口为空，请检查时间跨度")

            scaled_train, mean, std = _standardize(train_df, feature_cols)
            scaled_valid = valid_df.copy()
            for col in feature_cols:
                scaled_valid[col] = (scaled_valid[col] - mean[col]) / (std[col] if std[col] else 1.0)

            x_train = scaled_train[feature_cols].values.astype(np.float32)
            y_train = _rank_labels(scaled_train, rank_bins)
            x_valid = scaled_valid[feature_cols].values.astype(np.float32)
            y_valid = _rank_labels(scaled_valid, rank_bins)

            train_groups = _build_rank_groups(train_df)
            valid_groups = _build_rank_groups(valid_df)

            model = _train_lgbm_ranker(
                config,
                x_train,
                y_train,
                train_groups,
                x_valid,
                y_valid,
                valid_groups,
                eval_at_list,
            )
            model.booster_.save_model(str(output_dir / "lgbm_model.txt"))
            metric_name, train_curve, valid_curve = _extract_lgbm_curve(model)
            ndcg_scores = _extract_ndcg_scores(model)
            preds = model.predict(x_valid)
            ic, rank_ic = _compute_ic_scores(preds, valid_df["label"].values.astype(np.float32))

            payload = LinearModelPayload(
                model_type="lgbm_ranker",
                features=feature_cols,
                coef=[],
                intercept=0.0,
                mean={k: float(v) for k, v in mean.items()},
                std={k: float(v) for k, v in std.items()},
                label_horizon_days=horizon,
                trained_at=datetime.utcnow().isoformat(),
                train_window={
                    "train_start": window.train_start.date().isoformat(),
                    "train_end": window.train_end.date().isoformat(),
                    "valid_end": window.valid_end.date().isoformat(),
                    "test_end": window.valid_end.date().isoformat(),
                },
            )
            save_linear_model(output_dir / "torch_payload.json", payload)
            metrics = {
                "model_type": "lgbm_ranker",
                "best_iteration": getattr(model, "best_iteration_", None),
                "best_score": getattr(model, "best_score_", None),
                **ndcg_scores,
                "ic": ic,
                "rank_ic": rank_ic,
            }
            curve_payload = _build_curve_payload(metric_name, train_curve, valid_curve)
            if curve_payload:
                metrics["curve"] = curve_payload
            (output_dir / "torch_metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            _write_progress(progress_path, {"phase": "train_done", "progress": 0.9})
            return

        score_rows: list[pd.DataFrame] = []
        window_metrics: list[dict] = []
        last_payload: LinearModelPayload | None = None
        last_model: "lgb.LGBMRanker | None" = None
        curve_metric: str | None = None
        train_curves: list[list[float]] = []
        valid_curves: list[list[float]] = []

        total_windows = len(windows)
        for idx, window in enumerate(windows):
            _check_cancel(cancel_path, progress_path)
            train_df = data[(data.index >= window.train_start) & (data.index < window.train_end)]
            valid_df = data[(data.index >= window.valid_start) & (data.index <= window.valid_end)]
            if train_df.empty or valid_df.empty:
                continue

            scaled_train, mean, std = _standardize(train_df, feature_cols)
            scaled_valid = valid_df.copy()
            for col in feature_cols:
                scaled_valid[col] = (scaled_valid[col] - mean[col]) / (std[col] if std[col] else 1.0)

            x_train = scaled_train[feature_cols].values.astype(np.float32)
            y_train = _rank_labels(scaled_train, rank_bins)
            x_valid = scaled_valid[feature_cols].values.astype(np.float32)
            y_valid = _rank_labels(scaled_valid, rank_bins)

            train_groups = _build_rank_groups(train_df)
            valid_groups = _build_rank_groups(valid_df)

            model = _train_lgbm_ranker(
                config,
                x_train,
                y_train,
                train_groups,
                x_valid,
                y_valid,
                valid_groups,
                eval_at_list,
            )
            metric_name, train_curve, valid_curve = _extract_lgbm_curve(model)
            ndcg_scores = _extract_ndcg_scores(model)
            preds = model.predict(x_valid)
            ic, rank_ic = _compute_ic_scores(preds, valid_df["label"].values.astype(np.float32))
            if metric_name and not curve_metric:
                curve_metric = metric_name
            if train_curve:
                train_curves.append(train_curve)
            if valid_curve:
                valid_curves.append(valid_curve)
            window_metrics.append(
                {
                    "train_start": window.train_start.date().isoformat(),
                    "train_end": window.train_end.date().isoformat(),
                    "valid_start": window.valid_start.date().isoformat(),
                    "valid_end": window.valid_end.date().isoformat(),
                    "test_start": window.test_start.date().isoformat(),
                    "test_end": window.test_end.date().isoformat(),
                    "best_iteration": getattr(model, "best_iteration_", None),
                    "best_score": getattr(model, "best_score_", None),
                    **ndcg_scores,
                    "ic": ic,
                    "rank_ic": rank_ic,
                }
            )

            _write_progress(
                progress_path,
                {
                    "phase": "score",
                    "progress": (idx + 0.95) / max(total_windows, 1),
                    "window": idx + 1,
                    "window_total": total_windows,
                },
            )

            mean_vec = np.array([mean.get(name, 0.0) for name in feature_cols], dtype=np.float32)
            std_vec = np.array(
                [std.get(name, 1.0) or 1.0 for name in feature_cols], dtype=np.float32
            )
            for symbol, features in features_map.items():
                _check_cancel(cancel_path, progress_path)
                feature_frame = features[
                    (features.index > window.test_start) & (features.index <= window.test_end)
                ]
                if feature_frame.empty:
                    continue
                feature_frame = feature_frame.reindex(columns=feature_cols).dropna()
                if feature_frame.empty:
                    continue
                matrix = feature_frame.to_numpy(dtype=np.float32, copy=True)
                matrix = (matrix - mean_vec) / std_vec
                scores = model.predict(matrix)
                if scores is None or len(scores) == 0:
                    continue
                score_rows.append(
                    pd.DataFrame(
                        {
                            "date": feature_frame.index.date.astype(str),
                            "symbol": symbol,
                            "score": scores,
                            "window": idx,
                        }
                    )
                )

            _write_progress(
                progress_path,
                {
                    "phase": "window_done",
                    "progress": (idx + 1) / max(total_windows, 1),
                    "window": idx + 1,
                    "window_total": total_windows,
                },
            )

            last_payload = LinearModelPayload(
                model_type="lgbm_ranker",
                features=feature_cols,
                coef=[],
                intercept=0.0,
                mean={k: float(v) for k, v in mean.items()},
                std={k: float(v) for k, v in std.items()},
                label_horizon_days=horizon,
                trained_at=datetime.utcnow().isoformat(),
                train_window={
                    "train_start": window.train_start.date().isoformat(),
                    "train_end": window.train_end.date().isoformat(),
                    "valid_end": window.valid_end.date().isoformat(),
                    "test_end": window.test_end.date().isoformat(),
                },
            )
            last_model = model

        if last_model is None or last_payload is None:
            raise RuntimeError("训练窗口为空，请检查时间跨度")

        last_model.booster_.save_model(str(output_dir / "lgbm_model.txt"))
        save_linear_model(output_dir / "torch_payload.json", last_payload)
        curve_payload = _build_curve_payload(
            curve_metric,
            _aggregate_curves(train_curves),
            _aggregate_curves(valid_curves),
        )
        (output_dir / "torch_metrics.json").write_text(
            json.dumps(
                {
                    "model_type": "lgbm_ranker",
                    "curve": curve_payload,
                    "walk_forward": {"windows": window_metrics, "config": walk_config},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        scores_path.parent.mkdir(parents=True, exist_ok=True)
        if score_rows:
            scores_df = pd.concat(score_rows, ignore_index=True)
            scores_df = scores_df.sort_values(["date", "symbol", "window"])
            scores_df = scores_df.drop_duplicates(subset=["date", "symbol"], keep="first")
            scores_df = scores_df.sort_values(["date", "symbol"]).drop(columns=["window"])
        else:
            scores_df = pd.DataFrame(columns=["date", "symbol", "score"])
        scores_df.to_csv(scores_path, index=False)

        _write_progress(progress_path, {"phase": "done", "progress": 1.0})
        print(f"saved model: {output_dir / 'lgbm_model.txt'}")
        print(f"saved payload: {output_dir / 'torch_payload.json'}")
        print(f"saved scores: {scores_path}")
        return

    _require_torch()
    batch_size = int(config.get("torch", {}).get("batch_size", 512))
    device = torch.device("cuda" if (args.device == "auto" and torch.cuda.is_available()) else "cpu")
    torch_config = config.get("torch", {})

    if not windows:
        window = _build_window(data.index, walk_config, lookback)
        train_df = data[(data.index >= window.train_start) & (data.index < window.train_end)]
        valid_df = data[(data.index >= window.valid_start) & (data.index <= window.valid_end)]
        if train_df.empty or valid_df.empty:
            raise RuntimeError("训练/验证窗口为空，请检查时间跨度")

        scaled_train, mean, std = _standardize(train_df, feature_cols)
        scaled_valid = valid_df.copy()
        for col in feature_cols:
            scaled_valid[col] = (scaled_valid[col] - mean[col]) / (std[col] if std[col] else 1.0)

        x_train = scaled_train[feature_cols].values.astype(np.float32)
        y_train = scaled_train["label"].values.astype(np.float32)
        x_valid = scaled_valid[feature_cols].values.astype(np.float32)
        y_valid = scaled_valid["label"].values.astype(np.float32)

        train_loader = DataLoader(
            TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
            batch_size=batch_size,
            shuffle=True,
        )
        valid_loader = DataLoader(
            TensorDataset(torch.from_numpy(x_valid), torch.from_numpy(y_valid)),
            batch_size=batch_size,
            shuffle=False,
        )

        model = TorchMLP(
            input_dim=len(feature_cols),
            hidden=torch_config.get("hidden", [64, 32]),
            dropout=float(torch_config.get("dropout", 0.1)),
        ).to(device)

        def _epoch_progress(epoch: int, total: int) -> None:
            _write_progress(
                progress_path,
                {
                    "phase": "train",
                    "progress": min(max(epoch / total, 0.0), 1.0) * 0.9,
                    "epoch": epoch,
                    "epoch_total": total,
                },
            )

        metrics = _train_loop(
            model,
            train_loader,
            valid_loader,
            torch_config,
            device,
            progress_cb=_epoch_progress,
            cancel_cb=lambda: _check_cancel(cancel_path, progress_path),
        )
        curve_payload = _build_loss_curve(metrics.get("history", []))
        if curve_payload:
            metrics["curve"] = curve_payload
        torch.save(model.state_dict(), output_dir / "torch_model.pt")

        payload = LinearModelPayload(
            model_type="torch_mlp",
            features=feature_cols,
            coef=[],
            intercept=0.0,
            mean={k: float(v) for k, v in mean.items()},
            std={k: float(v) for k, v in std.items()},
            label_horizon_days=horizon,
            trained_at=datetime.utcnow().isoformat(),
            train_window={
                "train_start": window.train_start.date().isoformat(),
                "train_end": window.train_end.date().isoformat(),
                "valid_end": window.valid_end.date().isoformat(),
                "test_end": window.valid_end.date().isoformat(),
            },
        )
        save_linear_model(output_dir / "torch_payload.json", payload)
        (output_dir / "torch_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        _write_progress(progress_path, {"phase": "train_done", "progress": 0.9})

        print(f"saved model: {output_dir / 'torch_model.pt'}")
        print(f"saved payload: {output_dir / 'torch_payload.json'}")
        return

    scores_output = args.scores_output.strip()
    if scores_output:
        scores_path = Path(scores_output)
    else:
        scores_path = output_dir / "scores.csv"

    score_rows: list[pd.DataFrame] = []
    window_metrics: list[dict] = []
    last_payload: LinearModelPayload | None = None
    last_model_state: dict[str, torch.Tensor] | None = None
    loss_curves: list[list[float]] = []

    total_windows = len(windows)
    for idx, window in enumerate(windows):
        _check_cancel(cancel_path, progress_path)
        train_df = data[(data.index >= window.train_start) & (data.index < window.train_end)]
        valid_df = data[(data.index >= window.valid_start) & (data.index <= window.valid_end)]
        if train_df.empty or valid_df.empty:
            continue

        scaled_train, mean, std = _standardize(train_df, feature_cols)
        scaled_valid = valid_df.copy()
        for col in feature_cols:
            scaled_valid[col] = (scaled_valid[col] - mean[col]) / (std[col] if std[col] else 1.0)

        x_train = scaled_train[feature_cols].values.astype(np.float32)
        y_train = scaled_train["label"].values.astype(np.float32)
        x_valid = scaled_valid[feature_cols].values.astype(np.float32)
        y_valid = scaled_valid["label"].values.astype(np.float32)

        train_loader = DataLoader(
            TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
            batch_size=batch_size,
            shuffle=True,
        )
        valid_loader = DataLoader(
            TensorDataset(torch.from_numpy(x_valid), torch.from_numpy(y_valid)),
            batch_size=batch_size,
            shuffle=False,
        )

        model = TorchMLP(
            input_dim=len(feature_cols),
            hidden=torch_config.get("hidden", [64, 32]),
            dropout=float(torch_config.get("dropout", 0.1)),
        ).to(device)

        def _window_progress(epoch: int, total: int) -> None:
            progress = (idx + min(max(epoch / total, 0.0), 1.0)) / max(total_windows, 1)
            _write_progress(
                progress_path,
                {
                    "phase": "train",
                    "progress": progress,
                    "window": idx + 1,
                    "window_total": total_windows,
                    "epoch": epoch,
                    "epoch_total": total,
                },
            )

        metrics = _train_loop(
            model,
            train_loader,
            valid_loader,
            torch_config,
            device,
            progress_cb=_window_progress,
            cancel_cb=lambda: _check_cancel(cancel_path, progress_path),
        )
        curve_payload = _build_loss_curve(metrics.get("history", []))
        if curve_payload and curve_payload.get("valid"):
            loss_curves.append(list(curve_payload.get("valid") or []))
        window_metrics.append(
            {
                "train_start": window.train_start.date().isoformat(),
                "train_end": window.train_end.date().isoformat(),
                "valid_start": window.valid_start.date().isoformat(),
                "valid_end": window.valid_end.date().isoformat(),
                "test_start": window.test_start.date().isoformat(),
                "test_end": window.test_end.date().isoformat(),
                "best_loss": metrics.get("best_loss"),
                "epochs": len(metrics.get("history", [])),
            }
        )

        _write_progress(
            progress_path,
            {
                "phase": "score",
                "progress": (idx + 0.95) / max(total_windows, 1),
                "window": idx + 1,
                "window_total": total_windows,
            },
        )

        model.eval()
        mean_vec = np.array([mean.get(name, 0.0) for name in feature_cols], dtype=np.float32)
        std_vec = np.array([std.get(name, 1.0) or 1.0 for name in feature_cols], dtype=np.float32)

        for symbol, features in features_map.items():
            _check_cancel(cancel_path, progress_path)
            feature_frame = features[
                (features.index > window.test_start) & (features.index <= window.test_end)
            ]
            if feature_frame.empty:
                continue
            feature_frame = feature_frame.reindex(columns=feature_cols).dropna()
            if feature_frame.empty:
                continue
            matrix = feature_frame.to_numpy(dtype=np.float32, copy=True)
            matrix = (matrix - mean_vec) / std_vec
            scores = _predict_scores(model, matrix, device, batch_size)
            if scores.size == 0:
                continue
            score_rows.append(
                pd.DataFrame(
                    {
                        "date": feature_frame.index.date.astype(str),
                        "symbol": symbol,
                        "score": scores,
                        "window": idx,
                    }
                )
            )

        _write_progress(
            progress_path,
            {
                "phase": "window_done",
                "progress": (idx + 1) / max(total_windows, 1),
                "window": idx + 1,
                "window_total": total_windows,
            },
        )

        last_payload = LinearModelPayload(
            model_type="torch_mlp",
            features=feature_cols,
            coef=[],
            intercept=0.0,
            mean={k: float(v) for k, v in mean.items()},
            std={k: float(v) for k, v in std.items()},
            label_horizon_days=horizon,
            trained_at=datetime.utcnow().isoformat(),
            train_window={
                "train_start": window.train_start.date().isoformat(),
                "train_end": window.train_end.date().isoformat(),
                "valid_end": window.valid_end.date().isoformat(),
                "test_end": window.test_end.date().isoformat(),
            },
        )
        last_model_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    if last_model_state is None or last_payload is None:
        raise RuntimeError("训练窗口为空，请检查时间跨度")

    torch.save(last_model_state, output_dir / "torch_model.pt")
    save_linear_model(output_dir / "torch_payload.json", last_payload)
    curve_payload = _build_curve_payload(
        "valid_loss", [], _aggregate_curves(loss_curves)
    )
    (output_dir / "torch_metrics.json").write_text(
        json.dumps(
            {
                "model_type": "torch_mlp",
                "curve": curve_payload,
                "walk_forward": {"windows": window_metrics, "config": walk_config},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    scores_path.parent.mkdir(parents=True, exist_ok=True)
    if score_rows:
        scores_df = pd.concat(score_rows, ignore_index=True)
        scores_df = scores_df.sort_values(["date", "symbol", "window"])
        scores_df = scores_df.drop_duplicates(subset=["date", "symbol"], keep="first")
        scores_df = scores_df.sort_values(["date", "symbol"]).drop(columns=["window"])
    else:
        scores_df = pd.DataFrame(columns=["date", "symbol", "score"])
    scores_df.to_csv(scores_path, index=False)

    _write_progress(progress_path, {"phase": "done", "progress": 1.0})

    print(f"saved model: {output_dir / 'torch_model.pt'}")
    print(f"saved payload: {output_dir / 'torch_payload.json'}")
    print(f"saved scores: {scores_path}")


if __name__ == "__main__":
    try:
        main()
    except CancelledError:
        print("training canceled")
        sys.exit(130)
