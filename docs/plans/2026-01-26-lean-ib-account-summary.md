# Lean IB Account Summary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Lean Bridge account summary output with a merged IB account snapshot (AccountUpdates + AccountSummary, BASE‑first) so UI shows real IB values.

**Architecture:** Add snapshot accessors in IB brokerage/account data, expose brokerage from transaction handler, and update `LeanBridgeResultHandler` to build summary from IB snapshot with BASE‑first + source priority merge and stale fallback.

**Tech Stack:** C# (.NET), QuantConnect Lean (Lean_git), NUnit tests, JSON output.

---

### Task 1: Account snapshot helper (TDD)

**Files:**
- Create: `Lean_git/Tests/Common/Brokerages/InteractiveBrokersAccountDataTests.cs`
- Modify: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersAccountData.cs`

**Step 1: Write the failing test**
```csharp
using NUnit.Framework;
using QuantConnect.Brokerages.InteractiveBrokers;

namespace QuantConnect.Tests.Common.Brokerages
{
    [TestFixture]
    public class InteractiveBrokersAccountDataTests
    {
        [Test]
        public void GetAccountSummarySnapshotReturnsCopy()
        {
            var data = new InteractiveBrokersAccountData();
            data.AccountProperties["BASE:NetLiquidation"] = "123";

            var snapshot = data.GetAccountSummarySnapshot();
            snapshot["BASE:NetLiquidation"] = "999";

            Assert.AreEqual("123", data.AccountProperties["BASE:NetLiquidation"]);
        }
    }
}
```

**Step 2: Run test to verify it fails**
Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~InteractiveBrokersAccountDataTests.GetAccountSummarySnapshotReturnsCopy`
Expected: FAIL (method `GetAccountSummarySnapshot` not found).

**Step 3: Write minimal implementation**
```csharp
public Dictionary<string, string> GetAccountSummarySnapshot()
{
    return new Dictionary<string, string>(AccountProperties);
}
```

**Step 4: Run test to verify it passes**
Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~InteractiveBrokersAccountDataTests.GetAccountSummarySnapshotReturnsCopy`
Expected: PASS.

**Step 5: Commit**
```bash
git add Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersAccountData.cs \
        Lean_git/Tests/Common/Brokerages/InteractiveBrokersAccountDataTests.cs
git commit -m "test: add IB account snapshot helper"
```

---

### Task 2: Brokerage snapshot exposure + IB AccountSummary ingestion (TDD)

**Files:**
- Modify: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs`
- Modify: `Lean_git/Engine/TransactionHandlers/BrokerageTransactionHandler.cs`

**Step 1: Write the failing test**
Add to `Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs` a test that:
- Creates a temp output dir
- Creates `InteractiveBrokersBrokerage` and injects snapshot values (via internal test helper to be added)
- Initializes `BrokerageTransactionHandler` with brokerage
- Runs `LeanBridgeResultHandler.ProcessSynchronousEvents(true)`
- Asserts `account_summary.json` uses snapshot values

Example test skeleton (insert near existing tests):
```csharp
[Test]
public void BuildAccountSummaryUsesBrokerageSnapshot()
{
    using var dir = new TemporaryDirectory();
    Config.Set("lean-bridge-output-dir", dir.Directory);

    var algo = new AlgorithmStub();
    var brokerage = new InteractiveBrokersBrokerage();
    brokerage.SetAccountSummaryValueForTesting("BASE", "NetLiquidation", "123456.78");
    brokerage.SetAccountSummaryValueForTesting("BASE", "TotalCashValue", "90000.00");

    var resultHandler = new LeanBridgeResultHandler();
    resultHandler.Initialize(new ResultHandlerInitializeParameters(algo, null, null, null, null, null, null, null));

    var transactionHandler = new TestableBrokerageTransactionHandler();
    transactionHandler.Initialize(algo, brokerage, resultHandler);
    resultHandler.SetTransactionHandler(transactionHandler);

    resultHandler.ProcessSynchronousEvents(true);

    var json = JObject.Parse(File.ReadAllText(Path.Combine(dir.Directory, "account_summary.json")));
    Assert.AreEqual(123456.78m, json["items"]["NetLiquidation"].Value<decimal>());
    Assert.AreEqual("lean_bridge", json["source"].Value<string>());
}
```

**Step 2: Run test to verify it fails**
Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~BuildAccountSummaryUsesBrokerageSnapshot`
Expected: FAIL (missing helper + still using Algorithm.Portfolio).

**Step 3: Write minimal implementation**
- In `InteractiveBrokersBrokerage`:
  - Add `public Dictionary<string,string> GetAccountSummarySnapshot()`
  - Add `internal void SetAccountSummaryValueForTesting(...)` to seed `AccountProperties`
  - Update `HandleAccountSummary` to record to `_accountData.AccountProperties[$"{e.Currency}:{e.Tag}"] = e.Value`
- In `BrokerageTransactionHandler`:
  - Add `public IBrokerage Brokerage => _brokerage;`

**Step 4: Run test to verify it passes**
Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~BuildAccountSummaryUsesBrokerageSnapshot`
Expected: PASS.

**Step 5: Commit**
```bash
git add Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs \
        Lean_git/Engine/TransactionHandlers/BrokerageTransactionHandler.cs \
        Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs
git commit -m "feat: expose ib account snapshot and test hook"
```

---

### Task 3: LeanBridgeResultHandler uses merged snapshot (TDD)

**Files:**
- Modify: `Lean_git/Engine/Results/LeanBridgeResultHandler.cs`

**Step 1: Write the failing test**
Extend the test in Task 2 (or add a second test) to assert merge behavior:
- `BASE` wins over non‑BASE
- AccountUpdates values override AccountSummary values
- Empty snapshot yields `items={}` and `stale=true`

**Step 2: Run test to verify it fails**
Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~BuildAccountSummaryUsesBrokerageSnapshot`
Expected: FAIL (merge logic missing).

**Step 3: Write minimal implementation**
Implement in `LeanBridgeResultHandler`:
- Detect `BrokerageTransactionHandler` + `InteractiveBrokersBrokerage`
- Read snapshot via `GetAccountSummarySnapshot()`
- Merge with BASE‑first + source priority
- Build items list, set `stale=true` when empty

**Step 4: Run test to verify it passes**
Run: `dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~BuildAccountSummaryUsesBrokerageSnapshot`
Expected: PASS.

**Step 5: Commit**
```bash
git add Lean_git/Engine/Results/LeanBridgeResultHandler.cs \
        Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs
git commit -m "fix: lean bridge account summary from ib snapshot"
```

---

### Task 4: Manual verification (no code)

**Step 1: Run Lean live (paper)**
- Ensure TWS/Gateway connected
- Start Lean live and wait for bridge output

**Step 2: Verify output**
- Compare `/data/share/stock/data/lean_bridge/account_summary.json` with TWS Account Summary
- Confirm UI matches values

**Step 3: Note results in task log**

