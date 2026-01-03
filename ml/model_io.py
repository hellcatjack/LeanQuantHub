from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class LinearModelPayload:
    model_type: str
    features: list[str]
    coef: list[float]
    intercept: float
    mean: dict[str, float]
    std: dict[str, float]
    label_horizon_days: int
    trained_at: str
    train_window: dict[str, str]


def save_linear_model(path: Path, payload: LinearModelPayload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_linear_model(path: Path) -> LinearModelPayload:
    data = json.loads(path.read_text(encoding="utf-8"))
    return LinearModelPayload(**data)
