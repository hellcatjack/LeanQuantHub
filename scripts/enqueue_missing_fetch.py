#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'").strip('"')
    return env


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--actions",
        type=str,
        default="",
        help="missing_symbol_actions.csv 路径",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="US",
        help="地区（默认 US）",
    )
    parser.add_argument(
        "--reset-history",
        action="store_true",
        help="清空历史后重新抓取",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / "backend" / ".env"
    env = load_env(env_path)
    for key, value in env.items():
        os.environ.setdefault(key, value)

    sys.path.insert(0, str(project_root / "backend"))

    from app.db import get_session  # noqa: WPS433
    from app.models import DataSyncJob, Dataset  # noqa: WPS433
    from app.routes.datasets import (  # noqa: WPS433
        ACTIVE_SYNC_STATUSES,
        _is_alpha_source,
        _resolve_market_source,
    )
    from app.services.audit_log import record_audit  # noqa: WPS433

    data_root = env.get("DATA_ROOT")
    if not data_root:
        raise SystemExit("DATA_ROOT is not set in backend/.env")
    data_root_path = Path(data_root)
    actions_path = (
        Path(args.actions).expanduser().resolve()
        if args.actions
        else data_root_path / "universe" / "missing_symbol_actions.csv"
    )

    rows = read_csv(actions_path)
    if not rows:
        raise SystemExit(f"missing_symbol_actions not found: {actions_path}")

    vendor_label = "Alpha"
    frequency = "daily"
    default_region = args.region.strip().upper() or "US"
    date_column = "timestamp"
    reset_history = bool(args.reset_history)

    created = 0
    updated = 0
    queued = 0
    skipped = 0
    reused = 0

    with get_session() as session:
        for row in rows:
            action = (row.get("action") or "").strip().lower()
            if action != "fetch":
                continue
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            region = (row.get("region") or "").strip().upper() or default_region
            asset_type = (row.get("asset_type") or "").strip().upper()
            asset_class = "ETF" if asset_type == "ETF" else "Equity"
            source_path = f"alpha:{symbol.lower()}"
            dataset_name = f"{vendor_label}_{symbol}_Daily"

            dataset = (
                session.query(Dataset)
                .filter(
                    Dataset.source_path == source_path,
                    Dataset.vendor == vendor_label,
                    Dataset.frequency == frequency,
                    Dataset.region == region,
                )
                .first()
            )
            if not dataset:
                dataset = session.query(Dataset).filter(Dataset.name == dataset_name).first()

            if not dataset:
                dataset = Dataset(
                    name=dataset_name,
                    vendor=vendor_label,
                    asset_class=asset_class,
                    region=region,
                    frequency=frequency,
                    source_path=source_path,
                )
                session.add(dataset)
                session.commit()
                session.refresh(dataset)
                created += 1
                record_audit(
                    session,
                    action="dataset.create",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    detail={"name": dataset.name, "source": "missing_fetch"},
                )
                session.commit()
            else:
                reused += 1
                changed = False
                if asset_class and dataset.asset_class != asset_class:
                    dataset.asset_class = asset_class
                    changed = True
                if region and dataset.region != region:
                    dataset.region = region
                    changed = True
                if not dataset.frequency and frequency:
                    dataset.frequency = frequency
                    changed = True
                if not dataset.source_path and source_path:
                    dataset.source_path = source_path
                    changed = True
                if changed:
                    dataset.updated_at = datetime.utcnow()
                    record_audit(
                        session,
                        action="dataset.update",
                        resource_type="dataset",
                        resource_id=dataset.id,
                        detail={"source_path": source_path},
                    )
                    session.commit()
                    updated += 1

            stored_source = _resolve_market_source(dataset, source_path)
            if _is_alpha_source(stored_source):
                date_column = "timestamp"
            existing = (
                session.query(DataSyncJob)
                .filter(
                    DataSyncJob.dataset_id == dataset.id,
                    DataSyncJob.source_path == stored_source,
                    DataSyncJob.date_column == date_column,
                    DataSyncJob.reset_history == reset_history,
                    DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
                )
                .order_by(DataSyncJob.created_at.desc())
                .first()
            )
            if existing:
                skipped += 1
                continue

            job = DataSyncJob(
                dataset_id=dataset.id,
                source_path=stored_source,
                date_column=date_column,
                reset_history=reset_history,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            record_audit(
                session,
                action="data.sync.create",
                resource_type="data_sync_job",
                resource_id=job.id,
                detail={"dataset_id": dataset.id, "source_path": job.source_path},
            )
            session.commit()
            queued += 1

    print(f"missing fetch actions: {actions_path}")
    print(f"datasets created: {created}")
    print(f"datasets reused: {reused}")
    print(f"datasets updated: {updated}")
    print(f"sync jobs queued: {queued}")
    print(f"sync jobs skipped (active): {skipped}")


if __name__ == "__main__":
    main()
