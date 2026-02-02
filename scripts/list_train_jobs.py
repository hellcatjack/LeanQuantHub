from __future__ import annotations

import json
from typing import Iterable
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8021"
PROJECT_ID = 18


def _get_json(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_train_job_ids(items: Iterable[dict]) -> list[int]:
    return [int(row["id"]) for row in items if row.get("status") == "success"]


def main() -> None:
    page = 1
    ids: list[int] = []
    while True:
        data = _get_json(
            f"{API}/api/ml/train_jobs/page?project_id={PROJECT_ID}&page={page}&page_size=200"
        )
        items = data.get("items") or []
        ids.extend(extract_train_job_ids(items))
        if len(items) < 200:
            break
        page += 1
    print("\n".join(str(i) for i in ids))


if __name__ == "__main__":
    main()
