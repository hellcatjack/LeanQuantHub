import json
from pathlib import Path


def test_theme_keywords_contains_ai_companion():
    path = Path(__file__).resolve().parents[2] / "configs" / "theme_keywords.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    categories = payload.get("categories") or []
    match = [c for c in categories if c.get("key") == "AI_COMPANION"]
    assert match, "AI_COMPANION not found"
    item = match[0]
    assert item.get("label") == "AI 搭配组合"
    manual = item.get("manual") or []
    for symbol in ("BRK.B", "JPM", "XOM", "XLU", "TMO"):
        assert symbol in manual
