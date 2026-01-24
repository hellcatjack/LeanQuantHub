# Lean Bridge ResultHandler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Lean 内新增 `LeanBridgeResultHandler` 输出 bridge 文件，后端读取并展示账户/持仓/行情/成交，形成“Lean 执行唯一来源”的可视化闭环。

**Architecture:** 在 Lean_git 中实现 `LeanBridgeWriter` 与 `LeanBridgeResultHandler`（继承 `LiveTradingResultHandler`），以原子写/节流方式输出 `account_summary.json`、`positions.json`、`quotes.json`、`execution_events.jsonl`、`lean_bridge_status.json`。主仓配置执行时指定 `result-handler` 与 `lean-bridge-output-dir`，后端按心跳 TTL 判断 stale。

**Tech Stack:** Lean (.NET/C#), FastAPI/Python, JSON/JSONL, NUnit, Pytest

---

### Task 1: Lean_git 增加桥接写入器（LeanBridgeWriter）

**Files:**
- Create: `/app/stocklean/Lean_git/Engine/Results/LeanBridgeWriter.cs`
- Create: `/app/stocklean/Lean_git/Tests/Engine/Results/LeanBridgeWriterTests.cs`

**Step 1: Write the failing test**
```csharp
using System;
using System.IO;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using QuantConnect.Lean.Engine.Results;

namespace QuantConnect.Tests.Engine.Results
{
    [TestFixture]
    public class LeanBridgeWriterTests
    {
        [Test]
        public void WritesJsonAtomically()
        {
            var dir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
            var writer = new LeanBridgeWriter(dir);
            writer.WriteJsonAtomic("account_summary.json", new { source = "lean_bridge", items = new { NetLiquidation = 100m } });

            var path = Path.Combine(dir, "account_summary.json");
            Assert.IsTrue(File.Exists(path));
            var json = JObject.Parse(File.ReadAllText(path));
            Assert.AreEqual("lean_bridge", (string)json["source"]);
        }

        [Test]
        public void AppendsJsonLines()
        {
            var dir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
            var writer = new LeanBridgeWriter(dir);
            writer.AppendJsonLine("execution_events.jsonl", new { orderId = 1, status = "FILLED" });
            writer.AppendJsonLine("execution_events.jsonl", new { orderId = 2, status = "NEW" });

            var path = Path.Combine(dir, "execution_events.jsonl");
            var lines = File.ReadAllLines(path);
            Assert.AreEqual(2, lines.Length);
        }
    }
}
```

**Step 2: Run test to verify it fails**
Run: `dotnet test /app/stocklean/Lean_git/Tests/Tests.csproj --filter FullyQualifiedName~LeanBridgeWriterTests`
Expected: FAIL (class not found)

**Step 3: Write minimal implementation**
```csharp
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Serialization;

namespace QuantConnect.Lean.Engine.Results
{
    public class LeanBridgeWriter
    {
        private readonly string _outputDir;
        private readonly JsonSerializerSettings _settings;

        public LeanBridgeWriter(string outputDir)
        {
            _outputDir = outputDir;
            _settings = new JsonSerializerSettings
            {
                ContractResolver = new DefaultContractResolver
                {
                    NamingStrategy = new CamelCaseNamingStrategy
                    {
                        ProcessDictionaryKeys = false,
                        OverrideSpecifiedNames = true
                    }
                }
            };
            Directory.CreateDirectory(_outputDir);
        }

        public void WriteJsonAtomic(string filename, object payload)
        {
            Directory.CreateDirectory(_outputDir);
            var path = Path.Combine(_outputDir, filename);
            var tmp = path + ".tmp";
            var json = JsonConvert.SerializeObject(payload, Formatting.Indented, _settings);
            File.WriteAllText(tmp, json);
            File.Move(tmp, path, true);
        }

        public void AppendJsonLine(string filename, object payload)
        {
            Directory.CreateDirectory(_outputDir);
            var path = Path.Combine(_outputDir, filename);
            var json = JsonConvert.SerializeObject(payload, _settings);
            File.AppendAllText(path, json + "\n");
        }
    }
}
```

**Step 4: Run test to verify it passes**
Run: `dotnet test /app/stocklean/Lean_git/Tests/Tests.csproj --filter FullyQualifiedName~LeanBridgeWriterTests`
Expected: PASS

**Step 5: Commit**
```bash
git -C /app/stocklean/Lean_git add Engine/Results/LeanBridgeWriter.cs Tests/Engine/Results/LeanBridgeWriterTests.cs
git -C /app/stocklean/Lean_git commit -m "feat: add lean bridge writer"
```

---

### Task 2: Lean_git 增加 LeanBridgeResultHandler（继承 LiveTradingResultHandler）

**Files:**
- Create: `/app/stocklean/Lean_git/Engine/Results/LeanBridgeResultHandler.cs`
- Create: `/app/stocklean/Lean_git/Tests/Engine/Results/LeanBridgeResultHandlerTests.cs`

**Step 1: Write the failing test**
```csharp
using System;
using System.IO;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using QuantConnect.Configuration;
using QuantConnect.Lean.Engine.Results;
using QuantConnect.Lean.Engine.TransactionHandlers;
using QuantConnect.Messaging;
using QuantConnect.Packets;
using QuantConnect.Tests.Engine.DataFeeds;

namespace QuantConnect.Tests.Engine.Results
{
    [TestFixture]
    public class LeanBridgeResultHandlerTests
    {
        [Test]
        public void WritesBridgeFilesOnProcess()
        {
            var dir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
            Config.Set("lean-bridge-output-dir", dir);
            Config.Set("lean-bridge-snapshot-seconds", "0");
            Config.Set("lean-bridge-heartbeat-seconds", "0");

            using var messaging = new Messaging();
            var handler = new LeanBridgeResultHandler();
            handler.Initialize(new ResultHandlerInitializeParameters(new LiveNodePacket(), messaging, null, new BacktestingTransactionHandler(), null));

            var algorithm = new AlgorithmStub(createDataManager: false);
            algorithm.SetFinishedWarmingUp();
            algorithm.AddEquity("SPY").Holdings.SetHoldings(1, 10);
            handler.SetAlgorithm(algorithm, 100000);

            handler.ProcessSynchronousEvents(true);

            Assert.IsTrue(File.Exists(Path.Combine(dir, "account_summary.json")));
            Assert.IsTrue(File.Exists(Path.Combine(dir, "positions.json")));
            Assert.IsTrue(File.Exists(Path.Combine(dir, "lean_bridge_status.json")));

            var json = JObject.Parse(File.ReadAllText(Path.Combine(dir, "account_summary.json")));
            Assert.AreEqual("lean_bridge", (string)json["source"]);
        }
    }
}
```

**Step 2: Run test to verify it fails**
Run: `dotnet test /app/stocklean/Lean_git/Tests/Tests.csproj --filter FullyQualifiedName~LeanBridgeResultHandlerTests`
Expected: FAIL (class not found)

**Step 3: Write minimal implementation**
```csharp
using System;
using System.Collections.Generic;
using System.IO;
using QuantConnect.Configuration;
using QuantConnect.Lean.Engine.Results;
using QuantConnect.Orders;
using QuantConnect.Securities;

namespace QuantConnect.Lean.Engine.Results
{
    public class LeanBridgeResultHandler : LiveTradingResultHandler
    {
        private LeanBridgeWriter _writer;
        private DateTime _nextSnapshotUtc;
        private DateTime _nextHeartbeatUtc;
        private TimeSpan _snapshotPeriod;
        private TimeSpan _heartbeatPeriod;
        private string _lastError;
        private DateTime? _lastErrorAt;
        private bool _degraded;

        public override void Initialize(ResultHandlerInitializeParameters parameters)
        {
            base.Initialize(parameters);
            var outputDir = Config.Get("lean-bridge-output-dir", Path.Combine(Globals.DataFolder, "lean_bridge"));
            _snapshotPeriod = TimeSpan.FromSeconds(Config.GetInt("lean-bridge-snapshot-seconds", 2));
            _heartbeatPeriod = TimeSpan.FromSeconds(Config.GetInt("lean-bridge-heartbeat-seconds", 5));
            _writer = new LeanBridgeWriter(outputDir);
            _nextSnapshotUtc = DateTime.MinValue;
            _nextHeartbeatUtc = DateTime.MinValue;
        }

        public override void ProcessSynchronousEvents(bool forceProcess = false)
        {
            base.ProcessSynchronousEvents(forceProcess);
            var now = DateTime.UtcNow;
            if (forceProcess || now >= _nextSnapshotUtc)
            {
                _nextSnapshotUtc = now.Add(_snapshotPeriod);
                TryWriteSnapshots(now);
            }
            if (forceProcess || now >= _nextHeartbeatUtc)
            {
                _nextHeartbeatUtc = now.Add(_heartbeatPeriod);
                TryWriteStatus(now);
            }
        }

        public override void OrderEvent(OrderEvent newEvent)
        {
            base.OrderEvent(newEvent);
            TryAppendExecutionEvent(newEvent);
        }

        private void TryWriteSnapshots(DateTime now)
        {
            try
            {
                _writer.WriteJsonAtomic("account_summary.json", BuildAccountSummary(now));
                _writer.WriteJsonAtomic("positions.json", BuildPositions(now));
                _writer.WriteJsonAtomic("quotes.json", BuildQuotes(now));
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
                _lastErrorAt = now;
                _degraded = true;
            }
        }

        private void TryWriteStatus(DateTime now)
        {
            var payload = new Dictionary<string, object>
            {
                ["status"] = _degraded ? "degraded" : "ok",
                ["last_heartbeat"] = now.ToString("O"),
                ["last_error"] = _lastError,
                ["last_error_at"] = _lastErrorAt?.ToString("O"),
                ["source"] = "lean_bridge",
                ["stale"] = false
            };
            try
            {
                _writer.WriteJsonAtomic("lean_bridge_status.json", payload);
            }
            catch
            {
                // last resort: swallow to avoid impacting execution
            }
        }

        private void TryAppendExecutionEvent(OrderEvent newEvent)
        {
            try
            {
                _writer.AppendJsonLine("execution_events.jsonl", new Dictionary<string, object>
                {
                    ["order_id"] = newEvent.OrderId,
                    ["symbol"] = newEvent.Symbol?.Value,
                    ["status"] = newEvent.Status.ToString(),
                    ["filled"] = newEvent.FillQuantity,
                    ["fill_price"] = newEvent.FillPrice,
                    ["direction"] = newEvent.Direction.ToString(),
                    ["time"] = newEvent.UtcTime.ToString("O")
                });
            }
            catch (Exception ex)
            {
                _lastError = ex.Message;
                _lastErrorAt = DateTime.UtcNow;
                _degraded = true;
            }
        }

        private Dictionary<string, object> BuildAccountSummary(DateTime now)
        {
            var items = new Dictionary<string, object>
            {
                ["NetLiquidation"] = Algorithm.Portfolio.TotalPortfolioValue,
                ["TotalCashValue"] = Algorithm.Portfolio.Cash,
                ["BuyingPower"] = Algorithm.Portfolio.MarginRemaining,
                ["UnrealizedPnL"] = Algorithm.Portfolio.TotalUnrealizedProfit,
                ["TotalHoldingsValue"] = Algorithm.Portfolio.TotalHoldingsValue
            };
            return new Dictionary<string, object>
            {
                ["items"] = items,
                ["refreshed_at"] = now.ToString("O"),
                ["source"] = "lean_bridge",
                ["stale"] = false
            };
        }

        private Dictionary<string, object> BuildPositions(DateTime now)
        {
            var holdings = GetHoldings(Algorithm.Securities.Values, Algorithm.SubscriptionManager.SubscriptionDataConfigService, onlyInvested: true);
            var list = new List<Dictionary<string, object>>();
            foreach (var entry in holdings)
            {
                var holding = entry.Value;
                list.Add(new Dictionary<string, object>
                {
                    ["symbol"] = holding.Symbol.Value,
                    ["quantity"] = holding.Quantity,
                    ["avg_cost"] = holding.AveragePrice,
                    ["market_value"] = holding.MarketValue,
                    ["unrealized_pnl"] = holding.UnrealizedProfit,
                    ["currency"] = holding.CurrencySymbol
                });
            }
            return new Dictionary<string, object>
            {
                ["items"] = list,
                ["refreshed_at"] = now.ToString("O"),
                ["source"] = "lean_bridge",
                ["stale"] = false
            };
        }

        private Dictionary<string, object> BuildQuotes(DateTime now)
        {
            var list = new List<Dictionary<string, object>>();
            foreach (var security in Algorithm.Securities.Values)
            {
                if (!security.IsTradable || security.Symbol.IsCanonical()) continue;
                list.Add(new Dictionary<string, object>
                {
                    ["symbol"] = security.Symbol.Value,
                    ["bid"] = security.BidPrice,
                    ["ask"] = security.AskPrice,
                    ["last"] = security.Price,
                    ["timestamp"] = security.Time.ToUniversalTime().ToString("O")
                });
            }
            return new Dictionary<string, object>
            {
                ["items"] = list,
                ["refreshed_at"] = now.ToString("O"),
                ["source"] = "lean_bridge",
                ["stale"] = false
            };
        }
    }
}
```

**Step 4: Run test to verify it passes**
Run: `dotnet test /app/stocklean/Lean_git/Tests/Tests.csproj --filter FullyQualifiedName~LeanBridgeResultHandlerTests`
Expected: PASS

**Step 5: Commit**
```bash
git -C /app/stocklean/Lean_git add Engine/Results/LeanBridgeResultHandler.cs Tests/Engine/Results/LeanBridgeResultHandlerTests.cs
git -C /app/stocklean/Lean_git commit -m "feat: add lean bridge result handler"
```

---

### Task 3: 主仓写入 Lean 执行配置（result-handler + output dir）

**Files:**
- Modify: `backend/app/services/lean_execution.py`
- Modify: `backend/tests/test_lean_execution_config.py`
- Modify: `configs/lean_config_template.json`

**Step 1: Write the failing test**
```python
from app.services.lean_execution import build_execution_config


def test_execution_config_includes_bridge_result_handler():
    cfg = build_execution_config(intent_path="/tmp/intent.json", brokerage="InteractiveBrokersBrokerage")
    assert cfg["result-handler"].endswith("LeanBridgeResultHandler")
    assert cfg["lean-bridge-output-dir"] == "/data/share/stock/data/lean_bridge"
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_config.py::test_execution_config_includes_bridge_result_handler`
Expected: FAIL (missing keys)

**Step 3: Write minimal implementation**
```python
# backend/app/services/lean_execution.py
from app.core.config import settings
from pathlib import Path


def _bridge_output_dir() -> str:
    base = settings.data_root or "/data/share/stock/data"
    return str(Path(base) / "lean_bridge")


def build_execution_config(*, intent_path: str, brokerage: str) -> dict:
    return {
        "brokerage": brokerage,
        "execution-intent-path": intent_path,
        "result-handler": "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler",
        "lean-bridge-output-dir": _bridge_output_dir(),
    }
```

**Step 4: Update config template**
```json
// configs/lean_config_template.json
"lean-bridge-output-dir": "/data/share/stock/data/lean_bridge",
"environments": {
  "backtesting": { ... },
  "live": {
    "live-mode": true,
    "setup-handler": "QuantConnect.Lean.Engine.Setup.BrokerageSetupHandler",
    "result-handler": "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler",
    "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.LiveTradingDataFeed",
    "real-time-handler": "QuantConnect.Lean.Engine.RealTime.LiveTradingRealTimeHandler",
    "history-provider": ["QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"],
    "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BrokerageTransactionHandler"
  }
}
```

**Step 5: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_config.py::test_execution_config_includes_bridge_result_handler`
Expected: PASS

**Step 6: Commit**
```bash
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_config.py configs/lean_config_template.json
git commit -m "feat: add lean bridge result handler config"
```

---

### Task 4: 后端 bridge stale 计算与兼容读取

**Files:**
- Modify: `backend/app/services/lean_bridge_reader.py`
- Modify: `backend/tests/test_lean_bridge_reader.py`

**Step 1: Write the failing test**
```python
from datetime import datetime, timedelta
import json

def test_bridge_status_stale_by_heartbeat(tmp_path):
    payload = {"status": "ok", "last_heartbeat": (datetime.utcnow() - timedelta(minutes=10)).isoformat()}
    (tmp_path / "lean_bridge_status.json").write_text(json.dumps(payload), encoding="utf-8")
    result = read_bridge_status(tmp_path)
    assert result["stale"] is True
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_reader.py::test_bridge_status_stale_by_heartbeat`
Expected: FAIL (stale not computed)

**Step 3: Write minimal implementation**
```python
# backend/app/services/lean_bridge_reader.py
from datetime import datetime, timedelta


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def read_bridge_status(root: Path) -> dict:
    path = root / "lean_bridge_status.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"status": "missing", "stale": True}
    heartbeat = _parse_iso(str(data.get("last_heartbeat") or ""))
    stale = True
    if heartbeat:
        stale = datetime.utcnow() - heartbeat > timedelta(seconds=10)
    data.setdefault("status", "ok")
    data["stale"] = bool(stale)
    return data
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_reader.py::test_bridge_status_stale_by_heartbeat`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_bridge_reader.py backend/tests/test_lean_bridge_reader.py
git commit -m "feat: compute lean bridge stale from heartbeat"
```

---

### Task 5: 同步 TODO 状态

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Update status**
- 将 Phase 1.1/1.2/1.3 中已完成项标记为 `[x]`。
- 增加桥接输出目录完成状态。

**Step 2: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: update ib auto trade todo status"
```
