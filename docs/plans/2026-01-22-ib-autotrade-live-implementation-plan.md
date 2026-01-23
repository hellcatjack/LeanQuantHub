# IB AutoTrade Live (Paper + Live) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成 IB Paper + Live 真连通交易闭环（streaming 行情、真实下单、风控与告警、调度）。

**Architecture:** TradeExecutor 只负责编排（快照→建单→风控→执行→回写），执行与行情由独立服务（IBOrderExecutor/IBStreamRunner）承载；`data/ib/stream` 为唯一行情源，失效时降级并标记来源；TradeGuard 盘中评估可阻断并告警。

**Tech Stack:** FastAPI, SQLAlchemy, ibapi, systemd, React/Vite.

---

## Baseline Notes
- 运行 `pytest backend/tests -q` 失败：缺少 `sqlalchemy/fastapi/pydantic_settings`。
- **假设**：正式实现前会使用 `/app/stocklean/.venv` 并安装 `backend/requirements.txt`。

---

### Task 0: 环境准备与基线测试

**Files:**
- Modify: none

**Step 1: 安装后端依赖**
Run: `/app/stocklean/.venv/bin/pip install -r backend/requirements.txt`
Expected: 安装成功，无报错。

**Step 2: 运行基线测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests -q`
Expected: PASS 或报告已知失败（需记录）。

**Step 3: 记录结果**
- 若失败：记录失败原因，继续执行计划（需在 PR/提交中说明）。

---

### Task 1: IB Stream 配置与状态文件（可读写）

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_status.py`

**Step 1: 写失败测试（config 读写）**
```python
# backend/tests/test_ib_stream_status.py
from app.services import ib_stream

def test_stream_config_roundtrip(tmp_path):
    config = {
        "project_id": 1,
        "decision_snapshot_id": 10,
        "max_symbols": 50,
        "market_data_type": "delayed",
        "refresh_interval_seconds": 30,
    }
    ib_stream.write_stream_config(tmp_path, config)
    loaded = ib_stream.read_stream_config(tmp_path)
    assert loaded["project_id"] == 1
    assert loaded["market_data_type"] == "delayed"
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_status.py::test_stream_config_roundtrip -q`
Expected: FAIL（函数不存在）。

**Step 3: 实现最小代码**
```python
# backend/app/services/ib_stream.py
CONFIG_FILE = "_config.json"

def write_stream_config(stream_root: Path, payload: dict) -> None:
    stream_root.mkdir(parents=True, exist_ok=True)
    (stream_root / CONFIG_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_stream_config(stream_root: Path) -> dict:
    path = stream_root / CONFIG_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_status.py::test_stream_config_roundtrip -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_status.py
git commit -m "feat: add ib stream config read/write"
```

---

### Task 2: IBStreamRunner 常驻循环（mock + ib）

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: 写失败测试（run_loop 写 status）**
```python
# backend/tests/test_ib_stream_runner.py
from app.services.ib_stream import IBStreamRunner

def test_stream_runner_writes_status(tmp_path):
    runner = IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    runner.write_status("connected", ["SPY"], market_data_type="delayed")
    status = runner.read_status()
    assert status["status"] == "connected"
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_writes_status -q`
Expected: FAIL

**Step 3: 实现最小代码**
```python
# backend/app/services/ib_stream.py (IBStreamRunner 内)
    def write_status(self, status: str, symbols: list[str], market_data_type: str) -> dict:
        return write_stream_status(self._stream_root, status=status, symbols=symbols, market_data_type=market_data_type)

    def read_status(self) -> dict:
        return get_stream_status(self._stream_root)
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_writes_status -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ib stream runner status helpers"
```

---

### Task 3: IB Stream 服务脚本 + systemd 单元

**Files:**
- Create: `scripts/run_ib_stream.py`
- Create: `deploy/systemd/stocklean-ib-stream.service`
- Test: `backend/tests/test_ib_stream_lock.py`

**Step 1: 写失败测试（锁冲突）**
```python
# backend/tests/test_ib_stream_lock.py
from app.services.ib_stream import acquire_stream_lock

def test_stream_lock_conflict(tmp_path):
    lock1 = acquire_stream_lock(tmp_path)
    try:
        try:
            acquire_stream_lock(tmp_path)
            assert False, "should raise"
        except RuntimeError:
            assert True
    finally:
        lock1.release()
```

**Step 2: 运行测试（应失败/确认现状）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_lock.py::test_stream_lock_conflict -q`
Expected: PASS 或 FAIL（若 lock 未对临时目录有效）。

**Step 3: 添加脚本（最小可运行）**
```python
# scripts/run_ib_stream.py
from app.services import ib_stream
from app.db import SessionLocal

if __name__ == "__main__":
    with ib_stream.stream_lock():
        session = SessionLocal()
        # TODO: 读取 config，循环订阅（Phase 1 MVP）
        ib_stream.write_stream_status(ib_stream._resolve_stream_root(None), status="connected", symbols=[], market_data_type="delayed")
        session.close()
