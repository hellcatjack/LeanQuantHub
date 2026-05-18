# Defensive Policy Baseline Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把防御资产实验结论固化进默认值归一化、研究模板和实验脚本入口，避免默认路径漂移。

**Architecture:** 新增统一防御基线模块作为默认值单一来源；项目和算法路由通过该模块归一化默认配置；研究模板矩阵独立成配置文件；默认实验脚本与之对齐。研究路径保留显式扩展能力，不与默认路径混淆。

**Tech Stack:** FastAPI backend, Python scripts, JSON config files, pytest

---

### Task 1: 添加失败测试，锁定默认基线与研究模板行为

**Files:**
- Modify: `backend/tests/test_default_defensive_symbols.py`
- Create: `backend/tests/test_defensive_policy.py`
- Modify: `backend/tests/test_project18_train120_opt_payload.py`
- Modify: `backend/tests/test_project18_train120_opt_v2_payload.py`

- [ ] **Step 1: 写失败测试，断言统一基线模块与研究模板存在**
- [ ] **Step 2: 运行新增测试，确认因缺少模块/文件而失败**
- [ ] **Step 3: 扩展现有默认值测试，断言默认 benchmark 为 `SPY`，研究模板包含 `GLD/USO/BNO/TLT/QQQ/SOXX`**
- [ ] **Step 4: 重新运行测试，确认失败原因正确**

### Task 2: 实现统一防御基线模块与研究模板矩阵

**Files:**
- Create: `backend/app/services/defensive_policy.py`
- Create: `configs/research_defensive_matrix.json`
- Test: `backend/tests/test_defensive_policy.py`

- [ ] **Step 1: 实现统一常量与读取函数**
- [ ] **Step 2: 落盘研究模板矩阵文件**
- [ ] **Step 3: 运行针对性测试，确认从红变绿**

### Task 3: 把项目与算法默认归一化统一到基线模块

**Files:**
- Modify: `backend/app/routes/projects.py`
- Modify: `backend/app/routes/algorithms.py`
- Test: `backend/tests/test_default_defensive_symbols.py`

- [ ] **Step 1: 接入统一基线模块，替换散落常量**
- [ ] **Step 2: 运行默认值测试，确认归一化行为保持正确**
- [ ] **Step 3: 确认默认路径仍为 `SGOV / SGOV,VGSH / SPY`**

### Task 4: 同步默认实验脚本与研究模板入口

**Files:**
- Modify: `scripts/run_project18_train120_opt.py`
- Modify: `scripts/run_project18_train120_opt_v2.py`
- Modify: `scripts/run_cagr_opt.py`
- Modify: `scripts/run_train_model_opt.py`
- Test: `backend/tests/test_project18_train120_opt_payload.py`
- Test: `backend/tests/test_project18_train120_opt_v2_payload.py`

- [ ] **Step 1: 对齐脚本默认防御参数到统一基线**
- [ ] **Step 2: 让脚本能读到研究模板矩阵或至少对齐其结构**
- [ ] **Step 3: 运行脚本 payload 测试并确认通过**

### Task 5: 回归验证

**Files:**
- Verify: `backend/tests/test_default_defensive_symbols.py`
- Verify: `backend/tests/test_defensive_policy.py`
- Verify: `backend/tests/test_project18_train120_opt_payload.py`
- Verify: `backend/tests/test_project18_train120_opt_v2_payload.py`

- [ ] **Step 1: 运行聚合 pytest 回归**
- [ ] **Step 2: 检查研究模板文件内容与最终决策一致**
- [ ] **Step 3: 总结变更范围与后续可继续固化的入口**
