# Data Sync Orphan Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 基于“队列空闲 + 任务落盘证据”的联合信号，自动回收 bulk_sync 中的孤儿 data_sync_jobs，解除 PreTrade 阻塞。

**Architecture:** 在 bulk_sync 的 `syncing` 循环内加入孤儿评估器；评估器读取配置、检查队列空闲、搜集证据并写审计，必要时标记失败。

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, pytest, JSON 配置。

---

## Task 1: Orphan Guard 配置加载器

**Files:**
- Create: `backend/app/services/data_sync_orphan_guard.py`
- Test: `backend/tests/test_data_sync_orphan_guard.py`

**Step 1: 写失败测试**

```python
import json
from app.services.data_sync_orphan_guard import load_data_sync_orphan_guard_config


def test_orphan_guard_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    cfg = load_data_sync_orphan_guard_config()
    assert cfg["enabled"] is True
    assert cfg["dry_run"] is False
    assert cfg["evidence_required"] is True


def test_orphan_guard_load_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    cfg_path = tmp_path / "config" / "data_sync_orphan_guard.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"enabled": False, "dry_run": True}))
    cfg = load_data_sync_orphan_guard_config()
    assert cfg["enabled"] is False
    assert cfg["dry_run"] is True
```

**Step 2: 运行测试（应失败）**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: FAIL（模块不存在）

**Step 3: 最小实现**

```python
from app.core.config import settings

DEFAULT_ORPHAN_GUARD = {
    "enabled": True,
    "dry_run": False,
    "evidence_required": True,
}

# 解析 DATA_ROOT 与 JSON 配置
```

**Step 4: 运行测试（应通过）**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: PASS

**Step 5: 提交**

```bash
git add backend/app/services/data_sync_orphan_guard.py backend/tests/test_data_sync_orphan_guard.py
git commit -m "feat: add data sync orphan guard config loader"
```

---

## Task 2: 证据检索与判定辅助函数

**Files:**
- Modify: `backend/app/routes/datasets.py`
- Test: `backend/tests/test_data_sync_orphan_guard.py`

**Step 1: 写失败测试**

```python
from app.routes.datasets import _find_sync_job_evidence, _should_orphan_candidates


def test_orphan_evidence_detects_outputs(tmp_path):
    (tmp_path / "curated").mkdir(parents=True)
    (tmp_path / "curated" / "125_Alpha_X_Daily.csv").write_text("x")
    evidence = _find_sync_job_evidence(tmp_path, dataset_id=125, source_path="alpha:x")
    assert any("curated" in item for item in evidence)


def test_should_orphan_candidates_logic():
    assert _should_orphan_candidates(pending=0, running_total=2, candidate_count=2) is True
    assert _should_orphan_candidates(pending=1, running_total=2, candidate_count=2) is False
    assert _should_orphan_candidates(pending=0, running_total=3, candidate_count=2) is False
```

**Step 2: 运行测试（应失败）**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: FAIL（函数缺失）

**Step 3: 最小实现**

```python
# datasets.py
from app.services.data_sync_orphan_guard import load_data_sync_orphan_guard_config

# _find_sync_job_evidence / _should_orphan_candidates
```

**Step 4: 运行测试（应通过）**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: PASS

**Step 5: 提交**

```bash
git add backend/app/routes/datasets.py backend/tests/test_data_sync_orphan_guard.py
git commit -m "feat: add orphan evidence helpers"
```

---

## Task 3: bulk_sync 中接入孤儿回收逻辑

**Files:**
- Modify: `backend/app/routes/datasets.py`
- Test: `backend/tests/test_data_sync_orphan_guard.py`

**Step 1: 写失败测试**

```python
from app.routes import datasets as datasets_routes

# 使用 FakeSession + monkeypatch 验证 _evaluate_orphaned_sync_jobs
```

**Step 2: 运行测试（应失败）**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: FAIL（评估器缺失）

**Step 3: 最小实现**

```python
# datasets.py
# _is_sync_queue_idle + _evaluate_orphaned_sync_jobs
# 在 bulk_sync syncing 循环中调用评估器
```

**Step 4: 运行测试（应通过）**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: PASS

**Step 5: 提交**

```bash
git add backend/app/routes/datasets.py backend/tests/test_data_sync_orphan_guard.py
git commit -m "feat: auto-recover orphaned data sync jobs"
```

---

## Task 4: 设计文档对齐与收尾

**Files:**
- Modify: `docs/plans/2026-01-27-data-sync-orphan-guard-design.md`

**Step 1: 对齐判定信号描述**
- 将 B 信号改为“队列空闲 + 锁可获取”，与实现一致。

**Step 2: 验证测试**

Run:
```
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_data_sync_orphan_guard.py
```
Expected: PASS

**Step 3: 提交**

```bash
git add docs/plans/2026-01-27-data-sync-orphan-guard-design.md
git commit -m "docs: align orphan guard signal definition"
```
