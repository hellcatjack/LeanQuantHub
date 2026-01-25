# Lean IB Live Paper Bridge 验证设计

## 背景
当前系统已完成 Lean Bridge 输出链路与后端读取改造，但仍需在 **TWS paper** 环境验证：
- Lean live-interactive 能否稳定连接 IB
- Bridge 文件是否持续落地并可供前端展示
- 连接与权限问题是否可被清晰诊断

## 目标
- 使用 **TWS paper**（`192.168.1.31:7497`，`clientId=101`）启动 Lean live-interactive。
- Bridge 输出持续刷新：`lean_bridge_status.json` 心跳更新；`account_summary.json` 可读且数值合理。
- 记录清晰的启动步骤与故障排查路径。

## 非目标
- 不验证真实成交（不提交订单）。
- 不要求行情订阅成功（第一阶段仅验证账户与心跳）。
- 不修改研究/回测/信号链路。

## 方案选择
- **采用 live-interactive + IB Brokerage/DataQueue**（推荐）：验证与生产路径一致。
- 放弃 live-paper + LiveDataQueue（已验证不可用，会抛 `NotImplemented`）。

## 设计要点
### 1) 启动配置（独立 JSON）
- 新增专用配置文件，避免污染默认 `config.json`。
- 关键项：
  - `environment = live-interactive`
  - `result-handler = QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler`
  - `lean-bridge-output-dir = /data/share/stock/data/lean_bridge`
  - `ib-host = 192.168.1.31`
  - `ib-port = 7497`
  - `ib-client-id = 101`
  - `ib-trading-mode = paper`
- 指定算法为 `LeanBridgeSmokeAlgorithm`（无行情订阅），用于验证桥接文件稳定输出。
- 设置 `PYTHONNET_PYDLL` 与 `PYTHONHOME`，确保 pythonnet 正常初始化。

### 2) 验证路径
- **第一阶段（账户与心跳）**：
  - 启动 Lean Live 20–30 秒。
  - `lean_bridge_status.json.last_heartbeat` 连续更新。
  - `account_summary.json` 中净值/现金与 TWS paper 一致。
- **第二阶段（可选行情验证）**：
  - 将算法改为订阅低频标的（例如 `SPY`），确认 `quotes.json` 出现报价。

## 故障排查
- **连接失败**：检查 TWS API 开启、IP 白名单、`clientId` 冲突。
- **行情订阅失败**：检查 IB market data 权限与交易时间；必要时启用延迟行情。
- **bridge 文件不更新**：检查输出路径权限，确认 ResultHandler 初始化日志。
- **Python GIL 崩溃**：检查 `PYTHONNET_PYDLL`/`PYTHONHOME` 指向 Python 3.10.19。

## 成功标准
- Bridge 文件在 `/data/share/stock/data/lean_bridge` 生成并持续更新。
- 日志无 IB 连接错误，心跳可持续刷新。

