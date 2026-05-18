# IB Gateway 恢复链路稳态化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 降低 watchdog 对瞬时探针抖动的误判，并在恢复期阻止重复升级恢复动作，避免 CPU 峰值与重连风暴。

**Architecture:** 在 `ib_gateway_runtime.py` 收紧退化判定，在 `ib_gateway_watchdog.py` 增加恢复静默窗口和更稳健的默认阈值；通过 `pytest` 回归测试验证升级链路、静默期和健康恢复行为。

**Tech Stack:** FastAPI backend, Python watchdog script, pytest

---

### Task 1: 为 runtime 判定写失败测试

**Files:**
- Modify: `backend/tests/test_ib_gateway_runtime.py`
- Modify: `backend/app/services/ib_gateway_runtime.py`

- [ ] Step 1: 添加“连续 probe 失败但 snapshot 新鲜时不进入 bridge_degraded”的测试。
- [ ] Step 2: 运行 `pytest backend/tests/test_ib_gateway_runtime.py -k probe -v`，确认新测试先失败。
- [ ] Step 3: 修改 `build_gateway_runtime_health()`，让 probe 失败必须叠加 snapshot/command 异常才进入 `bridge_degraded`。
- [ ] Step 4: 重新运行 `pytest backend/tests/test_ib_gateway_runtime.py -v`，确认通过。

### Task 2: 为 watchdog 静默窗口写失败测试

**Files:**
- Modify: `backend/tests/test_ib_gateway_recovery.py`
- Modify: `scripts/ib_gateway_watchdog.py`
- Modify: `backend/app/core/config.py`

- [ ] Step 1: 添加 `leader_restart` 后静默窗口内不再升级的测试。
- [ ] Step 2: 添加 `gateway_restart` 后静默窗口内不重复 restart 的测试。
- [ ] Step 3: 运行 `pytest backend/tests/test_ib_gateway_recovery.py -k quiet -v`，确认新测试先失败。
- [ ] Step 4: 在 `config.py` 中增加显式默认阈值和 `ib_gateway_recovery_quiet_period_seconds`。
- [ ] Step 5: 在 `ib_gateway_watchdog.py` 中实现静默窗口判定与动作抑制。
- [ ] Step 6: 重新运行 `pytest backend/tests/test_ib_gateway_recovery.py -v`，确认通过。

### Task 3: 运行完整回归

**Files:**
- Modify: 无

- [ ] Step 1: 运行 `pytest backend/tests/test_ib_gateway_runtime.py backend/tests/test_ib_gateway_recovery.py backend/tests/test_ib_gateway_trade_guard.py -v`。
- [ ] Step 2: 检查失败数为 `0`，并确认关键断言覆盖静默窗口与恢复链路。
- [ ] Step 3: 记录未处理项，仅限订阅恢复分批和日志降噪，避免本轮范围漂移。
