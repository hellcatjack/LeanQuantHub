# LiveTrade 持仓专业图表工作区设计

## 背景
当前 `LiveTrade` 页面已经具备持仓查看、批量平仓、单标的手动下单、Gateway 运行状态展示等能力，但“当前持仓”区域仍以表格为主，缺少专业交易终端常见的历史 K 线工作区。用户在持仓列表中选中某个标的后，无法直接看到该标的的历史走势、成交量、最近买卖点和周期切换视图，只能依赖其他页面或外部软件。

本次目标不是简单增加一张图，而是把持仓区升级为接近 moomoo / 富途类终端的“列表 + 专业图表工作区”。

## 目标
- 在 `LiveTrade` 的当前持仓卡片中新增专业 K 线工作区。
- 图表默认以 `IB 历史 K 线优先，本地 Alpha/curated_adjusted 日线回退` 的方式提供数据。
- 图表支持至少以下交互：缩放、拖拽、十字光标、周期切换、成交量、副图/指标开关、买卖点标记。
- 图表加载失败不得影响持仓表和交易按钮的既有行为。
- 在 `gateway_restarting/gateway_degraded` 时，图表仍应尽量显示本地日线回退，不因为 Gateway 降级而整块空白。

## 非目标
- 本期不实现画线工具、深度图、盘口、期权链、多标的对比叠加。
- 本期不重做整个 `LiveTrade` 页面，只聚焦持仓卡片的升级。
- 本期不依赖后台异步 `history-jobs`，图表使用同步读取接口。

## 方案结论
采用右侧专业图表工作区布局：
- 左侧：现有持仓表，承担选股器角色。
- 右侧：常驻 `PositionChartWorkspace`，展示当前选中 symbol 的专业图表。
- 桌面端默认双栏；移动端降级为上下结构。

选择原因：
- 最接近专业终端工作流。
- 切换 symbol 时视觉稳定，不需要反复展开/折叠行内容。
- 为后续扩展 MA、VWAP、买卖点、更多周期和全屏模式预留空间。

## 架构与模块边界

### 前端
在 [frontend/src/pages/LiveTradePage.tsx](/app/stocklean/frontend/src/pages/LiveTradePage.tsx) 的 `positions` 区块中新增一个工作区组件：
- 左栏保留持仓表与现有操作按钮。
- 右栏新增 `PositionChartWorkspace` 组件。
- 组件职责：
  - 管理当前选中 symbol
  - 管理周期切换 `1m / 5m / 15m / 1h / 1D / 1W / 1M`
  - 发起图表请求并处理竞态
  - 渲染 K 线、成交量、指标、标记和 fallback 状态

建议新增前端文件：
- `frontend/src/components/trade/PositionChartWorkspace.tsx`
- `frontend/src/components/trade/positionChartTypes.ts`
- `frontend/src/components/trade/positionChartUtils.ts`

### 后端
在 `brokerage` 域新增统一图表读取接口，不走 `history-jobs`：
- 新增 `GET /api/brokerage/history/chart`
- 内部按周期和可用性决定：
  1. 优先读取 IB 历史 bars
  2. 若是 `1D/1W/1M` 且 IB 失败，则回退本地 `curated_adjusted`

建议新增/修改文件：
- 修改 `backend/app/routes/brokerage.py`
- 修改 `backend/app/schemas.py`
- 修改 `backend/app/services/ib_market.py`
- 新增 `backend/app/services/price_chart_history.py`

## 数据源策略

### 默认优先级
- `1m / 5m / 15m / 1h`：只允许 IB 历史 bars
- `1D / 1W / 1M`：优先 IB；IB 不可用时回退本地 Alpha/curated_adjusted

### 原因
- 用户明确要求“IB 历史K线优先，本地日线回退”。
- 盘中周期必须尊重真实来源，不能用本地日线数据伪装盘中图。
- 本地数据只作为日/周/月图的稳定回退路径，避免 HMDS 状态抖动导致整块图表不可用。

## 接口契约

### 请求
```http
GET /api/brokerage/history/chart?symbol=AAPL&interval=1m&mode=paper
```

参数：
- `symbol`: 必填，标的代码
- `interval`: 必填，`1m | 5m | 15m | 1h | 1D | 1W | 1M`
- `mode`: 可选，`paper | live`，默认 `paper`
- `range`: 可选，首版由前端内部决定默认值
- `use_rth`: 可选，默认 `true`

### 响应
```json
{
  "symbol": "AAPL",
  "interval": "1D",
  "source": "ib",
  "fallback_used": false,
  "stale": false,
  "bars": [
    {
      "time": 1773187200,
      "open": 188.92,
      "high": 192.64,
      "low": 187.88,
      "close": 191.36,
      "volume": 58200000
    }
  ],
  "markers": [
    {
      "time": 1773187200,
      "position": "belowBar",
      "shape": "arrowUp",
      "color": "#10b981",
      "text": "BUY"
    }
  ],
  "meta": {
    "currency": "USD",
    "price_precision": 2,
    "last_bar_at": "2026-03-10T20:00:00Z"
  },
  "error": null
}
```

