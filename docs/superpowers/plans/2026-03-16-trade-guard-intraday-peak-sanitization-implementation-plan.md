# Trade Guard Intraday Peak Sanitization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复异常盘中峰值污染导致的误判 `guard_halted`，避免同日交易批次持续被误 block。

**Architecture:** 在 `trade_guard.py` 内部增加盘中峰值清洗与自动回写，保持执行器入口不变。测试直接扩展 `test_trade_guard_service.py`，覆盖误判、回写和自动解锁。

**Tech Stack:** Python, SQLAlchemy, pytest

---

### Task 1: 失败测试

**Files:**
- Modify: `backend/tests/test_trade_guard_service.py`

- [ ] 写失败测试：异常盘中峰值应被过滤，不应误触发 `max_intraday_drawdown`
- [ ] 运行单测，确认失败原因正确
- [ ] 写失败测试：清洗后应回写修正后的 `equity_peak`
- [ ] 运行单测，确认失败原因正确
- [ ] 写失败测试：仅由异常盘中峰值造成的 halt 应自动恢复 `active`
- [ ] 运行单测，确认失败原因正确

### Task 2: 最小实现

**Files:**
- Modify: `backend/app/services/trade_guard.py`

- [ ] 增加盘中峰值清洗 helper
- [ ] 用清洗后的盘中峰值替换 `intraday_drawdown` 计算
- [ ] 检测到异常峰值时回写 `state.equity_peak`
- [ ] 在 metrics 中记录 raw/sanitized/outlier 标志
- [ ] 对“仅由异常峰值导致的 halt”执行自动解锁

### Task 3: 回归验证

**Files:**
- Modify: `backend/tests/test_trade_guard_service.py`

- [ ] 运行新增单测，确认通过
- [ ] 运行相关 guard / executor 测试，确认未破坏既有行为
- [ ] 查询数据库验证当前 `trade_guard_state` 仍可被正确读取

### Task 4: 运行态核对

**Files:**
- None

- [ ] 对 `project_id=18` 的 `trade_guard_state` 做只读检查
- [ ] 明确今天 `1155/1156` 的阻断根因是否已被代码路径覆盖
- [ ] 输出变更摘要与后续运行建议
