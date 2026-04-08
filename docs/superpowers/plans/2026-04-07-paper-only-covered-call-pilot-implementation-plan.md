# Paper-Only Covered Call Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 StockLean 增加一条 `paper-only` 的备兑看涨试点后端链路，支持资格筛选、IB 期权链读取、候选合约推荐和 dry-run 审计产物。

**Architecture:** 新增独立的期权试点服务层，不污染现有股票交易主路径。试点链路读取当前持仓、open orders 和 Gateway 运行健康，再通过 IB 拉取期权链与报价，执行 covered call 资格判断和候选筛选，最后通过新 API 输出 dry-run 结果和 artifacts。

**Tech Stack:** Python 3.11, FastAPI, Pydantic, IB API read session helpers, pytest

---

## 文件结构

- Create: `backend/app/services/trade_option_models.py`
  - 定义 covered call pilot 的请求/响应和内部数据结构。
- Create: `backend/app/services/ib_options_market.py`
  - 封装 IB 期权链、合约详情、报价读取。
- Create: `backend/app/services/options_eligibility.py`
  - 根据持仓、挂单、运行健康判断标的资格。
- Create: `backend/app/services/covered_call_planner.py`
  - 负责候选合约过滤和最终推荐。
- Create: `backend/app/services/covered_call_pilot.py`
  - 编排资格判断、IB 读取、筛选和 artifact 落盘。
- Modify: `backend/app/services/ib_read_session.py`
  - 新增最小期权链/合约/报价读取能力，不影响现有股票路径。
- Modify: `backend/app/routes/trade.py`
  - 新增 `POST /api/trade/options/covered-call/pilot`。
- Modify: `backend/app/schemas.py`
  - 新增 pilot API schema。
- Create: `backend/tests/test_trade_option_models.py`
- Create: `backend/tests/test_ib_options_market.py`
- Create: `backend/tests/test_options_eligibility.py`
- Create: `backend/tests/test_covered_call_planner.py`
- Create: `backend/tests/test_covered_call_pilot_route.py`

---

### Task 1: 定义期权试点数据模型与 API Schema

**Files:**
- Create: `backend/app/services/trade_option_models.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_option_models.py`

- [ ] **Step 1: 先写失败测试，锁定最小请求/响应结构**

```python
from app.services.trade_option_models import CoveredCallPilotRequest, CoveredCallRecommendation


def test_covered_call_models_default_to_paper_dry_run():
    payload = CoveredCallPilotRequest()
    assert payload.mode == "paper"
    assert payload.dry_run is True
    assert payload.dte_min == 21
    assert payload.dte_max == 45
    assert payload.max_spread_ratio == 0.15


def test_covered_call_recommendation_serializes_contract_shape():
    rec = CoveredCallRecommendation(
        symbol="AAPL",
        shares=200,
        coverable_contracts=2,
        expiry="2026-05-15",
        strike=230.0,
        right="C",
        contracts=2,
        bid=1.2,
        ask=1.3,
        mid=1.25,
    )
    assert rec.right == "C"
    assert rec.contracts == 2
    assert rec.mid == 1.25
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_trade_option_models.py -q
```

Expected:
```text
E   ModuleNotFoundError: No module named 'app.services.trade_option_models'
```

- [ ] **Step 3: 写最小实现**

`backend/app/services/trade_option_models.py`
```python
from __future__ import annotations

from pydantic import BaseModel, Field


class CoveredCallPilotRequest(BaseModel):
    mode: str = "paper"
    symbols: list[str] = Field(default_factory=list)
    max_candidates_per_symbol: int = 5
    dte_min: int = 21
    dte_max: int = 45
    max_spread_ratio: float = 0.15
    dry_run: bool = True


class CoveredCallRecommendation(BaseModel):
    symbol: str
    shares: int
    coverable_contracts: int
    expiry: str
    strike: float
    right: str
    contracts: int
    bid: float
    ask: float
    mid: float
```

- [ ] **Step 4: 在 `backend/app/schemas.py` 暴露 API schema**

```python
class CoveredCallPilotRequest(BaseModel):
    mode: str = "paper"
    symbols: list[str] = []
    max_candidates_per_symbol: int = 5
    dte_min: int = 21
    dte_max: int = 45
    max_spread_ratio: float = 0.15
    dry_run: bool = True
```

