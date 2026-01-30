# Lean Bridge Leader Watchlist 设计方案

## 背景与目标
- 目标：让 Lean Bridge Leader 常驻并订阅 watchlist，避免心跳/行情缺失；watchlist 来源为“项目当前配置的股票池/主题（统一 universe）”。
- 约束：为避免并发过多请求，watchlist 总量硬上限 200。
- 范围：仅影响 Lean Bridge Leader 的 watchlist 写入与订阅，不改变交易执行或其它数据链路。

## 设计原则
- 稳定、可复现：同样配置应产生稳定排序与一致结果。
- 安全退化：无可用标的时 fallback 到 SPY，避免订阅为空。
- 去重优先：避免同一标的多次订阅。
- 低噪声写入：watchlist 内容无变化则不改写文件。

## 数据来源与范围
- 项目范围：`Project.is_archived = False`。
- 每个项目 symbols：使用现有 `collect_project_symbols()`，解析项目配置中的主题、权重、资产类型等规则。
- 基准标的：每个项目配置里的 `benchmark`（默认 SPY）。基准优先入列。
- 统一输出：写入 `lean_bridge_watchlist` 路径下 `watchlist.json`。

## 优先级与分配策略（上限 200）
1) **基准优先**：先收集所有项目 benchmark（去重）。
2) **轮询填充（Round-robin）**：
   - 按 `Project.id` 升序遍历项目。
   - 每个项目的 symbols 按字母排序。
   - 逐轮从每个项目取 1 个 symbol（去重），直到满 200 或无可取。
3) **再轮询**：继续下一轮，直至到达上限。

该策略确保多项目公平覆盖，避免单一大主题吞噬名额，同时保持输出稳定。

## 边界与异常处理
- 若所有项目无 symbols：watchlist 仅包含 `SPY`。
- 若写入路径不可用：抛出可观测日志，避免写入空列表覆盖旧文件。
- 去重后数量不足：允许小于 200，不补全。

## 测试策略（TDD）
- 新增单测验证：
  - **上限 200** 生效。
  - **基准优先**（benchmark 必入）。
  - **轮询公平**（多项目轮换取样）。
  - **去重**（同符号只出现一次）。
- 边界单测：无项目 symbols 时 fallback SPY。

## 实施位置
- `backend/app/services/project_symbols.py`：新增 watchlist 构建辅助方法（可选）。
- `backend/app/services/lean_bridge_leader.py`：替换 `_write_watchlist()` 逻辑为带上限与轮询策略。
- 测试：新增 `backend/tests/test_lean_bridge_watchlist.py`（或相近命名）。

## 可观测性
- 记录 watchlist 生成数量、上限、实际写入数量、是否发生写入。
- 如发生 fallback，写入明确日志（含原因）。

