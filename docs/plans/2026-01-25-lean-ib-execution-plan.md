# Lean IB 执行算法 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增 Lean 执行算法以读取 execution-intent 并实际下单（quantity 优先、weight 兜底）。

**Architecture:** 在 Lean_git/Algorithm.CSharp 新增 `LeanBridgeExecutionAlgorithm` + 解析器；后端 `build_execution_config` 默认使用新算法。通过 Lean ResultHandler 保持桥接输出，执行仅一次。

**Tech Stack:** C# (.NET, Lean), Python (FastAPI), pytest, dotnet test.

### Task 1: 后端配置切换到执行算法

**Files:**
- Modify: `/app/stocklean/backend/app/services/lean_execution.py`
- Modify: `/app/stocklean/backend/tests/test_lean_execution_config.py`

**Step 1: Write the failing test**

```python
def test_build_execution_config_uses_execution_algorithm():
    config = lean_execution.build_execution_config(
        intent_path="/tmp/intent.json",
        brokerage="InteractiveBrokersBrokerage",
        project_id=1,
        mode="paper",
    )
    assert config["algorithm-type-name"] == "LeanBridgeExecutionAlgorithm"
    assert config["algorithm-language"] == "CSharp"
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_lean_execution_config.py -q`
Expected: FAIL with assertion on algorithm-type-name

**Step 3: Write minimal implementation**

```python
payload.setdefault("algorithm-type-name", "LeanBridgeExecutionAlgorithm")
if payload.get("algorithm-type-name") in {"LeanBridgeSmokeAlgorithm", "LeanBridgeExecutionAlgorithm"}:
    payload["algorithm-language"] = "CSharp"
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_lean_execution_config.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add /app/stocklean/backend/app/services/lean_execution.py /app/stocklean/backend/tests/test_lean_execution_config.py
git commit -m "Use execution algorithm for Lean trade runs"
```

### Task 2: 为执行算法编写 Lean 单元测试（解析 intent）

**Files:**
- Create: `/app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`
- Create: `/app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs` (占位，先不实现逻辑)

**Step 1: Write the failing test**

```csharp
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using QuantConnect.Algorithm.CSharp;

namespace QuantConnect.Tests.Algorithm
{
    [TestFixture]
    public class LeanBridgeExecutionAlgorithmTests
    {
        [Test]
        public void ParsesQuantityAndWeight()
        {
            var path = Path.GetTempFileName();
            File.WriteAllText(path, "[{\"symbol\":\"AAPL\",\"quantity\":1},{\"symbol\":\"MSFT\",\"weight\":0.2}]");

            var items = LeanBridgeExecutionAlgorithm.LoadIntentItems(path);

            Assert.AreEqual(2, items.Count);
            Assert.AreEqual("AAPL", items[0].Symbol);
            Assert.AreEqual(1, items[0].Quantity);
            Assert.AreEqual(0, items[0].Weight);
            Assert.AreEqual("MSFT", items[1].Symbol);
            Assert.AreEqual(0, items[1].Quantity);
            Assert.AreEqual(0.2m, items[1].Weight);
        }
    }
}
```

**Step 2: Run test to verify it fails**

Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeExecutionAlgorithmTests`
Expected: FAIL because `LeanBridgeExecutionAlgorithm` 或 `LoadIntentItems` 不存在

**Step 3: Write minimal implementation**

在 `LeanBridgeExecutionAlgorithm.cs` 内提供：
```csharp
public class LeanBridgeExecutionAlgorithm : QCAlgorithm
{
    public class IntentItem { public string Symbol; public decimal Quantity; public decimal Weight; }
    public static List<IntentItem> LoadIntentItems(string path) { /* minimal JSON parse */ }
    public override void Initialize() { /* 暂不实现执行逻辑 */ }
}
```

**Step 4: Run test to verify it passes**

Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeExecutionAlgorithmTests`
Expected: PASS

**Step 5: Commit**

```bash
git add /app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs /app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs
git commit -m "Add execution intent parser tests"
```

### Task 3: 实现一次性执行逻辑（quantity 优先）

**Files:**
- Modify: `/app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs`
- Modify: `/app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`

**Step 1: Write the failing test**

在测试中新增：
```csharp
[Test]
public void QuantityTakesPriorityOverWeight()
{
    var path = Path.GetTempFileName();
    File.WriteAllText(path, "[{\"symbol\":\"AAPL\",\"quantity\":1,\"weight\":0.5}]");
    var items = LeanBridgeExecutionAlgorithm.LoadIntentItems(path);
    Assert.AreEqual(1, items[0].Quantity);
    Assert.AreEqual(0.5m, items[0].Weight);
}
```

**Step 2: Run test to verify it fails**

Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeExecutionAlgorithmTests`
Expected: FAIL if parser未保留两个字段或默认值不符

**Step 3: Write minimal implementation**

```csharp
private bool _executed;
private List<IntentItem> _items = new();
public override void Initialize()
{
    var path = Config.Get("execution-intent-path", string.Empty);
    _items = LoadIntentItems(path);
    foreach (var item in _items)
    {
        if (!string.IsNullOrWhiteSpace(item.Symbol))
        {
            AddEquity(item.Symbol, Resolution.Minute);
        }
    }
}

public override void OnData(Slice data)
{
    if (_executed || _items.Count == 0) return;
    foreach (var item in _items)
    {
        if (string.IsNullOrWhiteSpace(item.Symbol)) continue;
        if (item.Quantity > 0)
        {
            MarketOrder(item.Symbol, item.Quantity);
        }
        else if (item.Weight > 0)
        {
            SetHoldings(item.Symbol, item.Weight);
        }
    }
    _executed = true;
    Log("EXECUTED_ONCE");
}
```

**Step 4: Run test to verify it passes**

Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeExecutionAlgorithmTests`
Expected: PASS

**Step 5: Commit**

```bash
git add /app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs /app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs
git commit -m "Implement Lean execution algorithm for intent orders"
```

### Task 4: 构建与端到端验证

**Files:**
- Modify: `/app/stocklean/artifacts/order_intents/order_intent_manual_run_*.json` (临时)
- Modify: `/app/stocklean/artifacts/lean_execution/trade_run_*.json` (由后端生成)

**Step 1: Build C# algorithm**

Run: `dotnet build /app/stocklean/Lean_git/Algorithm.CSharp/QuantConnect.Algorithm.CSharp.csproj -c Release`
Expected: BUILD SUCCEEDED

**Step 2: 触发 trade_run 执行**

Run: `POST /api/trade/runs` + `POST /api/trade/runs/{id}/execute`
Expected: trade_run status running, Lean 日志出现 “EXECUTED_ONCE”

**Step 3: 确认 TWS Paper 订单**

Expected: TWS 出现 AAPL 市价单记录

**Step 4: Commit（若修改脚本/配置被纳入版本控制）**

```bash
git add -u
git commit -m "Document lean execution verification"
```