设计原则：
- 前端不关心底层来自 IB 还是本地文件。
- 后端统一输出 bars/markers/meta。
- 前端只根据 `source/fallback_used/error` 决定状态条与提示文案。

## 周期与范围映射
建议默认时间范围如下：
- `1m`: `1 D`
- `5m`: `5 D`
- `15m`: `10 D`
- `1h`: `30 D`
- `1D`: `6 M`
- `1W`: `2 Y`
- `1M`: `5 Y`

后端应负责把前端 interval 映射为：
- IB `barSizeSetting`
- IB `durationStr`
- 本地日线聚合粒度

## 本地回退实现
本地回退模块从 `data_root/curated_adjusted` 读取 Alpha 复权日线：
- `1D`：直接读取日线 bars
- `1W`：按周聚合日线
- `1M`：按月聚合日线

要求：
- 聚合后同样返回 OHLCV
- 若缺少成交量，允许 volume 为 `null` 或 `0`，但要保持结构统一
- 若本地数据完全缺失，返回明确的 `error=local_history_missing`

## 专业图表行为

### 首版必须支持
- 鼠标滚轮缩放
- 拖拽平移
- 十字光标
- 双击重置视图
- 周期切换
- 成交量副图
- MA20 / MA60
- BUY/SELL markers
- 底部 OHLC / 变动信息条

### 视觉原则
- 用 `lightweight-charts`，避免引入额外重型依赖
- 风格接近专业终端：克制、清晰、强调价格与量
- 桌面端双栏布局优先，移动端允许上下堆叠
- `fallback` 与 `unavailable` 用状态条表达，不用 toast 打扰

### 状态行为
- `IB 成功`：显示 `source=IB`
- `IB 失败 + 本地回退成功`：显示 `Fallback: Local Daily`
- `盘中周期 + IB 失败`：不伪造数据，显示 “该周期需要 IB 历史数据”
- `symbol 切换中`：保留旧图并叠加 loading mask，避免闪烁清空

## 标记与指标

### 首版标记
- 当前持仓建立方向或最近持仓基准点
- 最近交易订单/成交点（BUY/SELL）

### 首版指标
- `MA20`
- `MA60`

这些指标建议前端基于 bars 本地计算，避免新增后端指标计算耦合。

## 与现有 Gateway 状态机的关系
- 图表请求不参与当前 Gateway 自愈状态判定。
- `gateway_restarting/gateway_degraded` 时：
  - 保持既有交易阻断
  - 图表仍可请求 `1D/1W/1M` 的本地回退数据
- 盘中周期在 Gateway 不可用时直接显示 unavailable

## 测试策略

### 后端
新增：
- `backend/tests/test_price_chart_history.py`
- `backend/tests/test_price_chart_history_routes.py`

覆盖：
- interval 到 IB 参数映射正确
- `1D/1W/1M` 回退命中本地数据
- `1m/5m/15m/1h` IB 失败时返回 unavailable
- 响应结构统一

### 前端
新增：
- `frontend/src/components/trade/PositionChartWorkspace.test.tsx`

覆盖：
- 默认选中首个持仓
- 切换 symbol/周期时请求正确
- fallback 状态和 unavailable 状态正确渲染
- Gateway 降级时图表仍可渲染日线回退

### E2E
新增或扩展：
- `frontend/tests/live-trade-position-chart.spec.ts`

覆盖：
- 持仓双栏工作区渲染
- symbol 切换联动图表
- 周期切换后信息条刷新
- 模拟 IB 失败时 `1D` 回退成功、`1m` unavailable
- 移动端布局不溢出

## 风险与控制
- 风险：IB 历史 bars 读取失败或超时频繁
  - 控制：仅盘中周期强依赖 IB；日/周/月回退本地
- 风险：`LiveTradePage.tsx` 已较大，继续膨胀
  - 控制：把图表工作区拆到独立组件
- 风险：图表请求过于频繁
  - 控制：symbol/period 级请求缓存与竞态保护
- 风险：移动端双栏难用
  - 控制：移动端切换为上下结构

## 验收标准
- 桌面端持仓卡片升级为稳定双栏工作区
- 支持 `1m / 5m / 15m / 1h / 1D / 1W / 1M`
- `1D/1W/1M` 在 IB 不可用时自动回退本地日线
- `1m/5m/15m/1h` 在 IB 不可用时明确显示不可用状态
- 支持缩放、拖拽、十字光标、成交量、MA20/MA60、买卖点标记
- 前端构建通过，相关单测与 Playwright 回归通过
