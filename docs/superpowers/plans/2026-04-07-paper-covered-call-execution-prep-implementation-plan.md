# Paper Covered Call Execution Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 covered call pilot 增加一层执行准备能力，输出独立期权订单计划与 `ready / review_required / blocked` 门禁结果，仍保持 `paper-only + dry-run`。

**Architecture:** 新增独立的 execution prep 服务，复用现有 pilot 结果进行单标的门禁评估和订单建模。执行准备与推荐逻辑分离，确保后续真实 `paper` 期权下单可以建立在更稳的边界上。

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest

---

## 文件结构

- Modify: `backend/app/services/trade_option_models.py`
  - 增加 execution prep 请求、响应和期权订单计划模型。
- Create: `backend/app/services/covered_call_execution.py`
  - 编排单标的执行准备、门禁判断与 artifact 落盘。
- Modify: `backend/app/routes/trade.py`
  - 新增 `POST /api/trade/options/covered-call/prepare`。
- Modify: `backend/app/schemas.py`
  - 暴露 execution prep 的 API schema。
- Create: `backend/tests/test_covered_call_execution.py`
- Create: `backend/tests/test_covered_call_execution_route.py`

---

### Task 1: 扩展期权订单与 execution prep 数据模型

**Files:**
- Modify: `backend/app/services/trade_option_models.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_option_models.py`

- [ ] **Step 1: 先写失败测试，锁定 execution prep 模型**

```python
def test_covered_call_execution_plan_defaults_to_dry_run():
    payload = CoveredCallExecutionPrepareRequest(symbol="AAPL")
    assert payload.mode == "paper"
    assert payload.dry_run is True


def test_option_order_plan_serializes_contract_fields():
    order = OptionOrderPlan(
        underlying_symbol="AAPL",
        sec_type="OPT",
        expiry="2026-05-15",
        strike=230.0,
        right="C",
        multiplier=100,
        contracts=2,
        side="SELL",
        order_type="LMT",
        limit_price=1.25,
        dry_run=True,
    )
    assert order.sec_type == "OPT"
    assert order.contracts == 2
```

- [ ] **Step 2: 运行测试，确认红灯**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_trade_option_models.py -q
```

Expected:
```text
AttributeError / ValidationError
```

- [ ] **Step 3: 写最小模型实现**

新增：
- `CoveredCallExecutionPrepareRequest`
- `OptionOrderPlan`
- `CoveredCallExecutionPrepareResult`

- [ ] **Step 4: 同步 `schemas.py`**

新增 API 对应的 request/response schema。

- [ ] **Step 5: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_trade_option_models.py -q
```

Expected:
```text
all passed
```

---

### Task 2: 实现 execution prep 服务

**Files:**
- Create: `backend/app/services/covered_call_execution.py`
- Test: `backend/tests/test_covered_call_execution.py`

- [ ] **Step 1: 先写失败测试，锁定三种门禁状态**

```python
def test_prepare_covered_call_execution_blocks_when_pilot_has_no_recommendation():
    ...
    assert result["status"] == "blocked"


def test_prepare_covered_call_execution_marks_review_required_for_risk_tags():
    ...
    assert result["status"] == "review_required"


def test_prepare_covered_call_execution_marks_ready_without_risk_tags():
    ...
    assert result["status"] == "ready"
```

- [ ] **Step 2: 运行测试，确认红灯**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_covered_call_execution.py -q
```

Expected:
```text
ModuleNotFoundError / AttributeError
```

- [ ] **Step 3: 写最小 execution prep 实现**

实现：
- 调用现有 `run_covered_call_pilot(..., symbols=[symbol])`
- 若无 `eligible`，返回 `blocked`
- 若有推荐，构造 `OptionOrderPlan`
- 若 `risk_tags` 非空，返回 `review_required`
- 否则返回 `ready`
- 落盘 `summary.json` 与 `execution_plan.json`

- [ ] **Step 4: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_covered_call_execution.py -q
```

Expected:
```text
all passed
```

---

### Task 3: 接入路由并做 HTTP 验证

**Files:**
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_covered_call_execution_route.py`

- [ ] **Step 1: 先写路由失败测试**

```python
def test_covered_call_prepare_route_rejects_live_mode():
    ...
    assert exc.status_code == 400
    assert "paper_only" in str(exc)
```

- [ ] **Step 2: 运行测试，确认红灯**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_covered_call_execution_route.py -q
```

Expected:
```text
AttributeError / 404
```

- [ ] **Step 3: 新增 `POST /api/trade/options/covered-call/prepare`**

要求：
- `mode != paper` -> `400`
- `dry_run != true` -> `400`
- 其他门禁失败 -> `409`

- [ ] **Step 4: 重新运行测试，确认通过**

Run:
```bash
cd /app/stocklean && pytest backend/tests/test_covered_call_execution_route.py -q
```

Expected:
```text
all passed
```

---

### Task 4: 全量回归与真实 `paper` dry-run 验证

**Files:**
- Existing artifacts under `artifacts/options_execution_*`

- [ ] **Step 1: 跑相关后端测试**

Run:
```bash
cd /app/stocklean && pytest \
  backend/tests/test_trade_option_models.py \
  backend/tests/test_ib_options_market.py \
  backend/tests/test_options_eligibility.py \
  backend/tests/test_covered_call_planner.py \
  backend/tests/test_covered_call_pilot_route.py \
  backend/tests/test_covered_call_pilot_service.py \
  backend/tests/test_covered_call_execution.py \
  backend/tests/test_covered_call_execution_route.py -q
```

Expected:
```text
all passed
```

- [ ] **Step 2: 语法检查并重启后端**

Run:
```bash
cd /app/stocklean && python -m py_compile \
  backend/app/services/trade_option_models.py \
  backend/app/services/covered_call_execution.py \
  backend/app/routes/trade.py
systemctl --user restart stocklean-backend
```

Expected:
```text
无语法错误，backend active
```

- [ ] **Step 3: 用真实 `paper` 账户做 HTTP 验证**

Run:
```bash
curl -sS -X POST http://127.0.0.1:8021/api/trade/options/covered-call/prepare \
  -H 'Content-Type: application/json' \
  -d '{"mode":"paper","symbol":"AAPL","dry_run":true}'
```

Expected:
```text
返回 blocked/review_required/ready 之一，且不真实下单
```

- [ ] **Step 4: 检查 artifact 落盘**

Run:
```bash
ls -dt /app/stocklean/artifacts/options_execution_* | head -n 3
```

Expected:
```text
出现本次 execution prep 目录
```

---

## 自检

- 本计划仍然停留在 `paper-only + dry-run`，没有越界到真实期权下单。
- 计划把推荐、门禁、执行订单模型彻底分层，符合稳健目标。
- 所有任务都要求先红灯、再最小实现、再回归验证。
