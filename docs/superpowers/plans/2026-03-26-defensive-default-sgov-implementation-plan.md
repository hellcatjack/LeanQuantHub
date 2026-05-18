# SGOV 默认防御配置迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将系统默认防御标的与防御篮子统一为 `SGOV`，并把当前保存的项目配置与算法参数强制迁移到 `SGOV`，同时保持历史运行产物不变。

**Architecture:** 通过“后端规范化 + 默认值更新 + 数据库 patch”三层收口。前端只负责一致预填，后端负责最终规范化，数据库 patch 负责把已有配置源落盘统一。

**Tech Stack:** FastAPI, React + Vite, Lean Python algorithms, MySQL patch scripts, Pytest, npm build

---

### Task 1: 后端默认值与规范化

**Files:**
- Modify: `backend/app/routes/projects.py`
- Modify: `backend/app/routes/algorithms.py`
- Test: `backend/tests/test_default_defensive_symbols.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_default_defensive_symbols.py` 中增加或修改断言：
- 默认项目配置的 `risk_off_symbols == "SGOV"`
- 默认算法配置的 `risk_off_symbols == "SGOV"`
- 旧值规范化后输出 `SGOV`

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/test_default_defensive_symbols.py -v`
Expected: 至少一条断言因旧默认值仍是 `VGSH...` 或 `SHY...` 失败

- [ ] **Step 3: 实现最小后端修改**

修改 `backend/app/routes/projects.py` 与 `backend/app/routes/algorithms.py`：
- 默认项目配置改为 `SGOV`
- 默认算法配置改为 `SGOV`
- 新增配置规范化 helper，强制将相关字段收敛到 `SGOV`

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/test_default_defensive_symbols.py -v`
Expected: PASS

### Task 2: 算法兜底值统一

**Files:**
- Modify: `configs/default_algorithm.json`
- Modify: `algorithms/ml_overlay_scores.py`
- Modify: `algorithms/composite_trend_lowvol.py`
- Modify: `algorithms/trend_momentum_defensive.py`
- Modify: `algorithms/low_vol_defensive.py`
- Modify: `algorithms/lean_trend_rotation.py`
- Test: `backend/tests/test_project18_train120_opt_payload.py`
- Test: `backend/tests/test_project18_train120_opt_v2_payload.py`

- [ ] **Step 1: 写失败测试**

将相关测试期望改为 `SGOV`。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/test_project18_train120_opt_payload.py backend/tests/test_project18_train120_opt_v2_payload.py -v`
Expected: FAIL，仍返回旧 risk-off 配置

- [ ] **Step 3: 实现最小修改**

将默认算法 JSON 与 Lean 算法兜底值统一改为 `SGOV` / `["SGOV"]`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/test_project18_train120_opt_payload.py backend/tests/test_project18_train120_opt_v2_payload.py -v`
Expected: PASS

### Task 3: 数据库迁移脚本

**Files:**
- Create: `deploy/mysql/patches/20260326_force_defensive_defaults_to_sgov.sql`
- Test: patch 文本自检（通过 `rg` / `sed`）

- [ ] **Step 1: 先写 patch 文件**

Patch 需要：
- 变更说明
- 影响范围
- 回滚指引
- 更新 `project_versions.content`
- 更新 `project_versions.content_hash`
- 更新 `algorithm_versions.params`
- 记录 `schema_migrations`

- [ ] **Step 2: 自检 patch 内容**

Run: `sed -n '1,240p' deploy/mysql/patches/20260326_force_defensive_defaults_to_sgov.sql`
Expected: 能看到幂等保护和迁移逻辑

- [ ] **Step 3: 必要时微调 patch**

确保 patch 只打配置源，不碰历史运行表。

### Task 4: 前端默认值与文案预填

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/pages/AlgorithmsPage.tsx`

- [ ] **Step 1: 先改前端默认值与 placeholder**

将页面默认值、placeholder 统一改为 `SGOV`。

- [ ] **Step 2: 构建前端**

Run: `cd frontend && npm run build`
Expected: build 成功

- [ ] **Step 3: 重启前端服务**

Run: `systemctl --user restart stocklean-frontend`
Expected: 服务重启成功

### Task 5: 综合回归

**Files:**
- Verify only

- [ ] **Step 1: 跑后端回归**

Run: `pytest backend/tests/test_default_defensive_symbols.py backend/tests/test_project18_train120_opt_payload.py backend/tests/test_project18_train120_opt_v2_payload.py backend/tests/test_project_symbols_risk_off_whitelist.py backend/tests/test_trade_riskoff_validation.py -v`
Expected: PASS

- [ ] **Step 2: 检查前端与 patch 文件**

Run: `rg -n "VGSH,IEF,GLD,TLT|VGSH, IEF|\[\"VGSH\", \"IEF\"\]|SHY,IEF|\[\"SHY\", \"IEF\"\]" frontend backend algorithms configs deploy/mysql/patches/20260326_force_defensive_defaults_to_sgov.sql -S`
Expected: 仅剩与历史测试样本或明确非默认语义相关的引用；新的默认值路径不再出现旧组合

- [ ] **Step 3: 记录未覆盖项**

如果发现旧值仍存在于历史事实样本中，只记录，不强改。
