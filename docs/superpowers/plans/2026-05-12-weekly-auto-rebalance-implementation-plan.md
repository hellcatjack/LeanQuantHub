# Weekly Auto Rebalance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现每周一开盘前自动 PreTrade、开盘后自动执行交易批次，并通过现有 Telegram 通道通知用户。

**Architecture:** 新增后端 weekly rebalance 编排服务，将流程拆成 `prepare` 和 `execute` 两个幂等阶段。prepare 复用 PreTrade 生成 DecisionSnapshot 和 queued TradeRun；execute 校验周一、交易日和 RTH 开盘后执行同一周的 queued TradeRun，并通过既有 Telegram 配置发送结果。

**Tech Stack:** FastAPI、SQLAlchemy、MySQL/SQLite 测试、systemd user timers、现有 PreTrade/TradeRun/Telegram 服务。

---

### Task 1: PreTrade 支持自定义 step plan

**Files:**
- Modify: `backend/app/services/pretrade_runner.py`
- Test: `backend/tests/test_trade_run_schedule.py`

- [ ] **Step 1: 写失败测试**

在 `test_create_pretrade_run_for_project_creates_steps` 附近增加：

```python
def test_create_pretrade_run_for_project_accepts_step_plan_override():
    Session = _make_session_factory()
    session = Session()
    try:
        project = Project(name="pretrade-custom-plan", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = pretrade_runner.create_pretrade_run_for_project(
            session,
            project_id=project.id,
            params={"weekly_rebalance": {"week_key": "2026-W20"}},
            step_plan=[
                {"key": "calendar_refresh", "enabled": True, "params": {}},
                {"key": "trade_execute", "enabled": False, "params": {}},
            ],
        )

        steps = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run.id)
            .order_by(PreTradeStep.step_order.asc())
            .all()
        )
        assert (run.params or {}).get("weekly_rebalance", {}).get("week_key") == "2026-W20"
        assert [(step.step_key, step.status) for step in steps] == [
            ("calendar_refresh", "queued"),
            ("trade_execute", "skipped"),
        ]
    finally:
        session.close()
```

- [ ] **Step 2: 验证失败**

Run: `cd backend && ../.venv/bin/pytest tests/test_trade_run_schedule.py::test_create_pretrade_run_for_project_accepts_step_plan_override -q`

Expected: FAIL，原因是 `create_pretrade_run_for_project()` 尚不接受 `params` / `step_plan`。

- [ ] **Step 3: 实现最小改动**

给 `_create_steps()` 增加 `step_plan` 参数；给 `create_pretrade_run_for_project()` 增加 `params` 和 `step_plan` 参数。没有传入时保持现有行为。

- [ ] **Step 4: 验证通过**

Run: `cd backend && ../.venv/bin/pytest tests/test_trade_run_schedule.py::test_create_pretrade_run_for_project_accepts_step_plan_override -q`

Expected: PASS。

### Task 2: 新增 weekly rebalance 编排服务

**Files:**
- Create: `backend/app/services/weekly_rebalance.py`
- Test: `backend/tests/test_weekly_rebalance.py`

- [ ] **Step 1: 写 prepare 失败测试**

测试内容：

- 周一 08:00 ET 调用 prepare。
- mock `run_pretrade_run()` 将 run 标记为 success 并创建 DecisionSnapshot + TradeRun。
- 断言 prepare 返回 `status="success"`、写入 `weekly_rebalance.week_key`，并发送 Telegram。

- [ ] **Step 2: 写 prepare 幂等失败测试**

测试内容：

- 同一 project/week 已存在成功的 `PreTradeRun.params.weekly_rebalance.phase="prepare"`。
- 再次调用 prepare 不创建第二个 PreTradeRun，返回 `status="reused"`。

- [ ] **Step 3: 写 execute 开盘保护失败测试**

测试内容：

- 周一 09:00 ET 调用 execute。
- 断言返回 `status="skipped"`、`message="market_not_open"`，且不会调用 `execute_trade_run()`。

- [ ] **Step 4: 写 execute 成功失败测试**

测试内容：

- 同一周存在成功 prepare run 和 queued TradeRun。
- 周一 09:35 ET 调用 execute。
- mock `execute_trade_run()` 返回 running/done。
- 断言 TradeRun params 写入 `weekly_rebalance.phase="execute"`，并发送 Telegram。

- [ ] **Step 5: 验证失败**

Run: `cd backend && ../.venv/bin/pytest tests/test_weekly_rebalance.py -q`

Expected: FAIL，原因是服务文件不存在。

- [ ] **Step 6: 实现服务**

实现：

- `WeeklyRebalanceResult` dataclass
- `prepare_weekly_rebalance()`
- `execute_weekly_rebalance()`
- ISO week、交易日、开盘检查、同周 run 查找、Telegram 摘要。

- [ ] **Step 7: 验证通过**

Run: `cd backend && ../.venv/bin/pytest tests/test_weekly_rebalance.py -q`

Expected: PASS。

### Task 3: API 与部署入口

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/automation.py`
- Create: `scripts/weekly_rebalance.sh`
- Create: `deploy/systemd/stocklean-weekly-rebalance-prepare.service`
- Create: `deploy/systemd/stocklean-weekly-rebalance-prepare.timer`
- Create: `deploy/systemd/stocklean-weekly-rebalance-execute.service`
- Create: `deploy/systemd/stocklean-weekly-rebalance-execute.timer`
- Test: `backend/tests/test_weekly_rebalance.py`

- [ ] **Step 1: 写 API 失败测试**

直接调用 route 函数，mock service，断言 payload 映射和返回结构。

- [ ] **Step 2: 验证失败**

Run: `cd backend && ../.venv/bin/pytest tests/test_weekly_rebalance.py -q`

Expected: FAIL，原因是 schema/route 尚不存在。

- [ ] **Step 3: 实现 API 与脚本**

新增：

- `WeeklyRebalanceRequest`
- `WeeklyRebalanceOut`
- `POST /api/automation/weekly-rebalance/prepare`
- `POST /api/automation/weekly-rebalance/execute`
- shell 脚本以 `curl` 调用 API。

- [ ] **Step 4: 新增 systemd timer**

prepare timer: `OnCalendar=Mon *-*-* 08:00:00`

execute timer: `OnCalendar=Mon *-*-* 09:35:00`

- [ ] **Step 5: 验证通过**

Run: `cd backend && ../.venv/bin/pytest tests/test_weekly_rebalance.py tests/test_trade_run_schedule.py -q`

Expected: PASS。

### Task 4: 服务部署验证

**Files:**
- Install to: `/home/hellcat/.config/systemd/user/`

- [ ] **Step 1: 复制 systemd units**

Run:

```bash
install -m 0644 deploy/systemd/stocklean-weekly-rebalance-*.service /home/hellcat/.config/systemd/user/
install -m 0644 deploy/systemd/stocklean-weekly-rebalance-*.timer /home/hellcat/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now stocklean-weekly-rebalance-prepare.timer
systemctl --user enable --now stocklean-weekly-rebalance-execute.timer
```

- [ ] **Step 2: 重启后端**

Run: `systemctl --user restart stocklean-backend.service`

- [ ] **Step 3: 验证 timers**

Run: `systemctl --user list-timers --all --no-pager | rg 'weekly-rebalance|NEXT'`

Expected: 两个 timer 均 loaded/active，下一次执行时间为下一个周一 08:00/09:35 ET。