- [ ] **Step 5: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_trade_option_models.py -q
```

Expected:
```text
2 passed
```

- [ ] **Step 6: 提交本任务**

```bash
cd /app/stocklean
git add backend/app/services/trade_option_models.py backend/app/schemas.py backend/tests/test_trade_option_models.py
git commit -m "feat(options): add covered call pilot models"
```

---

### Task 2: 给 IB 读取层补最小期权链能力

**Files:**
- Modify: `backend/app/services/ib_read_session.py`
- Create: `backend/app/services/ib_options_market.py`
- Test: `backend/tests/test_ib_options_market.py`

- [ ] **Step 1: 先写失败测试，锁定期权链标准化输出**

```python
from app.services.ib_options_market import normalize_option_contract_row


def test_normalize_option_contract_row_keeps_call_contract_fields():
    row = {
        "symbol": "AAPL",
        "expiry": "20260515",
        "strike": 230,
        "right": "C",
        "bid": 1.2,
        "ask": 1.4,
    }
    item = normalize_option_contract_row(row)
    assert item["symbol"] == "AAPL"
    assert item["expiry"] == "2026-05-15"
    assert item["right"] == "C"
    assert item["bid"] == 1.2
    assert item["ask"] == 1.4
```

- [ ] **Step 2: 运行测试，确认失败**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_ib_options_market.py -q
```

Expected:
```text
E   ModuleNotFoundError: No module named 'app.services.ib_options_market'
```

- [ ] **Step 3: 在 `ib_read_session.py` 增加最小期权读取接口**

新增方法目标：
- `fetch_option_contract_details(...)`
- `fetch_option_market_snapshot(...)`

实现要求：
- 仅支持 `OPT`
- 失败时返回 `None`
- 不影响现有 `STK` 读取路径

- [ ] **Step 4: 写 `ib_options_market.py` 标准化封装**

最小接口：
```python
def normalize_option_contract_row(row: dict[str, object]) -> dict[str, object]: ...

def fetch_option_candidates(*, mode: str, symbol: str) -> list[dict[str, object]]: ...
```

- [ ] **Step 5: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_ib_options_market.py -q
```

Expected:
```text
1 passed
```

- [ ] **Step 6: 提交本任务**

```bash
cd /app/stocklean
git add backend/app/services/ib_read_session.py backend/app/services/ib_options_market.py backend/tests/test_ib_options_market.py
git commit -m "feat(options): add ib option market readers"
```

---

### Task 3: 实现 covered call 资格判断与候选筛选

**Files:**
- Create: `backend/app/services/options_eligibility.py`
- Create: `backend/app/services/covered_call_planner.py`
- Test: `backend/tests/test_options_eligibility.py`
- Test: `backend/tests/test_covered_call_planner.py`

- [ ] **Step 1: 先写资格判断失败测试**

```python
from app.services.options_eligibility import evaluate_covered_call_eligibility


def test_covered_call_eligibility_rejects_small_position():
    result = evaluate_covered_call_eligibility(
        symbol="NVDA",
        shares=75,
        has_open_orders=False,
        has_option_position=False,
        runtime_state="healthy",
        mode="paper",
    )
    assert result["eligible"] is False
    assert result["reason"] == "shares_below_100"


def test_covered_call_eligibility_accepts_round_lot_position():
    result = evaluate_covered_call_eligibility(
        symbol="AAPL",
        shares=250,
        has_open_orders=False,
        has_option_position=False,
        runtime_state="healthy",
        mode="paper",
    )
    assert result["eligible"] is True
    assert result["coverable_contracts"] == 2
```

- [ ] **Step 2: 写选约失败测试**

```python
from app.services.covered_call_planner import pick_covered_call_candidate


def test_pick_covered_call_candidate_prefers_otm_tighter_spread():
    candidates = [
        {"expiry": "2026-05-15", "strike": 220.0, "underlying_price": 225.0, "right": "C", "bid": 2.0, "ask": 3.0},
        {"expiry": "2026-05-15", "strike": 230.0, "underlying_price": 225.0, "right": "C", "bid": 1.2, "ask": 1.3},
    ]
    picked = pick_covered_call_candidate(candidates, dte_min=21, dte_max=45, max_spread_ratio=0.15)
    assert picked is not None
    assert picked["strike"] == 230.0
```

- [ ] **Step 3: 运行测试，确认当前失败**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_options_eligibility.py backend/tests/test_covered_call_planner.py -q
```

Expected:
```text
E   ModuleNotFoundError
```

- [ ] **Step 4: 写最小资格判断实现**

`evaluate_covered_call_eligibility()` 至少处理：
- `mode != paper`
- `runtime_state != healthy`
- `shares < 100`
- `has_open_orders`
- `has_option_position`
- 计算 `coverable_contracts = shares // 100`

