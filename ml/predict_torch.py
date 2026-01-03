from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from feature_engineering import FeatureConfig, compute_features, required_lookback
from model_io import load_linear_model
from torch_model import TorchMLP


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
        scores.append(output.astype(np.float32, copy=False))
    return np.concatenate(scores) if scores else np.array([], dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ml/config.json")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--output", default="ml/models/scores.csv")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    data_root = Path(args.data_root) if args.data_root else _data_root()
    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"缺少目录: {adjusted_dir}")

    payload = load_linear_model(Path("ml/models/torch_payload.json"))
    torch_config = config.get("torch", {})
    model = TorchMLP(
        input_dim=len(payload.features),
        hidden=torch_config.get("hidden", [64, 32]),
        dropout=float(torch_config.get("dropout", 0.1)),
    )
    state = torch.load("ml/models/torch_model.pt", map_location="cpu")
    model.load_state_dict(state)
    model.eval()

    device = torch.device("cuda" if (args.device == "auto" and torch.cuda.is_available()) else "cpu")
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

    spy_path = _pick_dataset_file(benchmark_symbol, adjusted_dir, vendor_pref)
    if not spy_path:
        raise RuntimeError("缺少基准数据")
    spy_df = _load_series(spy_path)

    rows: list[pd.DataFrame] = []
    batch_size = int(torch_config.get("batch_size", 4096)) or 4096
    mean_vec = np.array([payload.mean.get(name, 0.0) for name in payload.features], dtype=np.float32)
    std_vec = np.array(
        [payload.std.get(name, 1.0) or 1.0 for name in payload.features], dtype=np.float32
    )

    for symbol in symbols:
        symbol_path = _pick_dataset_file(symbol, adjusted_dir, vendor_pref)
        if not symbol_path:
            continue
        df = _load_series(symbol_path)
        features = compute_features(df, spy_df, feat_config)
        if "vol_z_20" in features.columns:
            features["vol_z_20"] = features["vol_z_20"].fillna(0.0)
        features = features.dropna()
        if features.empty or len(features) < lookback:
            continue
        feature_frame = features.reindex(columns=payload.features).dropna()
        if feature_frame.empty:
            continue
        matrix = feature_frame.to_numpy(dtype=np.float32, copy=True)
        matrix = (matrix - mean_vec) / std_vec
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
    main()
