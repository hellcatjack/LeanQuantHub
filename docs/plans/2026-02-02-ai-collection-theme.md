# 人工智能集合主题 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增一个独立主题“人工智能集合（AI_COLLECTION）”，包含用户提供的全部标的（含可选 INTC/GFS/SU）。

**Architecture:** 通过 `configs/theme_keywords.json` 增加新分类；后端主题加载沿用现有配置读取逻辑。新增一个最小化测试校验主题 key/label 与关键标的存在。

**Tech Stack:** FastAPI + JSON 配置 + pytest.

---

### Task 1: 添加失败测试（主题存在性）

**Files:**
- Create: `backend/tests/test_theme_keywords_ai_collection.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_theme_keywords_ai_collection.py -v`
Expected: FAIL (AI_COLLECTION not found)

---

### Task 2: 新增 AI_COLLECTION 主题配置

**Files:**
- Modify: `configs/theme_keywords.json`

**Step 1: Update config**

在 `categories` 末尾新增：
- key: `AI_COLLECTION`
- label: `人工智能集合`
- keywords: `[]`（可空）
- manual: 全量标的（统一大写，移除无效字符，如 `AZZ)` → `AZZ`）

完整 manual 列表（按用户给定）：
```
NVDA, AMD, AVGO, MRVL, MU, TSM, ASML, AMAT, LRCX, KLAC, SNPS, CDNS, ARM, INTC, GFS,
MSFT, AMZN, GOOGL, META, ORCL, IBM,
PLTR, SNOW, DDOG, MDB, NOW, CRM, CRWD, PANW, ZS,
EQIX, DLR, IRM, VRT, SMCI, DELL, HPE, TT, JCI,
ANET, CSCO, JNPR, CIEN, LITE, GLW,
ETN, ABB, SU, PWR, EME, WCC, POWL, AZZ, PH,
FSLR, ENPH, SEDG, NXT, ARRY,
CVX, LIN, GTLS, BWXT
```

**Step 2: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_theme_keywords_ai_collection.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add configs/theme_keywords.json backend/tests/test_theme_keywords_ai_collection.py
git commit -m "feat: add AI collection theme"
```

---

### Task 3: 验证与收尾

**Step 1: （可选）刷新系统主题缓存**

若需要验证前端主题列表变化，可重启后端或触发主题刷新接口。

---

**交付物**
- 新主题：AI_COLLECTION（人工智能集合）
- 最小化测试保证主题存在性

**执行后验证**
- 后端主题列表返回包含 AI_COLLECTION
- 关键标的（NVDA/TSM/MSFT/EQIX/ETN）存在
