from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from feature_engineering import FeatureConfig, compute_features, compute_label, required_lookback
from model_io import LinearModelPayload, save_linear_model
from torch_model import TorchMLP


@dataclass
class Window:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp


def _parse_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _standardize(
    df: pd.DataFrame, feature_cols: list[str]
) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    mean = df[feature_cols].mean().to_dict()
    std = df[feature_cols].std().replace(0, np.nan).to_dict()
    scaled = df.copy()
    for col in feature_cols:
        scaled[col] = (scaled[col] - mean[col]) / (std[col] if std[col] else 1.0)
    return scaled, mean, std


def _train_loop(
    model: nn.Module,
    train_loader: DataLoader,
    valid_loader: DataLoader,
    config: dict,
    device: torch.device,
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
    args = parser.parse_args()

    config_path = Path(args.config)
    config = _parse_config(config_path)
    data_root = Path(args.data_root) if args.data_root else _data_root_from_config(config)
    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"缺少目录: {adjusted_dir}")

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

    spy_path = _pick_dataset_file(benchmark_symbol, adjusted_dir, vendor_pref)
    if not spy_path:
        raise RuntimeError(f"未找到基准数据: {benchmark_symbol}")
    spy_df = _load_series(spy_path)

    dataset = []
    for symbol in symbols:
        symbol_path = _pick_dataset_file(symbol, adjusted_dir, vendor_pref)
        if not symbol_path:
            continue
        df = _load_series(symbol_path)
        features = compute_features(df, spy_df, feat_config)
        label = compute_label(df, spy_df, horizon)
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
    window = _build_window(data.index, config.get("walk_forward", {}), lookback)
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

    batch_size = int(config.get("torch", {}).get("batch_size", 512))
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

    device = torch.device("cuda" if (args.device == "auto" and torch.cuda.is_available()) else "cpu")
    torch_config = config.get("torch", {})
    model = TorchMLP(
        input_dim=len(feature_cols),
        hidden=torch_config.get("hidden", [64, 32]),
        dropout=float(torch_config.get("dropout", 0.1)),
    ).to(device)

    metrics = _train_loop(model, train_loader, valid_loader, torch_config, device)

    output_dir = Path(config.get("output_dir", "ml/models"))
    output_dir.mkdir(parents=True, exist_ok=True)
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

    print(f"saved model: {output_dir / 'torch_model.pt'}")
    print(f"saved payload: {output_dir / 'torch_payload.json'}")


if __name__ == "__main__":
    main()
