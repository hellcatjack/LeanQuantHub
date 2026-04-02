# Trade Strategy Snapshot 回测绑定一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TradeRun 的 `strategy_snapshot` 默认对齐当前 decision snapshot 已绑定的 `backtest_run_id`。

**Architecture:** 新增统一 helper 构造交易侧配置快照，按 snapshot 绑定回测优先、当前项目配置回退；接入 pretrade 和 trade route 两条建批次入口。

**Tech Stack:** FastAPI, SQLAlchemy, pytest

---

### Task 1: 锁定回归测试
- [ ] 为 pretrade 入口写失败测试
- [ ] 为 `/api/trade/runs` 写失败测试

### Task 2: 实现统一 helper 并接入
- [ ] 新增 `backend/app/services/trade_strategy_snapshot.py`
- [ ] 修改 `backend/app/services/pretrade_runner.py`
- [ ] 修改 `backend/app/routes/trade.py`

### Task 3: 验证
- [ ] 运行定向 pytest
- [ ] 运行更大范围 trade/pretrade 相关 pytest
- [ ] 重启后端并抽样验证返回的 run params
