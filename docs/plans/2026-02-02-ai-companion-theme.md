# AI 搭配组合主题 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增独立主题“AI 搭配组合（AI_COMPANION）”，包含用户给定的非科技/防御/金融/周期/ETF等标的，用于与 AI 主题搭配。

**Architecture:** 通过 `configs/theme_keywords.json` 增加新分类；后端主题加载沿用现有配置读取逻辑。新增最小化测试校验主题 key/label 与关键标的存在。

**Tech Stack:** FastAPI + JSON 配置 + pytest.

---

### Task 1: 添加失败测试（主题存在性）

**Files:**
- Create: `backend/tests/test_theme_keywords_ai_companion.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_theme_keywords_ai_companion.py -v`
Expected: FAIL (AI_COMPANION not found)

---

### Task 2: 新增 AI_COMPANION 主题配置

**Files:**
- Modify: `configs/theme_keywords.json`

**Step 1: Update config**

在 `categories` 末尾新增：
- key: `AI_COMPANION`
- label: `AI 搭配组合`
- keywords: `[]`
- manual: 全量标的（统一大写，修正异常字符）

**Step 2: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_theme_keywords_ai_companion.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add configs/theme_keywords.json backend/tests/test_theme_keywords_ai_companion.py
git commit -m "feat: add AI companion theme"
```

---

### Task 3: 验证与收尾

**Step 1: （可选）刷新系统主题缓存**

若需要验证前端主题列表变化，可重启后端或触发主题刷新接口。

---

**交付物**
- 新主题：AI_COMPANION（AI 搭配组合）
- 最小化测试保证主题存在性

**执行后验证**
- 后端主题列表返回包含 AI_COMPANION
- 关键标的（BRK.B/JPM/XOM/XLU/TMO）存在
