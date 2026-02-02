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


def build_page_url(project_id: int, page: int, page_size: int) -> str:
    return (
        f"{API}/api/ml/train-jobs/page"
        f"?project_id={project_id}&page={page}&page_size={page_size}"
    )


def main() -> None:
    page = 1
    ids: list[int] = []
    while True:
        data = _get_json(build_page_url(PROJECT_ID, page, 200))
        items = data.get("items") or []
        ids.extend(extract_train_job_ids(items))
        if len(items) < 200:
            break
        page += 1
    print("\n".join(str(i) for i in ids))


if __name__ == "__main__":
    main()