- [ ] **Step 5: 写最小选约实现**

`pick_covered_call_candidate()` 至少处理：
- 仅保留 `CALL`
- 仅保留 OTM
- 过滤无效 bid/ask
- 过滤 `spread / mid > max_spread_ratio`
- 按 `expiry` 与 `spread` 排序，返回第一个可用候选

- [ ] **Step 6: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_options_eligibility.py backend/tests/test_covered_call_planner.py -q
```

Expected:
```text
4 passed
```

- [ ] **Step 7: 提交本任务**

```bash
cd /app/stocklean
git add backend/app/services/options_eligibility.py backend/app/services/covered_call_planner.py backend/tests/test_options_eligibility.py backend/tests/test_covered_call_planner.py
git commit -m "feat(options): add covered call eligibility and planner"
```

---

### Task 4: 编排 pilot 服务并新增只读 API

**Files:**
- Create: `backend/app/services/covered_call_pilot.py`
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_covered_call_pilot_route.py`

- [ ] **Step 1: 先写路由失败测试**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_covered_call_pilot_route_requires_paper_mode(monkeypatch):
    client = TestClient(app)
    resp = client.post(
        "/api/trade/options/covered-call/pilot",
        json={"mode": "live", "dry_run": True},
    )
    assert resp.status_code == 400
    assert "paper_only" in resp.text
```

- [ ] **Step 2: 运行测试，确认当前失败**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_covered_call_pilot_route.py -q
```

Expected:
```text
404 != 400
```

- [ ] **Step 3: 写 `covered_call_pilot.py` 编排服务**

最小流程：
- 读取当前持仓
- 读取 open orders
- 读取 Gateway 运行健康
- 对每个 symbol 执行资格判断
- 拉取期权候选
- 调用 planner 选出推荐
- 落盘 artifacts
- 返回统一结构

- [ ] **Step 4: 在 `trade.py` 新增 pilot 路由**

目标接口：
```python
@router.post("/options/covered-call/pilot")
def run_covered_call_pilot(payload: CoveredCallPilotRequest):
    ...
```

要求：
- 非 `paper` 直接 `400`
- 非 `dry_run` 直接 `400`
- 仅调用 pilot 服务，不触发现有股票执行逻辑

- [ ] **Step 5: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_covered_call_pilot_route.py -q
```

Expected:
```text
1 passed
```

- [ ] **Step 6: 提交本任务**

```bash
cd /app/stocklean
git add backend/app/services/covered_call_pilot.py backend/app/routes/trade.py backend/app/schemas.py backend/tests/test_covered_call_pilot_route.py
git commit -m "feat(options): add covered call pilot api"
```

---

### Task 5: 运行回归并做真实 `paper` dry-run 验证

**Files:**
- Existing artifacts output under `artifacts/options_pilot_*`

- [ ] **Step 1: 跑全部后端测试**

Run:
```bash
cd /app/stocklean && pytest \
  backend/tests/test_trade_option_models.py \
  backend/tests/test_ib_options_market.py \
  backend/tests/test_options_eligibility.py \
  backend/tests/test_covered_call_planner.py \
  backend/tests/test_covered_call_pilot_route.py -q
```

Expected:
```text
all passed
```

- [ ] **Step 2: 重启后端服务**

Run:
```bash
systemctl --user restart stocklean-backend
systemctl --user status stocklean-backend --no-pager
```

Expected:
```text
active (running)
```

- [ ] **Step 3: 用真实 `paper` 账户执行 dry-run 试点**

Run:
```bash
curl -s -X POST http://127.0.0.1:8021/api/trade/options/covered-call/pilot \
  -H 'Content-Type: application/json' \
  -d '{"mode":"paper","dry_run":true}'
```

Expected:
```text
返回 eligible/rejected/artifacts 结构，且没有真实下单
```

- [ ] **Step 4: 检查 artifacts 是否落盘**

Run:
```bash
ls -dt /app/stocklean/artifacts/options_pilot_* | head
```

Expected:
```text
出现本次 dry-run 目录
```

- [ ] **Step 5: 提交本任务**

```bash
cd /app/stocklean
git add backend/app/services backend/app/routes/trade.py backend/app/schemas.py backend/tests
git commit -m "test(options): verify paper covered call pilot"
```

---

## 自检

- 本计划只覆盖 `paper-only covered call pilot`，没有偷偷扩大到真实 paper 下单或 live。
- 计划显式保持现有股票主路径不变，避免和当前实盘执行链相互污染。
- 每个任务都包含 TDD、运行命令和验证标准。
