# Lean IB Brokerage 源码集成 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 IB 插件源码集成到 Lean_git，并验证 live-interactive（paper）可创建 IB Brokerage/DataQueue 且 Bridge 输出正常。

**Architecture:** 以 submodule 方式引入 `Lean.Brokerages.InteractiveBrokers`，加入 `QuantConnect.Lean.sln`，并在 `Launcher` 引用插件项目保证 DLL 输出；通过单测验证 `InteractiveBrokersBrokerageFactory` 可被 Composer 发现；最后运行 live-interactive 验证 bridge 文件。

**Tech Stack:** Lean (.NET/C#), Git submodule, NUnit, Bash, JSON

---

### Task 1: 引入 IB 插件源码（submodule）并记录路径

**Files:**
- Modify: `/app/stocklean/Lean_git/.gitmodules`
- Create: `/app/stocklean/Lean_git/Brokerages/InteractiveBrokers/` (submodule)

**Step 1: Add submodule**
```bash
git -C /app/stocklean/Lean_git submodule add git@github.com:QuantConnect/Lean.Brokerages.InteractiveBrokers.git Brokerages/InteractiveBrokers
```

**Step 2: Verify csproj path**
```bash
rg --files -g "*.csproj" /app/stocklean/Lean_git/Brokerages/InteractiveBrokers
```
Expected: 找到 `QuantConnect.Brokerages.InteractiveBrokers.csproj`（记下完整路径）

**Step 3: Commit**
```bash
git -C /app/stocklean/Lean_git add .gitmodules Brokerages/InteractiveBrokers
git -C /app/stocklean/Lean_git commit -m "chore: add interactive brokers brokerage submodule"
```

---

### Task 2: 将插件项目加入解决方案并引用到 Launcher

**Files:**
- Modify: `/app/stocklean/Lean_git/QuantConnect.Lean.sln`
- Modify: `/app/stocklean/Lean_git/Launcher/QuantConnect.Lean.Launcher.csproj`

**Step 1: Add project to solution**
```bash
# 用 Task 1 记录的 csproj 路径替换 <IB_CSPROJ>
dotnet sln /app/stocklean/Lean_git/QuantConnect.Lean.sln add <IB_CSPROJ>
```

**Step 2: Add project reference**
```xml
<!-- 在 Launcher csproj 的 ItemGroup 中加入 -->
<ProjectReference Include="<IB_CSPROJ>" />
```

**Step 3: Build**
```bash
dotnet build /app/stocklean/Lean_git/Launcher/QuantConnect.Lean.Launcher.csproj -c Release -v minimal
```
Expected: 成功；并且 `Launcher/bin/Release/` 输出目录包含 IB 插件 DLL

**Step 4: Commit**
```bash
git -C /app/stocklean/Lean_git add QuantConnect.Lean.sln Launcher/QuantConnect.Lean.Launcher.csproj
git -C /app/stocklean/Lean_git commit -m "build: include ib brokerage in launcher"
```

---

### Task 3: 增加工厂发现测试（NUnit）

**Files:**
- Create: `/app/stocklean/Lean_git/Tests/Engine/Brokerages/InteractiveBrokersBrokerageFactoryTests.cs`
- Modify: `/app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj`

**Step 1: Write failing test**
```csharp
using System.Linq;
using NUnit.Framework;
using QuantConnect.Interfaces;
using QuantConnect.Util;
using QuantConnect.Brokerages;

namespace QuantConnect.Tests.Engine.Brokerages
{
    [TestFixture]
    public class InteractiveBrokersBrokerageFactoryTests
    {
        [Test]
        public void ComposerFindsInteractiveBrokersFactory()
        {
            var factories = Composer.Instance.GetExportedValues<IBrokerageFactory>();
            Assert.IsTrue(factories.Any(f => f.BrokerageType == BrokerageName.InteractiveBrokersBrokerage));
        }
    }
}
```

**Step 2: Run test to verify it fails**
```bash
PYTHONNET_PYDLL=/home/hellcat/.pyenv/versions/3.10.19/lib/libpython3.10.so \
PYTHONHOME=/home/hellcat/.pyenv/versions/3.10.19 \
dotnet test /app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj \
  --filter FullyQualifiedName~InteractiveBrokersBrokerageFactoryTests -c Release
```
Expected: FAIL（工厂找不到）

**Step 3: Ensure tests project references plugin**
```xml
<!-- Tests csproj ItemGroup 中加入 -->
<ProjectReference Include="<IB_CSPROJ>" />
```

**Step 4: Re-run test**
Same command as Step 2
Expected: PASS

**Step 5: Commit**
```bash
git -C /app/stocklean/Lean_git add Tests/Engine/Brokerages/InteractiveBrokersBrokerageFactoryTests.cs Tests/QuantConnect.Tests.csproj
git -C /app/stocklean/Lean_git commit -m "test: ensure ib brokerage factory discoverable"
```

---

### Task 4: 重新运行 live-interactive（paper）并验证 bridge 输出

**Files:**
- None (runtime verification)

**Step 1: Run Lean**
```bash
timeout 30s /app/stocklean/scripts/run_lean_live_interactive_paper.sh
```
Expected: 日志无 “brokerage factory not found / Sequence contains no matching element”

**Step 2: Validate bridge outputs**
```bash
ls -l /data/share/stock/data/lean_bridge
cat /data/share/stock/data/lean_bridge/lean_bridge_status.json
cat /data/share/stock/data/lean_bridge/account_summary.json
```
Expected: `last_heartbeat` 刷新，`status=ok`

**Step 3: Record log**
将关键日志片段记录到任务说明（无需代码改动）。

---

### Task 5: 更新 TODO 与清理

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Update TODO**
标记 “IB live-interactive 接入验证” 完成，并记录配置文件与脚本路径。

**Step 2: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: record ib live interactive verification"
```

