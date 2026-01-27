# IB 自动化交易闭环 TODO（首期）

本文件定义将系统扩展为**全自动模拟盘/实盘交易**的详细设计与落地任务。首期目标：**IB PRO 账户 + IB 数据源 + 周频调仓闭环**，参考 QuantConnect/Lean 架构。

## 目标与范围
- 目标：从数据→信号→风控→执行→监控形成可追溯闭环，可在 Paper/Live 切换。
- 交易账户：IB PRO（优先 Paper，再 Live）。
- 数据源（逻辑一致）：**研究/回测/信号**使用 Alpha（PIT），**执行/成交/账户/行情**由 Lean IB Brokerage 输出桥接文件提供（系统不直连 IB）；允许成交价偏差但需可解释。
- 周期：周一开盘调仓（与现有 PreTrade checklist 对齐）。

## 菜单与入口（对齐最新主菜单布局）
> 最新主菜单：项目 → 数据 → 回测&报告 → 主题库 → 系统审计  
> 实盘交易需新增一级入口并与上述布局融合。

- 主菜单新增“实盘交易”（建议路径：`/live-trade` 或 `/trade`）。
- 推荐顺序：项目 → 数据 → 回测&报告 → **实盘交易** → 主题库 → 系统审计。
- 未配置 IB 时：入口可见但标记“未配置/只读”，避免误操作。
- 项目页顶部提供“实盘交易”快捷入口（非必须，但建议），便于从项目直接跳转执行面板。

### 菜单验收
- 主菜单中“实盘交易”可见且不与回测/报告混淆。
- 入口状态清晰：未配置/未连接/可交易。

## 非目标
- 首期不覆盖期权交易（Phase 7 以后）。
- 首期不强制覆盖分钟级高频策略。
- 首期不替换现有训练数据源（训练/回测仍以 Alpha 为主，交易执行用 IB）。

## 关键设计原则
- **单实例执行**：同一服务器多副本启动时，严禁并发下单。
- **幂等与可回溯**：订单、信号、回测参数必须可追溯并可复现。
- **逻辑一致**：算法逻辑/风控/订单语义一致，允许成交价差异并建立解释机制。
- **风险优先**：任何风控触发都应阻止下单并告警。

## 术语/模块映射（对齐 QC/Lean）
- DataFeed → IB 行情/历史数据
- Universe → 项目主题/系统主题
- Alpha → ML 评分与决策快照
- Portfolio Construction → 权重生成 + 约束
- Execution → IB 下单与订单状态机
- Risk → 风控与熔断
- Brokerage → IB Gateway/TWS

---

## Phase 0：基础设施与连通（必做）
> 优先级：Phase 0–2 先行，详见 `docs/plans/2026-01-25-ib-autotrade-phase0-2-plan.md`。
### 0.1 Lean IB 连接管理（通过 Bridge 监控）
- [ ] IB Gateway/TWS 常驻服务（systemd 用户服务），支持自动重连。
- [ ] Lean 进程常驻/调度输出 `lean_bridge_status.json` 心跳。
- [ ] 连接健康检测与状态展示（UI/接口）改为读取 bridge 心跳。
- [ ] Paper/Live 开关：UI 可配置并写入 Lean 配置，默认 Paper。
- [x] Live-interactive（Paper）启动验证通过：`/app/stocklean/Lean_git/Launcher/config-lean-bridge-live-paper.json`（`ib-trading-mode=paper`、`ib-validate-subscription=false`、`ib-automater-enabled=false`），bridge 目录输出正常。
- 验收：bridge 心跳 60 秒内刷新，状态可查询。

### 0.2 交易配置管理（配置与安全）
- [ ] 后端配置项：IB_HOST、IB_PORT、IB_CLIENT_ID、IB_ACCOUNT、IB_MODE（IB_CLIENT_ID 仅保留兼容，不参与执行）。
- [ ] UI 配置时**不明文显示**敏感字段（只展示掩码）。
- [ ] 配置保存后写入 Lean 启动配置/参数（单一来源）。
- [x] client id 规则：project_id 优先（paper=base+pid，live=base+offset+pid），写入 `ib-client-id`。
- 验收：配置保存后 Lean 可正常建立连接并输出 bridge 心跳。

