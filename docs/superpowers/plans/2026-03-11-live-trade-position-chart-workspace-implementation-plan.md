# LiveTrade Position Chart Workspace Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `LiveTrade` 的当前持仓卡片中实现“左侧持仓列表 + 右侧专业图表工作区”，以 `IB 历史K线优先，本地日线回退` 的方式提供 `1m / 5m / 15m / 1h / 1D / 1W / 1M` 历史图表，并支持专业级交互。

**Architecture:** 后端新增统一图表读取服务，对外暴露同步 chart API；该服务优先读取 IB 历史 bars，在 `1D/1W/1M` 周期上失败时回退本地 `curated_adjusted` 聚合日线。前端把持仓卡片拆成双栏工作区，并以独立 `PositionChartWorkspace` 组件承接图表渲染、状态展示与交互逻辑，同时保留现有持仓操作与 Gateway 阻断机制。

**Tech Stack:** FastAPI、SQLAlchemy、React 18、Vite、TypeScript、lightweight-charts、Pytest、Vitest、Playwright。

---

## 文件结构映射

### 后端
- Modify: `backend/app/routes/brokerage.py`
  - 新增 `GET /api/brokerage/history/chart`
- Modify: `backend/app/schemas.py`
  - 新增 chart request/response schema
- Modify: `backend/app/services/ib_market.py`
  - 把 `fetch_historical_bars()` 从 stub 改成真实实现或委托到新服务
- Create: `backend/app/services/price_chart_history.py`
  - interval 映射、IB 历史读取、本地回退、统一响应装配
- Create: `backend/tests/test_price_chart_history.py`
- Create: `backend/tests/test_price_chart_history_routes.py`

### 前端
- Modify: `frontend/src/pages/LiveTradePage.tsx`
  - 持仓卡片改为双栏工作区并接入新组件
- Modify: `frontend/src/i18n.tsx`
  - 新增图表文案与错误提示
- Modify: `frontend/src/styles.css`
  - 新增工作区布局和图表状态样式
- Create: `frontend/src/components/trade/positionChartTypes.ts`
- Create: `frontend/src/components/trade/positionChartUtils.ts`
- Create: `frontend/src/components/trade/PositionChartWorkspace.tsx`
- Create: `frontend/src/components/trade/PositionChartWorkspace.test.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`
- Create: `frontend/tests/live-trade-position-chart.spec.ts`

---

## Chunk 1: 后端图表数据接口

### Task 1: 定义统一图表 schema