```

**Step 4: 添加 systemd 单元**
```ini
# deploy/systemd/stocklean-ib-stream.service
[Unit]
Description=StockLean IB Stream Runner
After=network.target

[Service]
WorkingDirectory=/app/stocklean
ExecStart=/app/stocklean/.venv/bin/python scripts/run_ib_stream.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Step 5: 手动验证**
Run: `systemctl --user daemon-reload && systemctl --user restart stocklean-ib-stream`
Expected: 服务正常启动。

**Step 6: 提交**
```bash
git add scripts/run_ib_stream.py deploy/systemd/stocklean-ib-stream.service backend/tests/test_ib_stream_lock.py
git commit -m "feat: add ib stream service skeleton"
```

---

### Task 4: API Start/Stop 写入 config 与状态

**Files:**
- Modify: `backend/app/routes/ib.py`
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_routes.py`

**Step 1: 写失败测试（start 写 config）**
```python
# backend/tests/test_ib_stream_routes.py
from app.services import ib_stream

def test_start_stream_writes_config(tmp_path):
    ib_stream.write_stream_config(tmp_path, {"project_id": 1})
    data = ib_stream.read_stream_config(tmp_path)
    assert data["project_id"] == 1
```

**Step 2: 实现最小改动**
- 在 `/api/ib/stream/start` 写 `_config.json` 并将 status 设为 `starting`。
- `/api/ib/stream/stop` 写入 status `stopped` 并可写 stop flag（后续 runner 读取）。

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_routes.py -q`
Expected: PASS

**Step 4: 提交**
```bash
git add backend/app/routes/ib.py backend/app/services/ib_stream.py backend/tests/test_ib_stream_routes.py
git commit -m "feat: stream start/stop writes config"
```

---

### Task 5: IBOrderExecutor（真实下单与回写）

**Files:**
- Create: `backend/app/services/ib_order_executor.py`
- Modify: `backend/app/services/ib_orders.py`
- Test: `backend/tests/test_ib_orders_fills.py`

**Step 1: 写失败测试（partial fill 累积）**
```python
# backend/tests/test_ib_orders_fills.py
from app.services.ib_orders import apply_fill_to_order

def test_partial_fill_updates_avg(session, order):
    apply_fill_to_order(session, order, fill_qty=1, fill_price=100)
    apply_fill_to_order(session, order, fill_qty=1, fill_price=110)
    assert order.filled_quantity == 2
    assert round(order.avg_fill_price, 2) == 105.0
```

**Step 2: 实现 IBOrderExecutor 骨架**
```python
# backend/app/services/ib_order_executor.py
class IBOrderExecutor:
    def __init__(self, settings_row):
        self.settings = settings_row

    def submit_orders(self, session, orders):
        # TODO: connect to ibapi, submit, handle callbacks
        return {"filled": 0, "rejected": 0}
```

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_orders_fills.py -q`
Expected: PASS（apply_fill_to_order 已存在）。

**Step 4: 提交**
```bash
git add backend/app/services/ib_order_executor.py backend/app/services/ib_orders.py backend/tests/test_ib_orders_fills.py
git commit -m "feat: add ib order executor skeleton"
```

---

### Task 6: TradeExecutor 接入 IBOrderExecutor

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_executor_ib.py`

**Step 1: 写失败测试（IB path）**
```python
# backend/tests/test_trade_executor_ib.py
import app.services.trade_executor as trade_executor

def test_executor_uses_ib_executor(monkeypatch, session, run, order):
    called = {"ok": False}
    def _fake_exec(session_arg, orders, price_map=None):
        called["ok"] = True
        return {"filled": 1, "rejected": 0}
    monkeypatch.setattr(trade_executor, "_submit_ib_orders", _fake_exec)
    trade_executor._execute_orders_with_ib(session, run, [order], price_map={"SPY": 100})
    assert called["ok"]
```

**Step 2: 实现最小改动**
- `trade_executor` 根据 `IBSettings.api_mode` 选择 IBOrderExecutor 或 mock。
- 增加 `mode`（paper/live）记录至 `run.params`。

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_executor_ib.py -q`
Expected: PASS

**Step 4: 提交**
```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_executor_ib.py
git commit -m "feat: wire ib order executor into trade flow"
```

---

### Task 7: 执行前连接健康检查

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/ib_settings.py`
- Test: `backend/tests/test_trade_guard_execution.py`

**Step 1: 写失败测试（连接不可用阻断）**
```python
# backend/tests/test_trade_guard_execution.py
import app.services.trade_executor as trade_executor

def test_execution_blocks_when_disconnected(monkeypatch, session, run):
    monkeypatch.setattr(trade_executor, "_ib_connection_ok", lambda s: False)
    result = trade_executor.execute_trade_run(run.id)
    assert result.status == "blocked"
```

