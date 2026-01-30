# Lean Bridge Watchlist 对齐策略设计

## 背景
当前 Leader 的 watchlist 来自全量 universe，容易触发 IB 的行情订阅上限，导致执行器下单失败（如 GEV/AVGO/TER 未成交）。需要将 Leader watchlist 与“当前执行意图”对齐，并确保包含当前持仓。

## 目标
- Leader watchlist 优先覆盖：**当前持仓 + 当前执行意图**。
- 订阅数量可控（默认上限 200）。
- 保持现有 watchlist 输出格式兼容前端与其他服务。
- 降低订阅超限导致的交易失败。

## 数据来源与优先级
1) **当前持仓**：从 Lean Bridge `positions.json` 读取 symbol 列表。
2) **当前执行意图**：查询 trade_run 状态为 `running/queued` 的记录，读取其 `order_intent_path` 中 symbols。
3) **兜底 universe（可选）**：仅当总数不足 200 时，从现有 `build_leader_watchlist` 补齐。

合并策略：
- `symbols = unique_preserve_order(positions + intents + fallback)`
- `symbols = symbols[:200]`
- 内容未变化则不重写文件

## 输出格式
沿用当前 `watchlist.json`：
```json
{
  "symbols": ["AAPL", "AVGO", "GEV"],
  "updated_at": "2026-01-30T20:00:00Z"
}
```

## 错误处理
- `positions.json` 读取失败：视为空列表，记录 WARN。
- intent 文件缺失/解析失败：跳过该 run，记录 WARN（包含 run_id/path）。
- 合并结果为空：保留原 watchlist 不变并记录 WARN。

## 可观测性
- 每次生成输出统计：`positions_count / intents_count / fallback_count / final_count`。
- 当 watchlist 发生变化时记录 INFO（前后长度 + 样本）。
- 若截断到 200，记录 INFO：`truncated=true`。

## 测试策略（TDD）
- 合并排序与去重
- intent 解析失败容错
- 截断到 200
- 仅 fallback 场景

## 影响范围
- 修改 `backend/app/services/lean_bridge_leader.py` 的 watchlist 生成逻辑
- 不改变现有 watchlist 文件结构

## 兼容性与风险
- Leader 继续常驻订阅，且订阅集合与执行意图一致
- 避免全量订阅触发 IB 限制
- 需确保 DB 查询仅获取 `running/queued` 的 run
