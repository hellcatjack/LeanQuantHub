# IB Gateway 半挂自动恢复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 IB Gateway 半挂场景补齐业务级探针、分级自愈、交易保护和前端兜底，确保系统在连续探测失败后通过 `systemd user service + IBC` 自动重启 Gateway，并在恢复前阻止新的交易执行。

**Architecture:** 新增统一的 Gateway 运行健康服务，综合 bridge 快照、commands/command_results 和直连 `reqPositions` 探针给出状态机；现有 `stocklean-ibgateway-watchdog.service` 保持为 systemd 入口，但内部改为调用 Python 业务探针与恢复逻辑；前端保留最后一次可信持仓并展示恢复状态；后端在实盘执行入口增加 `gateway_degraded/gateway_restarting` 保护。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL、现有 bridge JSON 快照、systemd user service、IBC、React + Vite、Vitest、Playwright、Pytest。

> 说明：项目规则禁止使用 git worktree，本计划直接在主工作区执行。

---

### Task 1: 建立 Gateway 运行健康模型与探针

**Files:**
- Create: `backend/app/services/ib_gateway_runtime.py`
- Modify: `backend/app/services/ib_account.py`
- Create: `backend/tests/test_ib_gateway_runtime.py`

**Step 1: Write the failing test**

在 `backend/tests/test_ib_gateway_runtime.py` 增加以下覆盖：
- `heartbeat` 新鲜，但 `positions/open_orders/account_summary` 时间戳停滞时，状态为 `snapshot_stale`
- `commands/` 存在超时未处理命令时，状态为 `command_stuck`
- 直连 `reqPositions` 连续失败达到阈值时，状态升级为 `bridge_degraded`
- 直连探针成功时，状态回落到 `healthy`

示例：

```python
def test_runtime_health_marks_command_stuck_when_pending_command_too_old(tmp_path):
    payload = build_gateway_runtime_health(
        bridge_root=tmp_path,
        bridge_status={"status": "ok", "stale": False},
        positions_payload={"stale": False, "refreshed_at": "2026-03-10T14:00:00Z"},
        open_orders_payload={"stale": False, "refreshed_at": "2026-03-10T14:00:00Z"},
        account_payload={"stale": False, "refreshed_at": "2026-03-10T14:00:00Z"},
        direct_probe={"ok": True, "latency_ms": 120},
        now=datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc),
    )
    assert payload["state"] == "command_stuck"
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_ib_gateway_runtime.py -v
```

Expected: FAIL，提示 `ib_gateway_runtime` 模块或状态分类逻辑不存在。

**Step 3: Write minimal implementation**

在 `backend/app/services/ib_gateway_runtime.py` 中实现：
- `build_gateway_runtime_health(...)`
- `load_gateway_runtime_health(...)`
- `write_gateway_runtime_health(...)`
- `is_gateway_trade_blocked(...)`
- 统一状态枚举与阈值解析

在 `backend/app/services/ib_account.py` 中抽取可复用的短超时直连 positions probe，避免 watchdog 只能看到端口连通而看不到业务请求卡死。

输出 JSON 至 bridge 根目录，例如：
- `gateway_runtime_health.json`

字段至少包含：
- `state`
- `failure_count`
- `pending_command_count`
- `oldest_pending_command_age_seconds`
- `last_positions_at`
- `last_open_orders_at`
- `last_account_summary_at`
- `last_command_result_at`
- `last_probe_result`
- `last_probe_latency_ms`
- `last_recovery_action`
- `last_recovery_at`
- `next_allowed_action_at`

**Step 4: Run tests to verify it passes**

Run:

```bash
pytest backend/tests/test_ib_gateway_runtime.py -v
```

Expected: PASS。

**Step 5: Commit**

```bash
git add backend/app/services/ib_gateway_runtime.py backend/app/services/ib_account.py backend/tests/test_ib_gateway_runtime.py
git commit -m "feat: add gateway runtime health model"
```

### Task 2: 暴露 Gateway 运行健康到 API 与状态总览

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/brokerage.py`
- Modify: `backend/app/services/ib_status_overview.py`
- Create: `backend/tests/test_ib_gateway_runtime_routes.py`

**Step 1: Write the failing test**

新增路由/Schema 覆盖：
- `GET /api/brokerage/bridge/status` 返回 `runtime_health`
- `GET /api/brokerage/status/overview` 返回聚合后的 Gateway 运行健康摘要

示例断言：

```python
def test_bridge_status_exposes_runtime_health(client, monkeypatch):
    monkeypatch.setattr(...)
    res = client.get("/api/brokerage/bridge/status")
    assert res.status_code == 200
    assert res.json()["runtime_health"]["state"] == "command_stuck"
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_ib_gateway_runtime_routes.py -v
```

Expected: FAIL，提示 `runtime_health` 字段缺失。

**Step 3: Implement**

- 为 `IBBridgeStatusOut` 增加 `runtime_health` 嵌套字段
- 为 `IBStatusOverviewOut` 增加 `gateway_runtime` 或等价摘要字段
- 在 `brokerage.py` 中将 `build_gateway_runtime_health` 接入 `/bridge/status`
- 在 `ib_status_overview.py` 中聚合运行健康结果，便于 UI 一次获取

**Step 4: Run tests to verify it passes**

Run:

```bash
pytest backend/tests/test_ib_gateway_runtime_routes.py -v
```

Expected: PASS。

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/brokerage.py backend/app/services/ib_status_overview.py backend/tests/test_ib_gateway_runtime_routes.py
git commit -m "feat: expose gateway runtime health APIs"
```

