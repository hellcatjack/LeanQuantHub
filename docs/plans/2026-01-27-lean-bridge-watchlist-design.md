# Lean Bridge Watchlist 设计

## 背景
当前 PreTrade 的 `market_snapshot` 依赖 Lean Bridge 的 `quotes.json`。Lean Bridge 仅输出已订阅标的报价，而现用 `LeanBridgeSmokeAlgorithm` 不订阅任何标的，导致决策快照中大量标的缺失报价，`market_snapshot_failed`。

## 目标
- 通过 **PreTrade → Lean Bridge Watchlist** 机制，确保决策快照标的全部被订阅并产生报价。
- 不破坏现有“Lean 输出/日志/事件桥接”的架构边界。

## 方案概述
1) **Watchlist 文件**：由后端写入 `lean_bridge/watchlist.json`，内容包含决策快照标的 + 当前持仓标的（去重、规范化）。
2) **Lean 订阅**：`LeanBridgeSmokeAlgorithm` 从 `lean-bridge-watchlist-path` 读取并增量 `AddEquity`；支持周期性刷新（`lean-bridge-watchlist-refresh-seconds`）。
3) **报价输出**：`LeanBridgeResultHandler.BuildQuotes()` 保持基于 `Algorithm.Securities` 输出，满足 PreTrade `market_snapshot` 校验。

## 数据结构
`watchlist.json`（建议格式）:
```json
{
  "symbols": ["AAPL", "MSFT"],
  "updated_at": "2026-01-27T01:20:00Z",
  "source": "pretrade",
  "project_id": 16,
  "decision_snapshot_id": 25
}
```

## 错误处理
- Watchlist 文件缺失/解析失败：保留已订阅集，不移除订阅，仅记录日志。
- Watchlist 为空：不新增订阅，等待下次刷新。

## 测试与验证
- C# 单测：watchlist 解析、去重与空文件处理。
- 后端单测：决策快照写入 watchlist（含 BOM 处理）。
- 手工验证：更新 watchlist 后 `quotes.json` 覆盖决策快照标的，PreTrade `market_snapshot` 通过。
