import json
from pathlib import Path


def test_theme_keywords_contains_ai_collection():
    path = Path(__file__).resolve().parents[2] / "configs" / "theme_keywords.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    categories = payload.get("categories") or []
    match = [c for c in categories if c.get("key") == "AI_COLLECTION"]
    assert match, "AI_COLLECTION not found"
    item = match[0]
    assert item.get("label") == "人工智能集合"
    manual = item.get("manual") or []
    for symbol in ("NVDA", "TSM", "MSFT", "EQIX", "ETN"):
        assert symbol in manual