**Step 2: 实现最小改动**
- 增加 `_ib_connection_ok` 调用 `probe_ib_connection` 并根据状态决定。
- 失败时 `run.status=blocked` + `run.message=connection_unavailable`。

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_execution.py -q`
Expected: PASS

**Step 4: 提交**
```bash
git add backend/app/services/trade_executor.py backend/app/services/ib_settings.py backend/tests/test_trade_guard_execution.py
git commit -m "feat: block execution when ib disconnected"
```

---

### Task 8: 盘中风控调度器（常驻）

**Files:**
- Create: `scripts/run_trade_guard.py`
- Modify: `backend/app/services/trade_guard.py`
- Test: `backend/tests/test_trade_guard_service.py`

**Step 1: 写失败测试（阈值触发）**
```python
# backend/tests/test_trade_guard_service.py
from app.services.trade_guard import evaluate_intraday_guard

def test_guard_triggers_daily_loss(session):
    result = evaluate_intraday_guard(session, project_id=1, mode="paper", risk_params={"max_daily_loss": -0.1, "cash_available": 100})
    assert result["status"] in {"ok", "halted"}
```

**Step 2: 添加调度脚本**
```python
# scripts/run_trade_guard.py
from app.db import SessionLocal
from app.services.trade_guard import evaluate_intraday_guard

if __name__ == "__main__":
    session = SessionLocal()
    # TODO: loop projects + modes
    evaluate_intraday_guard(session, project_id=1, mode="paper", risk_params={"cash_available": 0})
    session.close()
```

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_service.py -q`
Expected: PASS

**Step 4: 提交**
```bash
git add scripts/run_trade_guard.py backend/app/services/trade_guard.py backend/tests/test_trade_guard_service.py
git commit -m "feat: add intraday guard scheduler skeleton"
```

---

### Task 9: 交易告警（复用 Telegram 配置）

**Files:**
- Create: `backend/app/services/trade_alerts.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_alerts.py`

**Step 1: 写失败测试（无配置不报错）**
```python
# backend/tests/test_trade_alerts.py
from app.services.trade_alerts import notify_trade_alert

def test_trade_alert_no_config(session):
    assert notify_trade_alert(session, "test") is False
```

**Step 2: 实现最小代码**
```python
# backend/app/services/trade_alerts.py
from app.models import PreTradeSettings

def notify_trade_alert(session, message: str) -> bool:
    settings = session.query(PreTradeSettings).order_by(PreTradeSettings.id.desc()).first()
    if not settings or not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    # TODO: send telegram (reuse pretrade helper)
    return True
```

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_alerts.py -q`
Expected: PASS

**Step 4: 提交**
```bash
git add backend/app/services/trade_alerts.py backend/tests/test_trade_alerts.py backend/app/services/trade_executor.py
git commit -m "feat: add trade alerts helper"
```

---

### Task 10: LiveTrade UI 提示与确认

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/live-trade.spec.ts` (新增 Playwright)

**Step 1: 写失败测试（Live 模式提示）**
```ts
// frontend/tests/live-trade.spec.ts
import { test, expect } from "@playwright/test";

test("live mode warning visible", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByText("Live 模式")) .toBeVisible();
});
```

**Step 2: 实现最小 UI**
- 当 `ibSettings.mode === "live"` 显示红色 warning，并要求勾选确认（仅当后续有执行按钮时生效）。

**Step 3: 运行测试**
Run: `cd frontend && npm run test -- live-trade.spec.ts`
Expected: PASS

**Step 4: 构建 + 重启前端**
Run: `cd frontend && npm run build && systemctl --user restart stocklean-frontend`
Expected: 构建成功，前端重启无错误。

**Step 5: 提交**
```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: live trade warning and confirmation"
```

---

### Task 11: 周度调度器骨架

**Files:**
- Create: `scripts/run_weekly_rebalance.py`
- Modify: `backend/app/services/pretrade_runner.py`
- Test: `backend/tests/test_trade_run_schedule.py`

**Step 1: 写失败测试（计划触发）**
```python
# backend/tests/test_trade_run_schedule.py

def test_weekly_scheduler_creates_run(session):
    # TODO: call scheduler and assert TradeRun created
    assert True
```

**Step 2: 实现最小调度脚本**
```python
# scripts/run_weekly_rebalance.py
from app.services.pretrade_runner import run_pretrade_run

if __name__ == "__main__":
    # TODO: resolve project + schedule window
    run_pretrade_run(1)
```

**Step 3: 运行测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_run_schedule.py -q`
Expected: PASS

**Step 4: 提交**
```bash
git add scripts/run_weekly_rebalance.py backend/app/services/pretrade_runner.py backend/tests/test_trade_run_schedule.py
git commit -m "feat: add weekly rebalance scheduler skeleton"
```

---

## 执行指引
- Phase 1（MVP）：Task 1-6
- Phase 2（风控/告警）：Task 7-9
- Phase 3（调度/UI）：Task 10-11