### 0.3 单实例交易锁
- [ ] 复用现有 TradeTODO 的锁/心跳逻辑，加入 IB 交易流程前置校验。
- [ ] 多副本同时启动时只允许一个实例“执行交易”。
- 验收：并发启动只允许一个实例进入执行态。

---

## Phase 1：Lean Bridge 数据接入（必做）
### 1.1 Bridge 输出规范
- [x] Lean ResultHandler 输出：`account_summary.json`、`positions.json`、`quotes.json`、`execution_events.jsonl`、`lean_bridge_status.json`。
- [x] 输出目录统一为 `/data/share/stock/data/lean_bridge`（允许配置覆盖）。
- [x] 原子写入/轮转/心跳更新，避免半写入；行情/持仓支持节流更新。
- 验收：后端可读取并识别 `stale`。

### 1.2 行情/账户读取与缓存
- [x] 后端读取 bridge 文件并提供统一 API（`/api/brokerage/*`）。
- [ ] 前端展示更新时间、数据来源、是否降级（stale/degraded）。
- 验收：UI/日志可查看 bridge 更新状态。

### 1.3 数据源策略（逻辑一致）
- [x] 执行/账户/行情/成交来自 Lean bridge。
- [ ] 研究/回测/信号生成使用 Alpha（PIT）。
- [ ] 对账报告：回测价 vs 实盘成交价偏差解释。
- 验收：执行不依赖 Alpha 行情，但偏差可解释。

### 1.4 PreTrade 数据门禁 + Lean Bridge 交易门禁（新增）
- [ ] PreTrade 增加 `bridge_gate` 步骤：读取 `lean_bridge_status.json`/`account_summary.json`/`positions.json`/`quotes.json`，四项任一 stale/缺失/超时即阻断 `trade_execute`。
- [ ] 门禁阈值可配置（默认）：心跳 60s、账户 300s、持仓 300s、行情 60s；写入 `PreTradeStep.artifacts.bridge_gate`（实际时间戳 + 阈值 + 缺失列表）。
- [ ] 数据门禁补强：`trading_day_check` 强制 `coverage_end >= 上一交易日`；PIT 周度/基本面缺失清单写入 artifacts（含文件路径）。
- [ ] Data 页 PreTrade 摘要区拆分“数据门禁/交易门禁”状态与原因；交易门禁显示 Lean Bridge 心跳/账户/持仓/行情更新时间。
- [ ] PreTrade 模板编辑器/步骤列表纳入 `bridge_gate`（默认开启），并与 `market_snapshot`/`trade_execute` 顺序对齐。
- [ ] 数据同步孤儿任务回收：在 bulk_sync `syncing` 阶段评估 `running` 任务与队列状态（A+B 组合信号），满足证据则标记失败并写审计。
- [ ] 孤儿回收配置：`data_sync_orphan_guard.json`（enabled/dry_run/evidence_required）。
- 验收：任一门禁失败均阻断交易并给出可追溯原因；门禁通过后才允许进入下单。

---

## Phase 2：订单与执行（必做）
### 2.1 订单状态机
- [ ] NEW → SUBMITTED → PARTIAL → FILLED/CANCELED/REJECTED（来源为 Lean OrderEvent）。
- [ ] clientOrderId 幂等（重试不重复下单）。
- [ ] 成交回报回写 DB（从 bridge 事件流解析）。
- 验收：重复触发不会产生重复订单。

### 2.2 订单拆分与下单规则
- [ ] 权重 → 目标市值 → 股数计算（整数、最小交易单位）。
- [ ] 价格来源：Lean bridge 行情（或 Lean 内部估算）。
- [ ] 订单类型：首期支持 MKT 与 LMT（默认 MKT）。
- 验收：输入权重能生成合法订单。

### 2.3 Lean IB 执行接入（新增）
- [ ] Lean 执行器读取订单意图（CSV/JSON）并下单（IB Brokerage）。
- [ ] OrderEvent → trade_orders / trade_fills 回写。
- [ ] 订单语义映射（MKT/LMT/TIF/最小手数）。
- 验收：同一 TradeRun 可由 Lean 执行并完成回写。

