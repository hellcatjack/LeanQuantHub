# PreTrade Lean Bridge 门禁实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 PreTrade 周度检查中新增“数据门禁 + Lean Bridge 交易门禁”，硬阻断交易执行并在数据页清晰展示原因。

**Architecture:** 在 PreTrade 执行链路中新增 `bridge_gate` 步骤，基于 Lean Bridge 输出文件判定交易就绪；数据门禁仍依赖 Alpha/PIT 完整性。门禁阈值落地到 `PreTradeSettings` 并记录到 `PreTradeStep.artifacts`，前端以“数据门禁/交易门禁”两段摘要展示。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, React + Vite, Playwright, pytest

---

### Task 1: 增加 PreTradeSettings 门禁阈值字段

**Files:**
- Create: `deploy/mysql/patches/20260126_pretrade_bridge_gate.sql`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/pretrade.py`
- Test: `backend/tests/test_pretrade_settings.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_pretrade_settings.py

def test_pretrade_settings_bridge_gate_fields_present():
    settings = pretrade_routes.get_pretrade_settings()
    assert hasattr(settings, "bridge_heartbeat_ttl_seconds")
    assert hasattr(settings, "bridge_account_ttl_seconds")
    assert hasattr(settings, "bridge_positions_ttl_seconds")
    assert hasattr(settings, "bridge_quotes_ttl_seconds")
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_pretrade_settings.py::test_pretrade_settings_bridge_gate_fields_present -v`
Expected: FAIL with attribute missing

**Step 3: Write minimal implementation**

```python
# backend/app/models.py (PreTradeSettings)
bridge_heartbeat_ttl_seconds = Column(Integer, default=60)
bridge_account_ttl_seconds = Column(Integer, default=300)
bridge_positions_ttl_seconds = Column(Integer, default=300)
bridge_quotes_ttl_seconds = Column(Integer, default=60)
```

```python
# backend/app/schemas.py (PreTradeSettingsOut/Update)
bridge_heartbeat_ttl_seconds: int | None = None
bridge_account_ttl_seconds: int | None = None
bridge_positions_ttl_seconds: int | None = None
bridge_quotes_ttl_seconds: int | None = None
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_pretrade_settings.py::test_pretrade_settings_bridge_gate_fields_present -v`
Expected: PASS

**Step 5: Commit**

```bash
git add deploy/mysql/patches/20260126_pretrade_bridge_gate.sql backend/app/models.py backend/app/schemas.py backend/app/routes/pretrade.py backend/tests/test_pretrade_settings.py
git commit -m "feat(pretrade): add bridge gate ttl settings"
```

---

### Task 2: 新增 PreTrade `bridge_gate` 步骤并加入执行序列

**Files:**
- Modify: `backend/app/services/lean_bridge_reader.py`
- Modify: `backend/app/services/pretrade_runner.py`
- Test: `backend/tests/test_pretrade_bridge_gate.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_pretrade_bridge_gate.py

def test_bridge_gate_fails_when_quotes_stale(tmp_path, monkeypatch):
    # arrange stale bridge files
    # expect RuntimeError("bridge_gate_failed")
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_pretrade_bridge_gate.py::test_bridge_gate_fails_when_quotes_stale -v`
Expected: FAIL (function missing)

**Step 3: Write minimal implementation**

```python
# backend/app/services/pretrade_runner.py

def step_bridge_gate(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    settings = _get_or_create_settings(ctx.session)
    # read lean bridge files and evaluate ttl thresholds
    # if any stale/missing -> raise RuntimeError("bridge_gate_failed")
    return StepResult(artifacts={"bridge_gate": {...}})

STEP_DEFS = [
    ("calendar_refresh", step_calendar_refresh),
    ...,
    ("bridge_gate", step_bridge_gate),
    ("market_snapshot", step_market_snapshot),
    ("trade_execute", step_trade_execute),
    ...,
]
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_pretrade_bridge_gate.py::test_bridge_gate_fails_when_quotes_stale -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/lean_bridge_reader.py backend/app/services/pretrade_runner.py backend/tests/test_pretrade_bridge_gate.py
git commit -m "feat(pretrade): add lean bridge gate step"
```

---

### Task 3: PreTrade 步骤与模板/文本对齐（UI & i18n）

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/data-page.spec.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/data-page.spec.ts
// expect "Bridge Gate" step name visible in PreTrade steps list
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- data-page.spec.ts`
Expected: FAIL (text not found)

**Step 3: Write minimal implementation**

```ts
// frontend/src/pages/DataPage.tsx
// include bridge_gate in PRETRADE_STEP_KEYS and step groups
```

```ts
// frontend/src/i18n.tsx
// add data.pretrade.steps.bridge_gate + desc
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- data-page.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/DataPage.tsx frontend/src/i18n.tsx frontend/tests/data-page.spec.ts
git commit -m "feat(pretrade-ui): add bridge gate step labels"
```

---

### Task 4: 数据页展示“数据门禁/交易门禁”摘要

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/data-page-pagination.spec.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/data-page-pagination.spec.ts
// expect "Data Gate" and "Trade Gate" summary blocks visible
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- data-page-pagination.spec.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```ts
// DataPage.tsx
// derive summary from pretradeRunDetail.steps -> show data gate / trade gate status
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- data-page-pagination.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/DataPage.tsx frontend/src/i18n.tsx frontend/tests/data-page-pagination.spec.ts
git commit -m "feat(data-ui): show pretrade data/trade gates"
```

---

### Task 5: 文档与验收对齐

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`
- Modify: `docs/todolists/PreTradeDataSyncTODO.md`

**Step 1: Update docs**

- 在 IBAutoTradeTODO 增加 PreTrade 门禁条目（数据/交易双门禁、阈值、UI 展示）。
- 在 PreTradeDataSyncTODO 增加“交易门禁”说明与验收标准。

**Step 2: Commit**

```bash
git add docs/todolists/IBAutoTradeTODO.md docs/todolists/PreTradeDataSyncTODO.md
git commit -m "docs: add pretrade data+trade gate requirements"
```

---

## Verification Checklist
- `cd backend && pytest tests/test_pretrade_settings.py tests/test_pretrade_bridge_gate.py -v`
- `cd frontend && npm run test -- data-page.spec.ts`
- `cd frontend && npm run test -- data-page-pagination.spec.ts`
- UI 验证：数据页 PreTrade 区域可见“数据门禁/交易门禁”状态与更新时间

