# Lean IB Positions Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 Lean Bridge 的 `positions.json` 以 IB 账户持仓为权威，确保实盘交易页面与 TWS 持仓一致。

**Architecture:** 在 `LeanBridgeResultHandler.BuildPositions` 中优先读取 `IBrokerage.GetAccountHoldings()`，若为空再回退算法持仓，并新增 `source_detail` 标记来源。

**Tech Stack:** C#/.NET, NUnit, Moq (Lean Tests)

---

### Task 1: 准备 Lean_git 工作区与基线测试

**Files:**
- Modify: `/app/stocklean/Lean_git` (独立仓库)

**Step 1: 在 Lean_git 创建 worktree（若已存在可跳过）**

```bash
git -C /app/stocklean/Lean_git worktree add .worktrees/lean-ib-positions -b fix/lean-ib-positions
```

**Step 2: 运行基线测试（确认环境可跑）**

```bash
cd /app/stocklean/Lean_git/.worktrees/lean-ib-positions
dotnet test Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeResultHandler
```

Expected: PASS（即使 0 tests 也算通过）

---

### Task 2: 编写失败测试（TDD）

**Files:**
- Create: `/app/stocklean/Lean_git/.worktrees/lean-ib-positions/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs`
- Test: `/app/stocklean/Lean_git/.worktrees/lean-ib-positions/Tests/QuantConnect.Tests.csproj`

**Step 1: 写失败测试**

```csharp
[Test]
public void BuildPositionsUsesBrokerageHoldingsWhenAvailable()
{
    var algorithm = new AlgorithmStub();
    algorithm.AddSecurities(equities: new List<string> { "AAPL" });

    var ibHolding = new Holding
    {
        Symbol = Symbols.SPY,
        Quantity = 2,
        AveragePrice = 100m,
        MarketValue = 200m,
        UnrealizedPnL = 0m,
        CurrencySymbol = "$"
    };

    var brokerage = new Mock<IBrokerage>();
    brokerage.SetupGet(x => x.IsConnected).Returns(true);
    brokerage.Setup(x => x.GetAccountHoldings()).Returns(new List<Holding> { ibHolding });

    var transactionHandler = new BrokerageTransactionHandler();
    transactionHandler.Initialize(algorithm, brokerage.Object, new BacktestingResultHandler());

    var handler = new TestableLeanBridgeResultHandler();
    handler.SetAlgorithmForTest(algorithm);
    handler.SetTransactionHandlerForTest(transactionHandler);

    var result = handler.InvokeBuildPositions(DateTime.UtcNow);
    var items = (List<Dictionary<string, object>>)result["items"];

    Assert.AreEqual("SPY", items[0]["symbol"]);
    Assert.AreEqual("ib_holdings", result["source_detail"]);
}
```

**Step 2: 运行测试，确认失败**

```bash
cd /app/stocklean/Lean_git/.worktrees/lean-ib-positions
dotnet test Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeResultHandler
```

Expected: FAIL（仍输出算法持仓或 source_detail 不匹配）

---

### Task 3: 实现 IB 优先逻辑 + 回退

**Files:**
- Modify: `/app/stocklean/Lean_git/.worktrees/lean-ib-positions/Engine/Results/LeanBridgeResultHandler.cs`

**Step 1: 最小实现**

```csharp
private Dictionary<string, object> BuildPositions(DateTime now)
{
    var sourceDetail = "algorithm_holdings";
    var list = new List<Dictionary<string, object>>();

    if (TransactionHandler is BrokerageTransactionHandler brokerageTransactionHandler)
    {
        var brokerageHoldings = brokerageTransactionHandler.Brokerage?.GetAccountHoldings();
        if (brokerageHoldings != null && brokerageHoldings.Count > 0)
        {
            sourceDetail = "ib_holdings";
            foreach (var holding in brokerageHoldings)
            {
                list.Add(new Dictionary<string, object>
                {
                    ["symbol"] = holding.Symbol.Value,
                    ["quantity"] = holding.Quantity,
                    ["avg_cost"] = holding.AveragePrice,
                    ["market_value"] = holding.MarketValue,
                    ["unrealized_pnl"] = holding.UnrealizedPnL,
                    ["currency"] = holding.CurrencySymbol
                });
            }
        }
    }

    if (list.Count == 0)
    {
        var holdings = GetHoldings(Algorithm.Securities.Values, Algorithm.SubscriptionManager.SubscriptionDataConfigService, onlyInvested: true);
        foreach (var entry in holdings)
        {
            var holding = entry.Value;
            list.Add(new Dictionary<string, object>
            {
                ["symbol"] = holding.Symbol.Value,
                ["quantity"] = holding.Quantity,
                ["avg_cost"] = holding.AveragePrice,
                ["market_value"] = holding.MarketValue,
                ["unrealized_pnl"] = holding.UnrealizedPnL,
                ["currency"] = holding.CurrencySymbol
            });
        }
    }

    return new Dictionary<string, object>
    {
        ["items"] = list,
        ["refreshed_at"] = now.ToString("O"),
        ["source"] = "lean_bridge",
        ["source_detail"] = sourceDetail,
        ["stale"] = false
    };
}
```

**Step 2: 运行测试，确认通过**

```bash
cd /app/stocklean/Lean_git/.worktrees/lean-ib-positions
dotnet test Tests/QuantConnect.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeResultHandler
```

Expected: PASS

**Step 3: Commit**

```bash
git add Engine/Results/LeanBridgeResultHandler.cs Tests/Engine/Results/LeanBridgeResultHandlerTests.cs
git commit -m "fix: prefer IB account holdings in lean bridge positions"
```

---

### Task 4: 验证 bridge 输出与 TWS 一致

**Files:**
- Verify: `/data/share/stock/data/lean_bridge/positions.json`

**Step 1: 触发一次 Lean Bridge 输出（Paper）**

Run: 触发现有 live/paper 运行流程（保持现有命令/脚本）

**Step 2: 校验输出**

```bash
jq '.items | length' /data/share/stock/data/lean_bridge/positions.json
```

Expected: 数量与 TWS 持仓数量一致，且 `source_detail=ib_holdings`

