# Lean Bridge Watchlist Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 PreTrade 的决策快照标的通过 watchlist 自动订阅到 Lean Bridge，从而保证 `market_snapshot` 有完整报价。

**Architecture:** 后端在 PreTrade 中写入 `lean_bridge/watchlist.json`，LeanBridgeSmokeAlgorithm 定期读取并增量 `AddEquity`，LeanBridgeResultHandler 按订阅输出 quotes。

**Tech Stack:** FastAPI (Python), Lean (C#), JSON, NUnit, pytest

---

### Task 0: 提交设计文档

**Files:**
- Modify: `docs/plans/2026-01-27-lean-bridge-watchlist-design.md`

**Step 1: 校验设计文档内容**

确认文件存在且内容正确。

**Step 2: 提交设计文档**

Run:
```bash
git add docs/plans/2026-01-27-lean-bridge-watchlist-design.md
git commit -m "docs: add lean bridge watchlist design"
```

---

### Task 1: 后端 watchlist 写入 + 单测

**Files:**
- Create: `backend/app/services/lean_bridge_watchlist.py`
- Modify: `backend/app/services/pretrade_runner.py`
- Modify: `backend/app/services/lean_execution.py`
- Modify: `configs/lean_live_interactive_paper.json`
- Modify: `configs/lean_config_template.json`
- Test: `backend/tests/test_lean_bridge_watchlist.py`

**Step 1: 写失败测试（watchlist 生成与写入）**

```python
from pathlib import Path
from app.services.lean_bridge_watchlist import build_watchlist_payload, write_watchlist

def test_write_watchlist_dedup_and_sort(tmp_path: Path):
    path = tmp_path / "watchlist.json"
    payload = write_watchlist(path, [" aapl", "MSFT", "AAPL", ""], meta={"source": "test"})
    assert payload["symbols"] == ["AAPL", "MSFT"]
    assert path.exists()
```

**Step 2: 运行测试确认失败**

Run:
```bash
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_lean_bridge_watchlist.py::test_write_watchlist_dedup_and_sort
```
Expected: FAIL (module or function missing)

**Step 3: 最小实现 watchlist 服务**

实现：
- `build_watchlist_payload(symbols, meta)`：规范化、去重、排序
- `write_watchlist(path, symbols, meta)`：写 JSON
- `merge_symbols(primary, extra)`：合并

**Step 4: PreTrade 集成 watchlist 写入**

在 `step_market_snapshot` 开始位置：
- 读取决策快照 symbols
- 读取 `positions.json`（如果存在）
- 合并并写入 watchlist（带 project_id、decision_snapshot_id、updated_at）

**Step 5: 更新 Lean 配置模板**

- `configs/lean_live_interactive_paper.json`
- `configs/lean_config_template.json`

新增字段：
- `"lean-bridge-watchlist-path": "/data/share/stock/data/lean_bridge/watchlist.json"`
- `"lean-bridge-watchlist-refresh-seconds": "5"`

并在 `backend/app/services/lean_execution.py` 的 `build_execution_config` 中设置同样字段（使用 `_bridge_output_dir()` 拼接路径）。

**Step 6: 重新运行测试**

Run:
```bash
PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest -q backend/tests/test_lean_bridge_watchlist.py
```
Expected: PASS

**Step 7: 提交**

```bash
git add backend/app/services/lean_bridge_watchlist.py backend/app/services/pretrade_runner.py backend/app/services/lean_execution.py backend/tests/test_lean_bridge_watchlist.py configs/lean_live_interactive_paper.json configs/lean_config_template.json
git commit -m "feat: write lean bridge watchlist from pretrade"
```

---

### Task 2: Lean 侧 watchlist 订阅 + 单测

**Files:**
- Modify: `/app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeSmokeAlgorithm.cs`
- Create: `/app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeSmokeAlgorithmTests.cs`

**Step 1: 写失败测试（watchlist 解析）**

```csharp
[Test]
public void ParsesWatchlistSymbols()
{
    var path = Path.GetTempFileName();
    File.WriteAllText(path, "{\"symbols\":[\"aapl\",\" MSFT \",\"\"]}");

    var symbols = LeanBridgeSmokeAlgorithm.LoadWatchlistSymbols(path);

    CollectionAssert.AreEqual(new[] { "AAPL", "MSFT" }, symbols);
}
```

**Step 2: 运行测试确认失败**

Run:
```bash
dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~LeanBridgeSmokeAlgorithmTests
```
Expected: FAIL (method missing)

**Step 3: 实现 watchlist 解析与订阅**

- 添加 `LoadWatchlistSymbols(string path)` 静态方法：
  - 支持 JSON array 或 `{ "symbols": [...] }`
  - 去重、排序、uppercase
- 在 `Initialize()` 读取 `lean-bridge-watchlist-path`
- 通过 `Schedule.On(DateRules.EveryDay(), TimeRules.Every(_refreshPeriod), ...)` 定期刷新
- 对新增 symbol 调用 `AddEquity(symbol, Resolution.Minute)`

**Step 4: 重新运行测试**

Run:
```bash
dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~LeanBridgeSmokeAlgorithmTests
```
Expected: PASS

**Step 5: 提交（Lean_git 仓库）**

```bash
cd /app/stocklean/Lean_git
git add Algorithm.CSharp/LeanBridgeSmokeAlgorithm.cs Tests/Algorithm/LeanBridgeSmokeAlgorithmTests.cs
git commit -m "feat: add watchlist subscriptions to lean bridge"
```

---

### Task 3: 手工验证 PreTrade 行情校验

**Files:**
- None

**Step 1: 触发 PreTrade（项目16）**

通过页面运行 PreTrade（使用 2026-01-23 PIT 快照）。

**Step 2: 观察 watchlist 与 quotes**

验证 `lean_bridge/watchlist.json` 有完整 symbols，`quotes.json` 覆盖决策快照标的。

**Step 3: 验证 market_snapshot 通过**

确认 PreTrade `market_snapshot` step 成功。

---

Plan complete and saved to `docs/plans/2026-01-27-lean-bridge-watchlist-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) – I dispatch fresh subagent per task, review between tasks, fast iteration
2. Parallel Session (separate) – Open new session with executing-plans, batch execution with checkpoints

Which approach?
