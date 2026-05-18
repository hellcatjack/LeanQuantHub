# Paper Covered Call Recent Search/Pagination 实施计划

**Goal:** 为 covered call recent 列表增加服务端搜索与分页，并在 `LiveTrade` 只读面板接入搜索框和翻页控件。

**Architecture:** 后端先扩展 `audit/recent` 的 request/response 与过滤分页服务；前端再接 `query/offset/total/has_more`，保持只读。测试优先，先后端再前端。

**Tech Stack:** FastAPI、Pydantic、React、Vitest、Playwright。

---

### Task 1: 后端 TDD 扩展 recent 接口

**Files:**
- Modify: `backend/app/services/trade_option_models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/covered_call_audit_recent.py`
- Modify: `backend/tests/test_covered_call_audit_recent.py`
- Modify: `backend/tests/test_covered_call_audit_recent_route.py`

- [x] Step 1: 先写失败测试，覆盖 query 过滤、offset 分页、total/has_more
- [x] Step 2: 运行目标 pytest，确认失败
- [x] Step 3: 最小实现 request/response 与 service 逻辑
- [x] Step 4: 重新运行 pytest，确认通过

### Task 2: 前端 TDD 接入搜索/分页

**Files:**
- Modify: `frontend/src/components/trade/CoveredCallAuditPanel.tsx`
- Modify: `frontend/src/components/trade/CoveredCallAuditPanel.test.tsx`
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`

- [x] Step 1: 先写失败测试，覆盖搜索框、分页信息、翻页按钮
- [x] Step 2: 运行前端单测，确认失败
- [x] Step 3: 最小实现前端 state 与请求参数
- [x] Step 4: 重新运行前端单测，确认通过

### Task 3: E2E 回归

**Files:**
- Modify: `frontend/tests/live-trade-covered-call-panel.spec.ts`

- [x] Step 1: 先写 E2E 失败断言，覆盖搜索与翻页
- [x] Step 2: 运行 Playwright，确认失败
- [x] Step 3: 修正实现直到通过
- [x] Step 4: 重新运行 Playwright，确认通过

### Task 4: 最终验证

**Files:**
- Modify: `backend/app/services/covered_call_audit_recent.py`
- Modify: `frontend/src/pages/LiveTradePage.tsx`

- [x] Step 1: 运行后端 pytest
- [x] Step 2: 运行前端 vitest
- [x] Step 3: 运行 Playwright
- [x] Step 4: 运行 `cd frontend && npm run build`
- [x] Step 5: 重启 `stocklean-frontend`
- [x] Step 6: 用运行中的静态服务再跑一次 covered call 面板 E2E
