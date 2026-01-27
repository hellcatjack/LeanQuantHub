# PIT + Decision Snapshot (2026-01-23) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 使用 2026-01-23 PIT 快照重建决策并发起 Paper 交易。

**Architecture:** 通过 API 触发 PIT Weekly 与 PIT Fundamentals 作业，随后基于指定 snapshot_date 生成 Decision Snapshot，最后创建并执行 paper Trade Run。

**Tech Stack:** FastAPI + MySQL, PIT scripts, Decision Snapshot service, Trade executor。

### Task 1: 触发 PIT Weekly（2026-01-23）

**Files:**
- 无代码修改（API 调用）

**Step 1: 发起 PIT Weekly 作业**

Run:
```bash
python - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8021"
payload = {
  "start": "2026-01-23",
  "end": "2026-01-23",
  "rebalance_mode": "weekday",
  "rebalance_day": "friday",
  "benchmark": "SPY",
  "vendor_preference": "Alpha",
  "data_root": "/data/share/stock/data"
}
req = urllib.request.Request(base + "/api/pit/weekly-jobs", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req).read()))
PY
```
Expected: 返回 job_id。

**Step 2: 轮询 PIT Weekly 作业完成**

Run:
```bash
python - <<'PY'
import json, time, urllib.request
base = "http://127.0.0.1:8021"
job_id = int(input("job_id: "))
while True:
  data = json.loads(urllib.request.urlopen(base + f"/api/pit/weekly-jobs/{job_id}").read())
  print(data["status"], data.get("message"), data.get("last_snapshot_path"))
  if data["status"] in {"success","failed","blocked","canceled"}:
    break
  time.sleep(5)
PY
```
Expected: `status=success` 且 `last_snapshot_path` 含 `pit_20260123.csv`。

### Task 2: 触发 PIT Fundamentals（2026-01-23）

**Files:**
- 无代码修改（API 调用）

**Step 1: 发起 PIT Fundamentals 作业**

Run:
```bash
python - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8021"
payload = {
  "start": "2026-01-23",
  "end": "2026-01-23",
  "benchmark": "SPY",
  "vendor_preference": "Alpha",
  "pit_dir": "/data/share/stock/data/universe/pit_weekly",
  "fundamentals_dir": "/data/share/stock/data/fundamentals/alpha",
  "output_dir": "/data/share/stock/data/factors/pit_weekly_fundamentals",
  "data_root": "/data/share/stock/data",
  "refresh_fundamentals": false,
  "build_pit_fundamentals": true
}
req = urllib.request.Request(base + "/api/pit/fundamental-jobs", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req).read()))
PY
```
Expected: 返回 job_id。

**Step 2: 轮询 PIT Fundamentals 作业完成**

Run:
```bash
python - <<'PY'
import json, time, urllib.request
base = "http://127.0.0.1:8021"
job_id = int(input("job_id: "))
while True:
  data = json.loads(urllib.request.urlopen(base + f"/api/pit/fundamental-jobs/{job_id}").read())
  print(data["status"], data.get("message"), data.get("output_dir"))
  if data["status"] in {"success","failed","blocked","canceled"}:
    break
  time.sleep(5)
PY
```
Expected: `status=success`。

### Task 3: 生成 Decision Snapshot（snapshot_date=2026-01-23）

**Files:**
- 无代码修改（API 调用）

**Step 1: 发起 Decision Snapshot**

Run:
```bash
python - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8021"
payload = {"project_id": 16, "snapshot_date": "2026-01-23"}
req = urllib.request.Request(base + "/api/decisions/run", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req).read()))
PY
```
Expected: 返回 decision_snapshot_id。

**Step 2: 轮询 Decision Snapshot 完成**

Run:
```bash
python - <<'PY'
import json, time, urllib.request
base = "http://127.0.0.1:8021"
snapshot_id = int(input("snapshot_id: "))
while True:
  data = json.loads(urllib.request.urlopen(base + f"/api/decisions/{snapshot_id}").read())
  print(data["status"], data.get("snapshot_date"))
  if data["status"] in {"success","failed"}:
    break
  time.sleep(5)
PY
```
Expected: `status=success` 且 `snapshot_date=2026-01-23`。

### Task 4: Paper 交易执行

**Files:**
- 无代码修改（API 调用）

**Step 1: 创建 Trade Run（paper）**

Run:
```bash
python - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8021"
snapshot_id = int(input("snapshot_id: "))
payload = {"project_id": 16, "decision_snapshot_id": snapshot_id, "mode": "paper"}
req = urllib.request.Request(base + "/api/trade/runs", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req).read()))
PY
```
Expected: 返回 trade_run_id。

**Step 2: 执行 Trade Run（paper）**

Run:
```bash
python - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8021"
run_id = int(input("trade_run_id: "))
payload = {"dry_run": false, "force": false}
req = urllib.request.Request(base + f"/api/trade/runs/{run_id}/execute", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req).read()))
PY
```
Expected: 返回执行结果（filled/cancelled/rejected/skipped）。

### Task 5: 验证

**Step 1: 验证交易结果**

Run:
```bash
python - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:8021"
run_id = int(input("trade_run_id: "))
print(json.loads(urllib.request.urlopen(base + f"/api/trade/runs/{run_id}").read()))
PY
```
Expected: `status` 为 success/finished（视实现）且订单数非空。
