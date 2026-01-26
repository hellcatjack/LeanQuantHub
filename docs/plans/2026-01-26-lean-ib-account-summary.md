# Lean IB 账户摘要准确性修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.

**Goal:** 将 `account_summary.json` 的账户信息改为 IB 原始摘要，确保实盘交易页展示准确。

**Architecture:** 在 `InteractiveBrokersBrokerage` 内缓存账户摘要快照并提供读取接口；`LeanBridgeResultHandler` 从 IB 快照生成 `account_summary.json`，无快照则标记 `stale=true`。

**Tech Stack:** C# (.NET), Lean Engine, xUnit (Lean Tests)

---

### Task 1: 提交设计文档

**Files:**
- Modify: `docs/plans/2026-01-26-lean-ib-account-summary-design.md`

**Step 1: 提交设计文档**

Run:
```bash
git add docs/plans/2026-01-26-lean-ib-account-summary-design.md
git commit -m "docs: add lean ib account summary design"
```
Expected: commit created.

---

### Task 2: 新增账户摘要快照读取接口（TDD）

**Files:**
- Modify: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersAccountData.cs`
- Modify: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs`
- Test: `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/InteractiveBrokersBrokerageTests.cs` (新增测试)

**Step 1: 写失败测试**

```csharp
[Test]
public void AccountSummarySnapshotReturnsBaseValues()
{
    var ib = new InteractiveBrokersBrokerage(...); // 使用现有测试模式初始化
    ib.SetAccountSummaryValue("BASE", "NetLiquidation", "123456.78");
    var snapshot = ib.GetAccountSummarySnapshot();
    Assert.AreEqual("123456.78", snapshot["BASE:NetLiquidation"]);
}
```

**Step 2: 运行测试（应失败）**

Run:
```bash
dotnet test Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/QuantConnect.InteractiveBrokersBrokerage.Tests.csproj --filter FullyQualifiedName~AccountSummarySnapshotReturnsBaseValues
```
Expected: FAIL (方法不存在/不可访问)。

**Step 3: 最小实现**

- 在 `InteractiveBrokersAccountData` 增加线程安全的快照读取方法。
- 在 `InteractiveBrokersBrokerage` 暴露 `GetAccountSummarySnapshot()`，仅返回拷贝。
- 在测试中使用可控方式写入 AccountProperties（如直接注入或测试辅助方法）。

**Step 4: 运行测试（应通过）**

Run:
```bash
dotnet test Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/QuantConnect.InteractiveBrokersBrokerage.Tests.csproj --filter FullyQualifiedName~AccountSummarySnapshotReturnsBaseValues
```
Expected: PASS.

**Step 5: 提交**

```bash
git add Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersAccountData.cs \
        Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs \
        Lean_git/Tests/Brokerages/InteractiveBrokersBrokerageTests.cs
git commit -m "feat(ib): expose account summary snapshot"
```

---

### Task 3: LeanBridgeResultHandler 使用 IB 账户摘要（TDD）

**Files:**
- Modify: `Lean_git/Engine/Results/LeanBridgeResultHandler.cs`
- Modify: `Lean_git/Engine/TransactionHandlers/BrokerageTransactionHandler.cs`
- Test: `Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs` (新增测试)

**Step 1: 写失败测试**

```csharp
[Test]
public void BuildAccountSummaryUsesBrokerageSnapshot()
{
    var handler = new LeanBridgeResultHandler();
    // 使用测试桩注入 BrokerageTransactionHandler + InteractiveBrokersBrokerage
    var summary = handler.TestBuildAccountSummary(now);
    Assert.AreEqual(123456.78m, summary["items"]["NetLiquidation"]);
}
```

**Step 2: 运行测试（应失败）**

Run:
```bash
dotnet test Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~BuildAccountSummaryUsesBrokerageSnapshot
```
Expected: FAIL.

**Step 3: 最小实现**

- 通过 `TransactionHandler` 获取 brokerage（在 `BrokerageTransactionHandler` 暴露只读属性）。
- 若 brokerage 为 `InteractiveBrokersBrokerage`，读取快照并组装 items。
- 若快照为空则输出空 items + `stale=true`。

**Step 4: 运行测试（应通过）**

Run:
```bash
dotnet test Tests/QuantConnect.Tests.csproj --filter FullyQualifiedName~BuildAccountSummaryUsesBrokerageSnapshot
```
Expected: PASS.

**Step 5: 提交**

```bash
git add Lean_git/Engine/Results/LeanBridgeResultHandler.cs \
        Lean_git/Engine/TransactionHandlers/BrokerageTransactionHandler.cs \
        Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs
git commit -m "feat(bridge): use ib account summary for bridge"
```

---

### Task 4: 集成验证

**Step 1: 运行 Lean live/paper**

Run:
```bash
# 依据现有启动脚本或配置启动
```
Expected: `account_summary.json` 显示 IB 真实净值。

**Step 2: 验证 UI**

- 打开 `http://192.168.1.31:8081/live-trade`
- 确认“账户概览”与 TWS Paper 一致。

**Step 3: 提交验证记录（可选）**

记录 `account_summary.json` 与 TWS 对照结果到日志或文档（如需）。
