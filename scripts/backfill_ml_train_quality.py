from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.db import get_session
from app.models import MLTrainJob
from app.services.ml_quality import attach_train_quality


def _needs_update(metrics: dict[str, Any] | None, force: bool) -> bool:
    if force:
        return True
    if not isinstance(metrics, dict):
        return False
    return metrics.get("quality_score") is None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    updated = 0
    scanned = 0
    with get_session() as session:
        query = session.query(MLTrainJob)
        if args.project_id:
            query = query.filter(MLTrainJob.project_id == args.project_id)
        for job in query.order_by(MLTrainJob.id.asc()):
            scanned += 1
            metrics = job.metrics if isinstance(job.metrics, dict) else None
            if not _needs_update(metrics, args.force):
                continue
            if metrics is None:
                continue
            enriched = attach_train_quality(metrics, job.config if isinstance(job.config, dict) else None)
            if enriched is None:
                continue
            if args.dry_run:
                updated += 1
                continue
            job.metrics = dict(enriched)
            flag_modified(job, "metrics")
            updated += 1
        if not args.dry_run:
            session.commit()

    print(f"scanned={scanned} updated={updated} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
