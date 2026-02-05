import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "ml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import train_torch


def test_extract_lgbm_ndcg_curves_from_evals():
    evals = {
        "valid_0": {
            "ndcg@10": [0.1, 0.2, 0.25],
            "ndcg@50": [0.3, 0.31, 0.33],
            "ndcg@100": [0.4, 0.41, 0.42],
        }
    }
    payload = train_torch._build_ndcg_curve_payload(evals)
    assert payload is not None
    assert payload["iterations"] == [1, 2, 3]
    assert payload["valid"]["ndcg@10"] == [0.1, 0.2, 0.25]
    assert payload["valid"]["ndcg@50"] == [0.3, 0.31, 0.33]
    assert payload["valid"]["ndcg@100"] == [0.4, 0.41, 0.42]


def test_attach_ndcg_curve_payload_in_metrics():
    evals = {
        "valid": {
            "ndcg@10": [0.1],
            "ndcg@50": [0.2],
            "ndcg@100": [0.3],
        }
    }
    metrics = {}
    train_torch._attach_ndcg_curve(metrics, evals)
    assert metrics["curve_ndcg"]["iterations"] == [1]
