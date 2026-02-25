from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.services.trade_riskoff_validation import validate_trade_run_riskoff_alignment  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate risk-off trade run alignment against defensive basket targets.",
    )
    parser.add_argument("--run-id", type=int, default=None, help="Trade run id to validate.")
    parser.add_argument("--project-id", type=int, default=None, help="Use latest trade run from project id.")
    parser.add_argument(
        "--risk-off-only",
        action="store_true",
        help="Auto-select latest trade run whose snapshot has risk_off=true (within project filter if provided).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat skipped results as failure exit code.",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = validate_trade_run_riskoff_alignment(
            session,
            run_id=args.run_id,
            project_id=args.project_id,
            risk_off_only=args.risk_off_only,
        )
    finally:
        session.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = str(result.get("status") or "").strip().lower()
    if status == "error":
        return 3
    if status == "failed":
        return 2
    if status == "skipped" and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
