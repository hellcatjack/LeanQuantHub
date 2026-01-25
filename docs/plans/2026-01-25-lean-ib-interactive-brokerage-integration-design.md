# Lean IB Interactive Brokerage 源码集成设计

## 背景
当前 Lean_git 无法创建 `InteractiveBrokersBrokerage` 工厂，启动 live-interactive 时出现 “brokerage factory not found / Sequence contains no matching element”。
文档显示 IB 功能通过独立插件仓库提供，因此需要将 `Lean.Brokerages.InteractiveBrokers` 源码集成到 Lean_git，并确保 Composer 可以发现 IB 工厂类。

## 目标
- 将 IB 插件源码合入 Lean_git，并纳入构建链路。
- live-interactive（paper）模式下可成功创建 IB Brokerage/DataQueue。
- Lean Bridge 输出文件持续更新并可用于前端展示。

## 非目标
- 不改动研究/回测/信号链路。
- 不要求真实下单或成交验证（仅验证账户/行情链路）。

## 方案选择
- **源码集成（本方案）**：将 `Lean.Brokerages.InteractiveBrokers` 作为子目录/子模块引入 Lean_git，加入解决方案并编译进输出目录。
- 不采用外部 DLL 或 CLI 自动拉取方案，避免部署差异与不可控版本漂移。

## 架构与集成点
1) **源码集成**
- 插件路径建议：`/app/stocklean/Lean_git/Brokerages/InteractiveBrokers/`。
- 将 `QuantConnect.Brokerages.InteractiveBrokers.csproj` 添加到 `QuantConnect.Lean.sln`。
- 确保 `Launcher` 或 `Brokerages` 项目引用该插件项目，使其 DLL 出现在 `Launcher/bin/Release/` 输出目录。

2) **加载机制**
- Lean 使用 `Composer` 扫描输出目录，发现 `InteractiveBrokersBrokerageFactory`。
- 若加载成功，日志中不再出现 “Not able to fetch brokerage factory”。

3) **运行配置**
- `configs/lean_live_interactive_paper.json`：
  - `live-mode-brokerage = InteractiveBrokersBrokerage`
  - `data-queue-handler = ["InteractiveBrokersBrokerage"]`
  - `ib-host = 192.168.1.31`
  - `ib-port = 7497`
  - `ib-client-id = 101`
  - `ib-trading-mode = paper`
  - `result-handler = QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler`
  - `lean-bridge-output-dir = /data/share/stock/data/lean_bridge`

4) **验证流程**
- 启动 `scripts/run_lean_live_interactive_paper.sh` 30 秒，确认：
  - 不再出现工厂加载错误。
  - `lean_bridge_status.json.last_heartbeat` 连续更新。
  - `account_summary.json` 净值/现金与 TWS paper 一致。
- 如需行情验证，临时在算法中订阅 `SPY`，观察 `quotes.json` 更新。

## 风险与对策
- **工厂未被加载**：检查插件 DLL 是否输出到 `Launcher/bin/Release/`，并确认解决方案引用关系。
- **IB 连接失败**：检查 TWS API 白名单与 clientId 冲突。
- **行情订阅失败**：检查 IB 行情权限或启用延迟行情。

## 成功标准
- IB Brokerage 工厂可被发现并成功创建。
- bridge 文件持续更新，前端可读账户/持仓/行情。