### Task 3: 实现分级自愈执行器并复用现有 systemd watchdog

**Files:**
- Create: `scripts/ib_gateway_watchdog.py`
- Modify: `scripts/ib_gateway_watchdog.sh`
- Modify: `backend/app/services/lean_bridge_watchdog.py`
- Modify: `backend/app/services/lean_bridge_leader.py`
- Create: `backend/tests/test_ib_gateway_recovery.py`

**Step 1: Write the failing test**

在 `backend/tests/test_ib_gateway_recovery.py` 增加：
- 第 1 次失败只触发 bridge refresh
- 第 2 次失败触发 leader restart
- 第 3 次失败触发 `systemctl --user restart stocklean-ibgateway.service`
- 冷却窗口内不会重复重启 Gateway
- Gateway 重启后探针恢复时，状态回到 `recovering -> healthy`

示例：

```python
def test_recovery_escalates_to_systemd_restart_after_threshold(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or DummyResult())
    result = run_gateway_watchdog_once(...)
    assert result["action"] == "gateway_restart"
    assert calls[-1][:4] == ["systemctl", "--user", "restart", "stocklean-ibgateway.service"]
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_ib_gateway_recovery.py -v
```

Expected: FAIL。

**Step 3: Implement minimal recovery ladder**

- 在 `scripts/ib_gateway_watchdog.py` 中实现一次性执行入口：
  - 读取运行健康快照
  - 更新 failure counter / cooldown
  - 依序执行：
    - `refresh_bridge(... force=True)`
    - `ensure_lean_bridge_leader(... force=True)`
    - `systemctl --user restart stocklean-ibgateway.service`
- 保留 `scripts/ib_gateway_watchdog.sh` 作为 systemd 入口，但内部改为调用 Python helper
- 恢复动作写入 `gateway_runtime_health.json`
- 写审计日志：
  - `brokerage.gateway.recovery_attempt`
  - `brokerage.gateway.leader_restart`
  - `brokerage.gateway.restart`
  - `brokerage.gateway.degraded`

**Step 4: Run tests to verify it passes**

Run:

```bash
pytest backend/tests/test_ib_gateway_recovery.py -v
```

Expected: PASS。

**Step 5: Manual verification (safe path)**

Run:

```bash
systemctl --user start stocklean-ibgateway-watchdog.service
systemctl --user status stocklean-ibgateway-watchdog.service --no-pager
journalctl --user -u stocklean-ibgateway-watchdog.service -n 50 --no-pager
```

Expected:
- watchdog 正常执行
- healthy 时不触发 restart
- 日志中可看到运行健康状态与 action

**Step 6: Commit**

```bash
git add scripts/ib_gateway_watchdog.py scripts/ib_gateway_watchdog.sh backend/app/services/lean_bridge_watchdog.py backend/app/services/lean_bridge_leader.py backend/tests/test_ib_gateway_recovery.py
git commit -m "feat: add staged gateway auto recovery"
```

### Task 4: 为交易执行入口增加 Gateway 降级保护

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/trade_direct_order.py`
- Modify: `backend/app/services/manual_trade_execution.py`
- Create: `backend/tests/test_ib_gateway_trade_guard.py`

**Step 1: Write the failing test**

增加覆盖：
- `gateway_restarting` 时批次执行返回 `409 gateway_restarting`
- `gateway_degraded` 时 direct order 返回 `409 gateway_degraded`
- `gateway_degraded` 时 manual order 返回 `409 gateway_degraded`
- 取消订单链路不受该 guard 影响

示例：

```python
def test_execute_trade_run_blocked_when_gateway_degraded(monkeypatch):
    monkeypatch.setattr(..., "is_gateway_trade_blocked", lambda *args, **kwargs: (True, "gateway_degraded"))
    result = execute_trade_run(...)
    assert result.status == "blocked"
    assert result.message == "gateway_degraded"
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_ib_gateway_trade_guard.py -v
```

Expected: FAIL。

**Step 3: Implement**

- 在 `ib_gateway_runtime.py` 提供统一 guard helper
- 在以下入口执行前调用：
  - `execute_trade_run`
  - `submit_direct_order`
  - `execute_manual_order`
- 对 blocked 状态写审计，detail 包含：
  - `gateway_state`
  - `last_recovery_action`
  - `last_probe_result`

**Step 4: Run tests to verify it passes**

Run:

```bash
pytest backend/tests/test_ib_gateway_trade_guard.py -v
```

Expected: PASS。

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/app/services/trade_direct_order.py backend/app/services/manual_trade_execution.py backend/tests/test_ib_gateway_trade_guard.py
git commit -m "feat: guard trading when gateway degraded"
```

