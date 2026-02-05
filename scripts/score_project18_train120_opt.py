from __future__ import annotations

import json
from pathlib import Path

from app.services.backtest_opt_cagr import score_manifest

MANIFEST = Path("/app/stocklean/artifacts/train120_opt_manifest.jsonl")
ARTIFACTS = Path("/app/stocklean/artifacts")


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit(f"manifest not found: {MANIFEST}")
    results = score_manifest(MANIFEST, artifacts_root=ARTIFACTS, max_dd=0.15, limit=3)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
