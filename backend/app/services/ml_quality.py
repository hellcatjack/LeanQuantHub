from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


DEFAULT_TRAIN_QUALITY_WEIGHTS: dict[str, float] = {
    "ndcg_at_10": 0.2,
    "ndcg_at_50": 0.4,
    "ndcg_at_100": 0.1,
    "ic": 0.15,
    "rank_ic": 0.15,
    "curve_gap": 0.2,
}

DEFAULT_TRAIN_QUALITY_CONFIG: dict[str, float] = {
    "curve_gap_scale": 0.2,
}


@dataclass
class TrainQualityResult:
    score: float | None
    curve_gap: float | None
    inputs: dict[str, float | None]
    normalized: dict[str, float | None]
    weights: dict[str, float]
    weight_sum: float
    notes: list[str]


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_metric(metrics: dict[str, Any], key: str) -> float | None:
    if key in metrics:
        return _safe_float(metrics.get(key))
    camel_key = "".join(
        part.capitalize() if idx > 0 else part
        for idx, part in enumerate(key.split("_"))
    )
    if camel_key in metrics:
        return _safe_float(metrics.get(camel_key))
    return None


def _extract_metric_from_windows(metrics: dict[str, Any], key: str) -> float | None:
    windows = metrics.get("walk_forward", {}).get("windows") or metrics.get("walkForward", {}).get("windows")
    if not isinstance(windows, list) or not windows:
        return None
    values: list[float] = []
    for item in windows:
        if not isinstance(item, dict):
            continue
        value = _safe_float(item.get(key))
        if value is not None:
            values.append(value)
            continue
        camel_key = "".join(
            part.capitalize() if idx > 0 else part
            for idx, part in enumerate(key.split("_"))
        )
        value = _safe_float(item.get(camel_key))
        if value is not None:
            values.append(value)
    if not values:
        return None
    return float(np.mean(values))


def _compute_curve_gap(metrics: dict[str, Any]) -> float | None:
    curve = metrics.get("curve") or metrics.get("walk_forward", {}).get("curve") or metrics.get("walkForward", {}).get("curve")
    if not isinstance(curve, dict):
        return None
    train = curve.get("train")
    valid = curve.get("valid")
    if not isinstance(train, list) or not isinstance(valid, list):
        return None
    length = min(len(train), len(valid))
    if length <= 0:
        return None
    gaps = []
    for idx in range(length):
        try:
            gap = float(train[idx]) - float(valid[idx])
        except (TypeError, ValueError):
            continue
        gaps.append(gap)
    if not gaps:
        return None
    return float(np.mean(gaps))


def compute_train_quality(
    metrics: dict[str, Any] | None,
    weights: dict[str, float] | None = None,
    config: dict[str, float] | None = None,
) -> TrainQualityResult | None:
    if not isinstance(metrics, dict):
        return None
    weights = dict(DEFAULT_TRAIN_QUALITY_WEIGHTS if weights is None else weights)
    config = dict(DEFAULT_TRAIN_QUALITY_CONFIG if config is None else config)

    inputs: dict[str, float | None] = {}
    for key in ("ndcg_at_10", "ndcg_at_50", "ndcg_at_100", "ic", "rank_ic"):
        value = _extract_metric(metrics, key)
        if value is None:
            value = _extract_metric_from_windows(metrics, key)
        inputs[key] = value

    curve_gap = _extract_metric(metrics, "curve_gap")
    if curve_gap is None:
        curve_gap = _compute_curve_gap(metrics)
    inputs["curve_gap"] = curve_gap

    normalized: dict[str, float | None] = {}
    notes: list[str] = []

    for key in ("ndcg_at_10", "ndcg_at_50", "ndcg_at_100"):
        value = inputs.get(key)
        normalized[key] = value if value is not None else None

    for key in ("ic", "rank_ic"):
        value = inputs.get(key)
        if value is None:
            normalized[key] = None
            continue
        normalized[key] = max(min((value + 1.0) / 2.0, 1.0), 0.0)

    gap_scale = float(config.get("curve_gap_scale") or 0.2)
    gap_value = inputs.get("curve_gap")
    if gap_value is None:
        normalized["curve_gap"] = None
    else:
        normalized["curve_gap"] = max(min(max(gap_value, 0.0) / max(gap_scale, 1e-6), 1.0), 0.0)

    positive_weight = 0.0
    score_raw = 0.0
    for key, weight in weights.items():
        if weight == 0:
            continue
        value = normalized.get(key)
        if value is None:
            continue
        if key == "curve_gap":
            score_raw -= weight * value
            continue
        score_raw += weight * value
        positive_weight += weight

    if positive_weight <= 0:
        return TrainQualityResult(
            score=None,
            curve_gap=curve_gap,
            inputs=inputs,
            normalized=normalized,
            weights=weights,
            weight_sum=0.0,
            notes=["missing_primary_metrics"],
        )

    score = score_raw / positive_weight * 100.0
    return TrainQualityResult(
        score=score,
        curve_gap=curve_gap,
        inputs=inputs,
        normalized=normalized,
        weights=weights,
        weight_sum=positive_weight,
        notes=notes,
    )


def attach_train_quality(metrics: dict[str, Any] | None, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return metrics
    scoring_cfg = {}
    if isinstance(config, dict):
        scoring_cfg = config.get("train_quality") or {}
    weights = scoring_cfg.get("weights") if isinstance(scoring_cfg, dict) else None
    gap_scale = None
    if isinstance(scoring_cfg, dict):
        gap_scale = scoring_cfg.get("curve_gap_scale")
    cfg = dict(DEFAULT_TRAIN_QUALITY_CONFIG)
    if gap_scale is not None:
        try:
            cfg["curve_gap_scale"] = float(gap_scale)
        except (TypeError, ValueError):
            pass
    result = compute_train_quality(metrics, weights=weights, config=cfg)
    if result is None:
        return metrics
    if result.curve_gap is not None:
        metrics["curve_gap"] = result.curve_gap
    metrics["quality_score"] = result.score
    metrics["quality_detail"] = {
        "inputs": result.inputs,
        "normalized": result.normalized,
        "weights": result.weights,
        "weight_sum": result.weight_sum,
        "curve_gap_scale": cfg.get("curve_gap_scale"),
        "score": result.score,
        "notes": result.notes,
    }
    return metrics
