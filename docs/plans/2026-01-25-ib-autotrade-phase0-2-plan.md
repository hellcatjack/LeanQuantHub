# IB 自动化交易后续开发任务整理（Phase 0-2）

日期：2026-01-25

## 目标
聚焦 Phase 0–2（连通/配置/执行闭环），明确依赖顺序、验收标准与交付物，作为接下来实施的工作清单。

---

## 任务总览（按依赖顺序）

### P0：连通与配置（必须优先）
1. **IB Gateway/TWS 常驻服务（systemd 用户服务）**
   - 目标：保证 TWS/IB Gateway 长驻与自动重连。
   - 交付物：systemd user service 配置 + 重启脚本/说明。
   - 验收：断线后 60s 内恢复；bridge 心跳持续刷新。

2. **Lean 常驻/调度输出桥接心跳**
   - 目标：稳定输出 `lean_bridge_status.json`。
   - 交付物：Lean 启动/调度脚本与日志。
   - 验收：心跳每 5–10s 更新，`stale=false`。

3. **交易配置管理落地（后端 + UI）**
   - 目标：配置项单一来源写入 Lean 启动参数。
   - 内容：IB_HOST/IB_PORT/IB_ACCOUNT/IB_MODE；IB_CLIENT_ID 仅兼容不参与执行。
   - 验收：UI 保存后 Lean 能使用新配置连接。

4. **Paper/Live 开关与 Lean 配置联动**
   - 目标：切换后配置生效并显式标识模式。
   - 验收：切换后 Lean 使用对应模式，UI 展示准确。

5. **桥接状态展示完善（UI）**
   - 目标：连接状态、stale/degraded、数据来源与更新时间清晰展示。
   - 验收：用户可一眼判断是否可交易。

---

### P1：桥接数据接入与对齐
6. **账户/持仓/行情 stale/degraded 展示**
   - 目标：桥接数据质量可见。
   - 验收：数据过期/降级明确提示。

7. **数据源策略标识**
   - 目标：明确“研究/回测=Alpha，执行/账户/行情=Lean bridge”。
   - 验收：页面文案与说明一致。

---

### P2：订单与执行闭环
8. **订单状态机**
   - 目标：NEW→SUBMITTED→PARTIAL→FILLED/CANCELED/REJECTED。
   - 数据源：`execution_events.jsonl`。
   - 验收：状态流完整可追溯。

9. **订单幂等 / clientOrderId**
   - 目标：重试不重复下单。
   - 验收：相同批次重复触发无重复订单。

10. **订单意图 → Lean 执行接入**
    - 目标：订单意图（CSV/JSON）驱动 Lean 下单。
    - 验收：TradeRun 可触发并落地订单。

11. **OrderEvent 回写 trade_orders / trade_fills**
    - 目标：执行记录可追溯。
    - 验收：交易批次可完整查询订单/成交。

12. **订单拆分与下单规则**
    - 目标：权重→目标市值→股数；支持 MKT/LMT/TIF。
    - 验收：输入权重生成合法订单。

---

## 依赖关系简图
P0（1→2→3→4→5）  
P1（6→7）  
P2（8→9→10→11→12）

---

## 风险与注意事项
- 若 TWS/IB Gateway 不稳定，后续执行闭环无法保证可用性。
- Bridge 心跳必须稳定，否则 UI 会反复显示降级。
- 订单执行依赖稳定的 `execution_events.jsonl` 输出与解析。

---

## 验收清单（摘要）
- Bridge 心跳 60 秒内刷新可查询；
- 配置保存后 Lean 可连接；
- 执行状态机完整；
- 订单/成交回写可追溯；
- UI 可见 stale/degraded 与数据来源。
