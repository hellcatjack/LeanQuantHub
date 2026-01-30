# Lean Bridge Watchlist Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 Lean Bridge Leader watchlist 生成逻辑（来源为项目统一 universe），并限制总量上限 200，确保稳定、去重与基准优先。

**Architecture:** 在 `project_symbols` 中新增“按项目轮询 + 基准优先 + 上限”构建函数，`lean_bridge_leader._write_watchlist()` 仅负责调用并写入文件，若内容未变则不写。

**Tech Stack:** Python 3.11, FastAPI backend, SQLAlchemy, pytest

---

### Task 1: 新增 watchlist 生成函数与单测（RED）

**Files:**
- Create: `backend/tests/test_lean_bridge_watchlist.py`
- Modify: `backend/app/services/project_symbols.py`

**Step 1: 写 failing test（上限+轮询+基准）**

```python
from app.services import project_symbols


def test_build_leader_watchlist_hard_cap_round_robin(monkeypatch):
    # 伪造项目与 symbols 输出
    projects = [
        {"id": 1, "benchmark": "SPY", "symbols": ["A", "B", "C", "D"]},
        {"id": 2, "benchmark": "QQQ", "symbols": ["A", "E", "F"]},
        {"id": 3, "benchmark": "IWM", "symbols": ["G"]},
    ]

    def _fake_collect_active(session):
        return projects

    monkeypatch.setattr(project_symbols, "_collect_active_project_watchlist_inputs", _fake_collect_active)

    result = project_symbols.build_leader_watchlist(None, max_symbols=5)
    # 基准优先且去重
    assert result[:3] == ["SPY", "QQQ", "IWM"]
    # 轮询填充（A/B/E 或 A/E/B，取决于排序规则，需与实现一致）
    assert len(result) == 5
    assert len(set(result)) == 5
```

**Step 2: 运行测试确认失败**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_watchlist.py::test_build_leader_watchlist_hard_cap_round_robin`
Expected: FAIL（函数未实现）

**Step 3: 再写 failing test（空 symbols fallback）**

```python

def test_build_leader_watchlist_fallback_spy(monkeypatch):
    def _fake_collect_active(session):
        return []

    monkeypatch.setattr(project_symbols, "_collect_active_project_watchlist_inputs", _fake_collect_active)
    result = project_symbols.build_leader_watchlist(None, max_symbols=200)
    assert result == ["SPY"]
```

**Step 4: 运行测试确认失败**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_watchlist.py::test_build_leader_watchlist_fallback_spy`
Expected: FAIL

---

### Task 2: 实现最小代码（GREEN）

**Files:**
- Modify: `backend/app/services/project_symbols.py`

**Step 1: 添加 helper**

```python
from collections import deque


def _collect_active_project_watchlist_inputs(session) -> list[dict]:
    projects = session.query(Project).filter(Project.is_archived.is_(False)).order_by(Project.id.asc()).all()
    items = []
    for project in projects:
        config = _resolve_project_config(session, project.id)
        symbols = collect_project_symbols(config)
        benchmark = str(config.get("benchmark") or "SPY").strip().upper()
        items.append({"id": project.id, "symbols": symbols, "benchmark": benchmark})
    return items


def build_leader_watchlist(session, *, max_symbols: int = 200) -> list[str]:
    items = _collect_active_project_watchlist_inputs(session)
    if not items:
        return ["SPY"]
    # 基准优先
    ordered = []
    seen = set()
    for item in items:
        bm = item.get("benchmark") or "SPY"
        bm = str(bm).strip().upper()
        if bm and bm not in seen:
            ordered.append(bm)
            seen.add(bm)
            if len(ordered) >= max_symbols:
                return ordered
    # 轮询
    queues = [deque(sorted({str(s).strip().upper() for s in item.get("symbols", []) if str(s).strip()})) for item in items]
    while len(ordered) < max_symbols:
        progressed = False
        for q in queues:
            while q:
                sym = q.popleft()
                if sym and sym not in seen:
                    ordered.append(sym)
                    seen.add(sym)
                    progressed = True
                    break
            if len(ordered) >= max_symbols:
                break
        if not progressed:
            break
    if not ordered:
        return ["SPY"]
    return ordered
```

**Step 2: 运行测试确认通过**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_watchlist.py`
Expected: PASS

---

### Task 3: 接入 `_write_watchlist()` 并保持“无变化不写”

**Files:**
- Modify: `backend/app/services/lean_bridge_leader.py`

**Step 1: 替换 watchlist 生成逻辑**

```python
from app.services.project_symbols import build_leader_watchlist


def _write_watchlist(session) -> Path:
    symbols = build_leader_watchlist(session, max_symbols=200)
    ... # 维持已有“无变化不写”逻辑
```

**Step 2: 运行测试确认通过**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_watchlist.py`
Expected: PASS

---

### Task 4: 提交改动

**Files:**
- Modify: `backend/app/services/project_symbols.py`
- Modify: `backend/app/services/lean_bridge_leader.py`
- Create: `backend/tests/test_lean_bridge_watchlist.py`

**Step 1: git add/commit**

```bash
git add backend/app/services/project_symbols.py backend/app/services/lean_bridge_leader.py backend/tests/test_lean_bridge_watchlist.py
git commit -m "feat: cap lean bridge watchlist and round-robin symbols"
```

---

### Task 5: 验证与说明

**Step 1: 运行验证**

```bash
PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_watchlist.py
```

**Step 2: 说明**
- 报告测试结果与任何 warning。
- 说明 watchlist 的上限与优先级策略。

