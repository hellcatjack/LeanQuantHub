# Lean IB Live-Interactive Paper 验证 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 通过独立配置与脚本启动 Lean live-interactive（TWS paper），验证 Lean Bridge 文件持续输出且账户信息可读。

**Architecture:** 在主仓新增独立的 live-interactive 配置与启动脚本，配置指向 LeanBridgeResultHandler 与 LeanBridgeSmokeAlgorithm；执行后通过 bridge 文件与心跳判断链路是否正常。

**Tech Stack:** Lean (.NET/C#), Bash, Python (pytest), JSON

---

### Task 1: 新增 live-interactive 配置并校验关键字段

**Files:**
- Create: `configs/lean_live_interactive_paper.json`
- Create: `backend/tests/test_lean_live_config.py`

**Step 1: Write the failing test**
```python
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".." / "configs" / "lean_live_interactive_paper.json"


def test_lean_live_interactive_config_has_required_fields():
    assert CONFIG.exists(), "lean_live_interactive_paper.json should exist"
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert payload.get("environment") == "live-interactive"
    assert payload.get("result-handler") == "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    assert payload.get("lean-bridge-output-dir") == "/data/share/stock/data/lean_bridge"

    assert payload.get("ib-host") == "192.168.1.31"
    assert payload.get("ib-port") == "7497"
    assert payload.get("ib-client-id") == "101"
    assert payload.get("ib-trading-mode") == "paper"

    assert payload.get("algorithm-type-name") == "LeanBridgeSmokeAlgorithm"
    assert payload.get("algorithm-location")
    assert payload.get("data-folder") == "/data/share/stock/data/lean"
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_live_config.py::test_lean_live_interactive_config_has_required_fields`
Expected: FAIL (config file missing)

**Step 3: Write minimal implementation**
```json
{
  "environment": "live-interactive",
  "algorithm-type-name": "LeanBridgeSmokeAlgorithm",
  "algorithm-language": "CSharp",
  "algorithm-location": "/app/stocklean/Lean_git/Algorithm.CSharp/bin/Release/QuantConnect.Algorithm.CSharp.dll",
  "data-folder": "/data/share/stock/data/lean",
  "log-handler": "QuantConnect.Logging.CompositeLogHandler",
  "messaging-handler": "QuantConnect.Messaging.Messaging",
  "job-queue-handler": "QuantConnect.Queues.JobQueue",
  "api-handler": "QuantConnect.Api.Api",
  "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
  "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
  "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
  "data-channel-provider": "DataChannelProvider",
  "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore",
  "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
  "force-exchange-always-open": true,
  "lean-bridge-output-dir": "/data/share/stock/data/lean_bridge",
  "lean-bridge-snapshot-seconds": "2",
  "lean-bridge-heartbeat-seconds": "2",
  "ib-host": "192.168.1.31",
  "ib-port": "7497",
  "ib-client-id": "101",
  "ib-trading-mode": "paper",
  "result-handler": "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
}
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_live_config.py::test_lean_live_interactive_config_has_required_fields`
Expected: PASS

**Step 5: Commit**
```bash
git add configs/lean_live_interactive_paper.json backend/tests/test_lean_live_config.py
git commit -m "feat: add lean live-interactive paper config"
```

---

### Task 2: 添加 Lean 启动脚本并进行语法校验

**Files:**
- Create: `scripts/run_lean_live_interactive_paper.sh`

**Step 1: Write the failing test**
```bash
bash -n scripts/run_lean_live_interactive_paper.sh
```
Expected: FAIL (file missing)

**Step 2: Write minimal implementation**
```bash
#!/usr/bin/env bash
set -euo pipefail

PYTHONNET_PYDLL="/home/hellcat/.pyenv/versions/3.10.19/lib/libpython3.10.so"
PYTHONHOME="/home/hellcat/.pyenv/versions/3.10.19"

export PYTHONNET_PYDLL
export PYTHONHOME

CONFIG="/app/stocklean/configs/lean_live_interactive_paper.json"
LAUNCHER="/app/stocklean/Lean_git/Launcher/bin/Release/QuantConnect.Lean.Launcher.dll"

exec dotnet "$LAUNCHER" --config "$CONFIG"
```

**Step 3: Run test to verify it passes**
Run: `bash -n scripts/run_lean_live_interactive_paper.sh`
Expected: PASS

**Step 4: Commit**
```bash
git add scripts/run_lean_live_interactive_paper.sh
git commit -m "chore: add lean live interactive runner"
```

---

### Task 3: 启动 Lean Live 并验证 bridge 文件

**Files:**
- None (runtime verification only)

**Step 1: Run Lean live-interactive (paper)**
Run: `timeout 30s scripts/run_lean_live_interactive_paper.sh`
Expected: Lean 启动成功，无连接错误。

**Step 2: Validate bridge outputs**
Run:
```bash
ls -l /data/share/stock/data/lean_bridge
cat /data/share/stock/data/lean_bridge/lean_bridge_status.json
cat /data/share/stock/data/lean_bridge/account_summary.json
```
Expected: `last_heartbeat` 更新、`status=ok`、账户净值/现金正确。

**Step 3: Record results**
在任务记录中写明日志关键片段与文件时间戳。

---

### Task 4: 可选 — 行情订阅验证

**Files:**
- Modify: `/app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeSmokeAlgorithm.cs`

**Step 1: Write the failing test**
```bash
# 运行 Lean 后应看到 quotes.json 有报价
```
Expected: quotes.json 为空

**Step 2: Implement minimal change**
在 `Initialize()` 增加 `AddEquity("SPY", Resolution.Minute)`

**Step 3: Re-run Lean and verify**
Run: `timeout 30s scripts/run_lean_live_interactive_paper.sh`
Expected: `quotes.json` 出现 SPY 报价

**Step 4: Commit**
```bash
# Lean_git 单独提交
```

---

### Task 5: 文档与验收记录

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Update TODO status**
标记“Lean IB Live paper 验证”完成，并记录配置路径。

**Step 2: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: record lean ib live paper verification"
```

