# IB Gateway CPU Spike Recovery Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 IB Gateway 恢复链路导致的 CPU 和日志洪峰，避免 watchdog 自身超时、降低恢复期订阅洪峰与日志噪音。

**Architecture:** Python watchdog 负责立即落盘并异步移交 gateway restart；Lean IB brokerage 负责把恢复订阅改成分批执行，并将恢复期日志从按 symbol TRACE 改为按批次摘要；同时对 IB farm OK/idle 消息做日志降级。

**Tech Stack:** Python watchdog, FastAPI backend tests, .NET 10 Lean brokerage, NUnit

---

### Task 1: watchdog 异步重启与状态落盘

**Files:**
- Modify: `scripts/ib_gateway_watchdog.py`
- Test: `backend/tests/test_ib_gateway_recovery.py`

- [ ] 在 `backend/tests/test_ib_gateway_recovery.py` 增加 `gateway_restart` 必须使用 `--no-block` 且先落盘 `gateway_restarting` 的失败测试。
- [ ] 运行 `pytest backend/tests/test_ib_gateway_recovery.py -k gateway_restart -v`，确认新测试先失败。
- [ ] 修改 `scripts/ib_gateway_watchdog.py`，把 `gateway_restart` 改成异步 `systemctl --user restart --no-block`，并在执行前写入 runtime health。
- [ ] 重新运行 `pytest backend/tests/test_ib_gateway_recovery.py -k gateway_restart -v`，确认通过。

### Task 2: IB farm OK/idle 日志降噪

**Files:**
- Modify: `scripts/ib_gateway_watchdog.py`
- Modify: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs`
- Test: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/InteractiveBrokersBrokerageAdditionalTests.cs`

- [ ] 为 C# brokerage 增加“`2104/2106/2107/2158` 走信息日志而非恢复噪音日志”的失败测试。
- [ ] 为 Python watchdog 增加或扩展测试，确认 `2104/2106/2107/2158` 不再被二次记录为 ERROR。
- [ ] 修改 Python watchdog 的日志分类。
- [ ] 修改 C# `HandleError()` 的日志分类，保留 `2103/2105/1100` 现有恢复语义。
- [ ] 运行对应 `pytest` 与 `dotnet test`，确认通过。

### Task 3: Lean 订阅恢复分批与批次摘要

**Files:**
- Modify: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs`
- Test: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/InteractiveBrokersBrokerageAdditionalTests.cs`

- [ ] 添加恢复订阅分批的失败测试，覆盖批次大小、批次延迟和摘要日志。
- [ ] 运行 `dotnet test /app/stocklean/Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/QuantConnect.InteractiveBrokersBrokerage.Tests.csproj --filter Subscription -v minimal`，确认新测试先失败。
- [ ] 在 `InteractiveBrokersBrokerage.cs` 中实现恢复订阅分批和摘要日志。
- [ ] 重新运行同一组 `dotnet test`，确认通过。

### Task 4: 构建与运行态验证

**Files:**
- Modify: 无

- [ ] 运行 `pytest backend/tests/test_ib_gateway_recovery.py backend/tests/test_ib_gateway_runtime.py -v`。
- [ ] 运行 `dotnet test /app/stocklean/Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/QuantConnect.InteractiveBrokersBrokerage.Tests.csproj -v minimal`。
- [ ] 运行 `dotnet build /app/stocklean/Lean_git/Launcher/QuantConnect.Lean.Launcher.csproj -c Release -v minimal`。
- [ ] 重启 `stocklean-backend`，验证 `stocklean-backend.service` 与 `stocklean-ibgateway-watchdog.service` 状态正常。
- [ ] 记录仍未处理项，仅限“服务拆分”和“更细粒度订阅优先级恢复”，不扩展本轮范围。
