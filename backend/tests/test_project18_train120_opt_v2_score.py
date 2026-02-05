from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts import score_project18_train120_opt_v2


def test_v2_manifest_path() -> None:
    assert (
        str(score_project18_train120_opt_v2.MANIFEST)
        == "/app/stocklean/artifacts/train120_opt_v2_manifest.jsonl"
    )