### 2.4 清理旧 IB 直连代码（必做）
- [x] 删除/迁移 `backend/app/services/ib_*`（market/stream/history/execution/order_executor/health/status_overview）。
- [x] 路由迁移至 `/api/brokerage/*`，移除 `/api/ib/*` 旧路径。
- [x] 删除 `scripts/run_ib_stream.py` 与相关测试。
- [x] 前端 LiveTrade 改为读取 bridge 数据源。
- [x] 移除 IB API 探测（仅保留 Lean Bridge/TCP 状态）。
- 验收：无 IB 直连依赖，IB API 连接仅由 Lean 负责。

---

## Phase 3：风控与回退（必做）
### 3.1 预交易风控
- [ ] 可用资金/保证金/最大仓位/单票上限/行业上限。
- [ ] 未通过时阻止下单并报警。
- 验收：风控触发后无下单行为。

### 3.2 盘中风险管理
- [ ] 单日亏损阈值、最大回撤阈值。
- [ ] 触发后自动停机、回滚或进入防御资产。
- 验收：触发后系统进入保护状态。

### 3.3 回退机制
- [ ] 下单失败/行情异常时回退至上次成功模型/权重。
- [ ] UI 展示“回退目标版本”。
- 验收：回退有审计记录。

---

## Phase 4：模型决策联动（必做）
### 4.1 当日决策快照冻结
- [ ] 生成当日决策快照：模型版本 + 评分 + 权重 + 参数。
- [ ] 交易执行只读此快照。
- 验收：回测/实盘信号一致可追溯。

### 4.2 交易与回测参数一致性
- [ ] 交易执行记录回测参数/策略参数版本。
- 验收：回测可复现对应交易日行为。

### 4.3 订单意图标准化（新增）
- [ ] 决策快照 → 订单意图输出（字段：symbol/weight/side/target_value/snapshot_date/rebalance_date）。
- [ ] Lean 执行器使用该意图生成订单。
- 验收：信号生成与执行接口一致。

---

## Phase 5：监控与告警（必做）
- [ ] 账户/持仓/订单/PNL 实时监控面板（来自 bridge）。
  - [ ] 实盘交易页展示账户摘要与持仓明细（bridge 来源）。
  - [ ] 订单/PNL 统一监控面板补全与汇总指标。
- [ ] 回测 vs 实盘偏差展示（价格/成交/滑点解释）。
- [ ] Telegram 告警：断线、下单失败、风控触发。
- [ ] 告警去重与抑制（避免刷屏）。
- 验收：关键事件可被及时通知。

---

## Phase 6：自动化调度（必做）
- [ ] 周度调仓调度器：PreTrade checklist → 决策冻结 → 下单 → 盘后审计。
- [ ] 任务幂等，重复触发不会重复下单。
- [ ] 失败重试与超时策略与 UI 配置。
- 验收：可一键执行完整流程。

---

## Phase 7：期权扩展（后续）
- [ ] 期权合约链、期权行情、Greeks/IV。
- [ ] 期权风控（保证金、行权/指派处理）。
- [ ] 期权对冲策略配置与回测支持。

---

## 数据与存储设计（建议）
- `data/lean_bridge/`  
  - `account_summary.json`  
  - `positions.json`  
  - `quotes.json`  
  - `execution_events.jsonl`  
  - `lean_bridge_status.json`
- DB 表建议（如需新增）：
  - `ib_connection_state`
  - `ib_contract_cache`
  - `trade_orders`
  - `trade_fills`
  - `trade_runs`（每日执行批次）

---

## UI/UX 设计要点
- 交易状态清晰：连接状态（bridge 心跳）、数据源（Lean bridge）、账户模式（Paper/Live）。
- 执行按钮必须二次确认（Live）。
- 订单与持仓展示不与回测混淆，突出“实盘信号版本”。

### UI/UX 落地状态
- [x] 订单明细与成交明细视图（Orders/Fills）。
- [x] 目标权重 vs 成交偏离对比表。
- [x] 实盘交易页新增“生成交易批次”，创建 queued TradeRun 并回填执行表单。

---

## 关键验收标准
1) Paper 模式：周度调仓可自动执行，且订单与成交完整可追溯。
2) 风控触发：能阻止下单并告警。
3) 数据一致：交易行情与执行来源一致（IB）。
4) 单实例锁：多副本启动不重复下单。
