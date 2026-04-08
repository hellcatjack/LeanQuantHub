# Paper Covered Call Submit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real `paper-only` covered-call submit stage that validates review tokens and runtime gates, writes option submit commands, and receives option command results through the long-lived Lean bridge.

**Architecture:** Keep the existing `pilot -> prepare -> review` layering. Add a new `submit` service on the Python side, extend the command payload with minimal option contract fields, and teach `LeanBridgeResultHandler` to consume `sec_type=OPT` submit commands while leaving the stock submit path unchanged.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy session, local JSON artifacts, pytest, NUnit, C# Lean bridge runtime.

---

### Task 1: Submit request/result models

**Files:**
- Modify: `backend/app/services/trade_option_models.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_option_models.py`

- [ ] 写失败测试，覆盖 `CoveredCallSubmitRequest` 和 `CoveredCallSubmitResult` 的默认值、必填字段与状态字段。
- [ ] 运行：`cd /app/stocklean && pytest backend/tests/test_trade_option_models.py -q`
- [ ] 只补最小模型：`CoveredCallSubmitRequest`、`CoveredCallSubmitResult`、`CoveredCallSubmitArtifacts`。
- [ ] 重新运行同一命令直到变绿。

### Task 2: Python command writer 期权字段扩展

**Files:**
- Modify: `backend/app/services/lean_bridge_commands.py`
- Test: `backend/tests/test_covered_call_submit_command.py`

- [ ] 写失败测试，覆盖：
  - 股票 submit 现有 payload 不变
  - `sec_type=OPT` 时写出 `underlying_symbol/expiry/strike/right/multiplier`
  - 期权缺字段时报 `ValueError`
- [ ] 运行：`cd /app/stocklean && pytest backend/tests/test_covered_call_submit_command.py -q`
- [ ] 扩展 `write_submit_order_command()`，保持股票默认调用兼容。
- [ ] 重新运行同一命令直到变绿。

### Task 3: Submit 服务

**Files:**
- Create: `backend/app/services/covered_call_submit.py`
- Test: `backend/tests/test_covered_call_submit.py`

- [ ] 写失败测试，覆盖：
  - `paper_only`
  - token 不匹配
  - token 过期
  - runtime 非 `healthy`
  - 持仓不足阻断
  - open orders 冲突阻断
  - command result `submitted`
  - command result `rejected`
  - command result 超时返回 `timeout_pending`
- [ ] 运行：`cd /app/stocklean && pytest backend/tests/test_covered_call_submit.py -q`
- [ ] 实现 `build_covered_call_submit()`：
  - 读取 review bundle
  - 重新做门禁校验
  - 写 command
  - 轮询 command result
  - 落盘 artifact
  - 写 audit log
- [ ] 重新运行同一命令直到变绿。

### Task 4: FastAPI 路由接入

**Files:**
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_covered_call_submit_route.py`

- [ ] 写失败测试，覆盖：
  - `paper_only`
  - `symbol_required` / `review_id_required` / `approval_token_required`
  - 成功透传 submit 结果
- [ ] 运行：`cd /app/stocklean && pytest backend/tests/test_covered_call_submit_route.py -q`
- [ ] 实现 `POST /api/trade/options/covered-call/submit`。
- [ ] 重新运行同一命令直到变绿。

### Task 5: Lean bridge 期权 submit 解析与回执

**Files:**
- Modify: `Lean_git/Engine/Results/LeanBridgeResultHandler.cs`
- Test: `Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs`

- [ ] 写失败测试，覆盖：
  - `sec_type=OPT` 缺字段 -> `option_contract_invalid`
  - `OPT` 非 `LMT` -> `unsupported_order_type`
  - 合法 covered call submit 会构造期权合约并返回包含期权字段的 `submitted` result
  - 股票 submit 测试不回归
- [ ] 运行：`cd /app/stocklean && ./scripts/run_lean_tests.sh Lean_git/Tests/QuantConnect.Tests.csproj --filter "FullyQualifiedName~LeanBridgeResultHandlerTests" -v minimal`
- [ ] 在 `LeanBridgeResultHandler.cs` 中实现最小期权 command 解析与 `PlaceOrder` 调用。
- [ ] 重新运行同一命令直到变绿。

### Task 6: 全量验证

**Files:**
- Verify only: 本阶段新增/修改的 covered call submit 与 Lean bridge 文件。

- [ ] 运行：`cd /app/stocklean && pytest backend/tests/test_trade_option_models.py backend/tests/test_covered_call_submit_command.py backend/tests/test_covered_call_submit.py backend/tests/test_covered_call_submit_route.py backend/tests/test_covered_call_execution.py backend/tests/test_covered_call_review.py backend/tests/test_trade_executor_snapshot_guard.py -q`
- [ ] 运行：`cd /app/stocklean && ./scripts/run_lean_tests.sh Lean_git/Tests/QuantConnect.Tests.csproj --filter "FullyQualifiedName~LeanBridgeResultHandlerTests" -v minimal`
- [ ] 运行：`cd /app/stocklean && python -m py_compile backend/app/services/trade_option_models.py backend/app/services/lean_bridge_commands.py backend/app/services/covered_call_submit.py backend/app/routes/trade.py backend/app/schemas.py`
- [ ] 重启后端：`systemctl --user restart stocklean-backend && systemctl --user status stocklean-backend --no-pager`
- [ ] HTTP 验证：
  - `POST /api/trade/options/covered-call/submit` with `{"mode":"live",...}` -> `400 paper_only`
  - `POST /api/trade/options/covered-call/submit` with bad token -> `409 token_invalid`
  - 使用有效 review bundle 做一次真实 `paper` submit 自测，确认返回 `submitted/rejected/timeout_pending` 三态之一并生成 artifact