### Task 5: 前端保留最后可信持仓并展示恢复状态

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`
- Create: `frontend/tests/live-trade-gateway-health.spec.ts`

**Step 1: Write the failing unit test**

在 `LiveTradePage.test.ts` 增加：
- 持仓成功加载一次后，后续请求报错不会把表格清空
- stale/恢复中横幅会显示“最后可信更新时间”
- 当 `gateway_restarting` 或 `gateway_degraded` 时，执行按钮与持仓买卖按钮禁用

示例：

```tsx
it("keeps last trusted positions when refresh fails", async () => {
  // first load returns positions, second load rejects
  // expect table rows still visible and stale banner shown
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd frontend && npm run test -- src/pages/LiveTradePage.test.ts
```

Expected: FAIL。

**Step 3: Implement**

在 `LiveTradePage.tsx` 中：
- 增加 `lastTrustedPositions`、`lastTrustedPositionsUpdatedAt`
- 仅在 `stale=false` 且请求成功时覆盖可信持仓
- 请求失败或 stale 时保留可信持仓，并展示运行健康/恢复状态横幅
- 将 `bridge/status` 返回的 `runtime_health` 接入页面
- 在执行、批量平仓、单行买卖按钮上接入禁用逻辑

**Step 4: Run unit tests to verify it passes**

Run:

```bash
cd frontend && npm run test -- src/pages/LiveTradePage.test.ts
```

Expected: PASS。

**Step 5: Add one Playwright regression**

验证页面在运行健康降级时不允许触发新执行，并保留旧持仓展示。

Run:

```bash
cd frontend && npm run test:e2e -- live-trade-gateway-health.spec.ts
```

Expected: PASS。

**Step 6: Build frontend and restart service**

Run:

```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```

Expected:
- 构建成功
- 页面刷新后状态卡片与持仓兜底行为生效

**Step 7: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/pages/LiveTradePage.test.ts frontend/src/i18n.tsx frontend/src/styles.css frontend/tests/live-trade-gateway-health.spec.ts
git commit -m "feat: preserve trusted positions during gateway recovery"
```

### Task 6: 文档与运维说明补齐

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`

**Step 1: Update operator docs**

补充以下内容：
- Gateway 半挂自动恢复的状态机
- `stocklean-ibgateway.service` 仍是唯一 Gateway manager
- watchdog 触发条件不再只是端口/进程，还包含业务级探针
- 常用排查命令：
  - `systemctl --user status stocklean-ibgateway.service`
  - `systemctl --user status stocklean-ibgateway-watchdog.timer`
  - `journalctl --user -u stocklean-ibgateway-watchdog.service -n 100 --no-pager`
  - `journalctl --user -u stocklean-ibgateway.service -n 100 --no-pager`

**Step 2: Commit**

```bash
git add README.md README.en.md
git commit -m "docs: document gateway auto recovery flow"
```

### Task 7: 全链路验证

**Files:**
- No additional files

**Step 1: Run backend test suite for touched areas**

Run:

```bash
pytest backend/tests/test_ib_gateway_runtime.py \
  backend/tests/test_ib_gateway_runtime_routes.py \
  backend/tests/test_ib_gateway_recovery.py \
  backend/tests/test_ib_gateway_trade_guard.py -v
```

Expected: PASS。

**Step 2: Run frontend tests**

Run:

```bash
cd frontend && npm run test -- src/pages/LiveTradePage.test.ts
cd frontend && npm run test:e2e -- live-trade-gateway-health.spec.ts
```

Expected: PASS。

**Step 3: Manual runtime verification**

在不影响生产下单的前提下，至少验证：
- 正常状态下 watchdog 报 `healthy`
- 人工制造 bridge 快照停滞时，状态升级到 `snapshot_stale/command_stuck`
- 连续失败达到阈值后，watchdog 触发 `systemctl --user restart stocklean-ibgateway.service`
- Gateway 恢复后，前端展示回到 `healthy`
- 恢复前无法执行新批次/新单，但取消操作仍可用

建议命令：

```bash
systemctl --user start stocklean-ibgateway-watchdog.service
systemctl --user status stocklean-ibgateway.service --no-pager
journalctl --user -u stocklean-ibgateway-watchdog.service -n 100 --no-pager
journalctl --user -u stocklean-ibgateway.service -n 100 --no-pager
```

**Step 4: Final commit**

```bash
git status
# 确认仅包含本计划相关改动后再提交
```
