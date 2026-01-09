from __future__ import annotations

from typing import Any


def _parse_metric_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("%"):
        raw = raw[:-1]
        try:
            return float(raw.replace(",", "")) / 100.0
        except ValueError:
            return None
    if raw.startswith("$"):
        raw = raw[1:]
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


DEFAULT_BACKTEST_SCORE_WEIGHTS: dict[str, float] = {
    "cagr": 0.4,
    "sharpe": 0.3,
    "drawdown": 0.2,
    "turnover_week": 0.1,
}

DEFAULT_BACKTEST_SCORE_SCALES: dict[str, float] = {
    "cagr": 0.2,
    "sharpe": 2.0,
    "drawdown": 0.2,
    "turnover_week": 0.1,
}

DEFAULT_COMBINED_WEIGHT = 0.4


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def _normalize(value: float | None, scale: float) -> float | None:
    if value is None:
        return None
    return _clip(value / max(scale, 1e-9))


def compute_backtest_score(
    metrics: dict[str, Any] | None,
    weights: dict[str, float] | None = None,
    scales: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return None
    weights = dict(DEFAULT_BACKTEST_SCORE_WEIGHTS if weights is None else weights)
    scales = dict(DEFAULT_BACKTEST_SCORE_SCALES if scales is None else scales)

    inputs: dict[str, float | None] = {
        "cagr": _parse_metric_value(metrics.get("Compounding Annual Return")),
        "sharpe": _parse_metric_value(metrics.get("Sharpe Ratio")),
        "drawdown": _parse_metric_value(metrics.get("Drawdown")),
        "turnover_week": _parse_metric_value(metrics.get("Turnover_week")),
    }

    normalized: dict[str, float | None] = {
        key: _normalize(inputs[key], scales.get(key, 1.0))
        for key in inputs
    }

    score_raw = 0.0
    positive_weight = 0.0
    for key, weight in weights.items():
        value = normalized.get(key)
        if value is None:
            continue
        if key in {"drawdown", "turnover_week"}:
            score_raw -= weight * value
        else:
            score_raw += weight * value
            positive_weight += weight

    if positive_weight <= 0:
        return {
            "score": None,
            "inputs": inputs,
            "normalized": normalized,
            "weights": weights,
            "scales": scales,
        }

    score = score_raw / positive_weight * 100.0
    return {
        "score": score,
        "inputs": inputs,
        "normalized": normalized,
        "weights": weights,
        "scales": scales,
    }


def compute_combined_score(
    train_score: float | None,
    backtest_score: float | None,
    weight: float | None = None,
) -> float | None:
    if train_score is None and backtest_score is None:
        return None
    if train_score is None:
        return backtest_score
    if backtest_score is None:
        return train_score
    weight = DEFAULT_COMBINED_WEIGHT if weight is None else weight
    weight = min(max(weight, 0.0), 1.0)
    return train_score * weight + backtest_score * (1.0 - weight)