**Files:**
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_price_chart_history_routes.py`

- [ ] **Step 1: 写失败测试，要求路由响应具备统一 chart 字段**

```python
def test_history_chart_response_shape(client, monkeypatch):
    monkeypatch.setattr(...)
    res = client.get("/api/brokerage/history/chart", params={"symbol": "AAPL", "interval": "1D"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["symbol"] == "AAPL"
    assert payload["interval"] == "1D"
    assert isinstance(payload["bars"], list)
    assert isinstance(payload["markers"], list)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_price_chart_history_routes.py -v`
Expected: FAIL，提示 schema 或路由不存在。

- [ ] **Step 3: 最小实现 schema**

新增：
- `PriceChartBarOut`
- `PriceChartMarkerOut`
- `PriceChartMetaOut`
- `PriceChartOut`

- [ ] **Step 4: 再跑测试确认 schema 层通过**

Run: `pytest backend/tests/test_price_chart_history_routes.py -v`
Expected: 仍失败，但错误前移到服务/路由未实现。

- [ ] **Step 5: 提交**

```bash
git add backend/app/schemas.py backend/tests/test_price_chart_history_routes.py
git commit -m "test: add chart response schema expectations"
```

### Task 2: 实现 interval 映射与本地回退服务

**Files:**
- Create: `backend/app/services/price_chart_history.py`
- Modify: `backend/app/services/ib_market.py`
- Test: `backend/tests/test_price_chart_history.py`

- [ ] **Step 1: 写失败测试覆盖 interval 映射**

```python
def test_interval_1m_maps_to_intraday_ib_request():
    request = build_chart_request(symbol="AAPL", interval="1m")
    assert request.ib_bar_size == "1 min"
    assert request.ib_duration == "1 D"
    assert request.allow_local_fallback is False
```

- [ ] **Step 2: 写失败测试覆盖本地日线回退**

```python
def test_daily_interval_falls_back_to_local_adjusted_data(tmp_path):
    result = load_chart_history(...)
    assert result["source"] == "local"
    assert result["fallback_used"] is True
    assert len(result["bars"]) > 0
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest backend/tests/test_price_chart_history.py -v`
Expected: FAIL，提示映射函数或回退实现不存在。

- [ ] **Step 4: 最小实现 interval 映射与本地聚合**

实现：
- `build_chart_request(interval)`
- `load_local_adjusted_bars(symbol, interval)`
- `aggregate_daily_bars(..., granularity="week"|"month")`
- `normalize_chart_response(...)`

注意：
- `1m/5m/15m/1h` 禁止本地回退
- `1D/1W/1M` 允许本地回退

- [ ] **Step 5: 再跑测试确认通过**

Run: `pytest backend/tests/test_price_chart_history.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/price_chart_history.py backend/app/services/ib_market.py backend/tests/test_price_chart_history.py
git commit -m "feat: add chart history mapping and local fallback"
```

### Task 3: 把 IB 历史读取接入统一图表服务

**Files:**
- Modify: `backend/app/services/ib_market.py`
- Modify: `backend/app/services/ib_read_session.py` 或复用现有会话能力
- Test: `backend/tests/test_price_chart_history.py`

- [ ] **Step 1: 写失败测试覆盖 IB 成功路径与盘中不可回退路径**

```python
def test_intraday_interval_returns_unavailable_when_ib_history_fails(monkeypatch):
    monkeypatch.setattr(...)
    result = load_chart_history(symbol="AAPL", interval="1m", mode="paper")
    assert result["source"] == "unavailable"
    assert result["error"] == "ib_history_unavailable"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_price_chart_history.py -v`
Expected: FAIL。

- [ ] **Step 3: 最小实现 IB 历史读取**

实现目标：
- `fetch_historical_bars()` 不再返回 `unsupported`
- 支持从 IB 读取 bars，并转换成统一 bars 结构
- 失败时：
  - 盘中周期返回 unavailable
  - 日/周/月继续进入本地回退逻辑

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest backend/tests/test_price_chart_history.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/ib_market.py backend/app/services/ib_read_session.py backend/tests/test_price_chart_history.py
git commit -m "feat: wire IB historical bars into chart service"
```

### Task 4: 暴露 chart API 路由

**Files:**
- Modify: `backend/app/routes/brokerage.py`
- Test: `backend/tests/test_price_chart_history_routes.py`

- [ ] **Step 1: 写失败测试覆盖路由行为**

```python
def test_daily_chart_route_uses_local_fallback_when_ib_fails(client, monkeypatch):
    monkeypatch.setattr(...)
    res = client.get("/api/brokerage/history/chart", params={"symbol": "AAPL", "interval": "1D"})
    assert res.status_code == 200
    assert res.json()["fallback_used"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_price_chart_history_routes.py -v`
Expected: FAIL。

- [ ] **Step 3: 最小实现路由**

- `GET /api/brokerage/history/chart`
- 参数：`symbol`、`interval`、`mode`、`use_rth`
- 返回统一 `PriceChartOut`

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest backend/tests/test_price_chart_history_routes.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/routes/brokerage.py backend/tests/test_price_chart_history_routes.py
git commit -m "feat: add brokerage chart history route"
```

---

## Chunk 2: 前端专业图表工作区

### Task 5: 抽离图表类型与工具函数

**Files:**
- Create: `frontend/src/components/trade/positionChartTypes.ts`
- Create: `frontend/src/components/trade/positionChartUtils.ts`
- Test: `frontend/src/components/trade/PositionChartWorkspace.test.tsx`

- [ ] **Step 1: 写失败测试覆盖 interval、fallback 文案、MA 计算**
- [ ] **Step 2: 运行 `cd frontend && npm run test -- src/components/trade/PositionChartWorkspace.test.tsx` 确认失败**
- [ ] **Step 3: 实现最小工具函数**
- [ ] **Step 4: 再跑单测确认通过**
- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/trade/positionChartTypes.ts frontend/src/components/trade/positionChartUtils.ts frontend/src/components/trade/PositionChartWorkspace.test.tsx
git commit -m "feat: add position chart utilities"
```

### Task 6: 实现 `PositionChartWorkspace` 专业图表组件

**Files:**
- Create: `frontend/src/components/trade/PositionChartWorkspace.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/components/trade/PositionChartWorkspace.test.tsx`

- [ ] **Step 1: 写失败测试覆盖组件核心状态**

覆盖：
- loading mask
- fallback banner
- intraday unavailable state
- crosshair detail strip 的基础文本
- interval 切换按钮

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- src/components/trade/PositionChartWorkspace.test.tsx`
Expected: FAIL。

- [ ] **Step 3: 最小实现组件骨架**

实现内容：
- chart 容器初始化
- candlestick + volume series
- MA20 / MA60
- interval toolbar
- fallback/unavailable/loading 状态条
- BUY/SELL markers 基础渲染

- [ ] **Step 4: 再跑测试确认通过**

Run: `cd frontend && npm run test -- src/components/trade/PositionChartWorkspace.test.tsx`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/trade/PositionChartWorkspace.tsx frontend/src/i18n.tsx frontend/src/styles.css frontend/src/components/trade/PositionChartWorkspace.test.tsx
git commit -m "feat: add professional position chart workspace"
```

### Task 7: 把持仓卡片升级为双栏工作区

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`
- Test: `frontend/src/pages/LiveTradePage.test.ts`

- [ ] **Step 1: 写失败测试覆盖默认选中 symbol 与工作区联动**
- [ ] **Step 2: 运行 `cd frontend && npm run test -- src/pages/LiveTradePage.test.ts` 确认失败**
- [ ] **Step 3: 最小实现 LiveTrade 集成**

实现内容：
- 维护 `selectedPositionChartSymbol`
- 默认选中第一条可展示持仓
- 左栏 table 与右栏 workspace 联动
- 保持现有平仓/下单/Gateway 阻断逻辑不回退
- 移动端改为上下结构

- [ ] **Step 4: 再跑单测确认通过**

Run: `cd frontend && npm run test -- src/pages/LiveTradePage.test.ts`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/pages/LiveTradePage.test.ts
git commit -m "feat: integrate chart workspace into live trade positions"
```

---

## Chunk 3: 回归、构建与文档

### Task 8: Playwright 桌面/回退回归

**Files:**
- Create: `frontend/tests/live-trade-position-chart.spec.ts`

- [ ] **Step 1: 写失败的 E2E 用例**

覆盖：
- 双栏布局渲染
- 点击不同 symbol 联动图表
- 切换 `1D` 在 IB 失败时显示 fallback
- 切换 `1m` 在 IB 失败时显示 unavailable

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test:e2e -- tests/live-trade-position-chart.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 修正实现直到 E2E 通过**
- [ ] **Step 4: 再跑 E2E 确认通过**

Run: `cd frontend && npm run test:e2e -- tests/live-trade-position-chart.spec.ts`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/tests/live-trade-position-chart.spec.ts
git commit -m "test: cover live trade position chart workspace"
```

### Task 9: 全量验证与文档说明

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`

- [ ] **Step 1: 补充使用说明**

说明：
- 图表周期
- IB 优先 / 本地日线回退规则
- 盘中周期在 IB 失败时的行为

- [ ] **Step 2: 跑后端测试**

Run:
```bash
pytest backend/tests/test_price_chart_history.py backend/tests/test_price_chart_history_routes.py -v
```
Expected: PASS。

- [ ] **Step 3: 跑前端测试与构建**

Run:
```bash
cd frontend && npm run test -- src/components/trade/PositionChartWorkspace.test.tsx src/pages/LiveTradePage.test.ts
cd frontend && npm run test:e2e -- tests/live-trade-position-chart.spec.ts
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```
Expected:
- 单测 PASS
- E2E PASS
- build 成功
- `stocklean-frontend` 重启成功

- [ ] **Step 4: 提交**

```bash
git add README.md README.en.md
git commit -m "docs: document live trade chart workspace"
```

---

## 收尾检查
- [ ] 确认 `GET /api/brokerage/history/chart` 在 `1m/5m/15m/1h/1D/1W/1M` 下行为符合设计
- [ ] 确认 `gateway_degraded` 时图表仍能显示 `1D/1W/1M` 本地回退
- [ ] 确认移动端不出现横向溢出
- [ ] 确认未引入新的前端依赖
- [ ] 确认 `frontend/dist` 未被纳入提交
