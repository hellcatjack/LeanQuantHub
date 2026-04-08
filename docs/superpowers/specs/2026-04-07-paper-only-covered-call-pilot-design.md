# Paper-Only Covered Call Pilot 设计

**目标**
在不改变当前股票主交易路径、且不触碰 `live` 的前提下，为 StockLean 增加一条 `paper-only` 的真实期权试点链路，用于验证备兑看涨（covered call）是否能在现有系统中以可控风险运行。

**结论先行**
当前阶段不应该直接把真实期权卖方策略接入主交易链路。推荐的最小可行范围是：
- 仅支持 `paper`
- 仅支持单腿 `covered call`
- 仅支持“账户中已持有整百股标的”的资格筛选
- 先做后端能力和预演，默认不把任何期权动作自动并入现有股票批次执行
- 先交付“发现可做标的 + 选约建议 + dry-run 订单计划 + 风险门禁”，再决定是否推进真实 `paper` 下单

---

## 一、问题背景

当前系统已经完成了两件前置工作：

1. 通过代理 ETF 研究验证了“期权收益增强”方向具备继续研究价值。
2. 已确认现有应用层执行框架仍以股票为核心，不具备期权合约、链路、风控和 UI 基础。

当前限制包括：
- [trade_order_builder.py](/app/stocklean/backend/app/services/trade_order_builder.py) 只有股票式订单字段，没有 `expiry/strike/right/multiplier` 等期权字段。
- [ib_read_session.py](/app/stocklean/backend/app/services/ib_read_session.py) 的历史数据请求仍固定 `secType="STK"`。
- 当前交易页和手工下单链路都是股票式表单。
- 当前账户和策略分散持仓较多，很多单票仓位低于 100 股，不满足 covered call 最基本的建仓条件。

因此，当前最稳的下一步不是“直接做期权交易”，而是构建一条受限、可观测、可回退的 `paper-only covered call pilot`。

---

## 二、范围边界

### 2.1 本阶段纳入范围
- `paper` 模式下的期权能力试点
- 单腿 `covered call`
- 只针对账户现有持仓生成候选和 dry-run 计划
- 基于 IB 获取期权链和合约细节
- 资格筛选、流动性门槛、风险门禁
- 预演输出与审计记录

### 2.2 本阶段明确不做
- `live` 真实期权下单
- `cash-secured put`
- 多腿价差、collar、roll 管理
- 期权自动并入现有股票批次执行
- 前端复杂期权链 UI
- Greeks/IV 的长期本地数据库建设

### 2.3 稳健性原则
- 任何期权能力默认关闭，必须显式进入 `paper-only pilot`
- 资格不满足时宁可“不做”，不能为了演示强行生成计划
- 所有期权动作必须可解释、可回放、可审计
- 任何无法确认的合约状态或行情状态，都不进入自动下单阶段

---

## 三、候选方案对比

### 方案 A：继续只做代理 ETF
**优点**
- 风险最低
- 不需要扩展执行系统

**缺点**
- 无法验证真实期权链路是否稳健
- 研究结果与真实 IB 期权执行之间仍有巨大落差

### 方案 B：`paper-only` 备兑看涨试点，推荐
**优点**
- 工程范围受控
- 与现有持仓联动最直接
- 风险边界最清楚
- 能验证真实期权链、合约筛选和订单建模

**缺点**
- 受账户持仓结构限制，可覆盖标的可能较少
- 仍需要补后端期权能力

### 方案 C：通用期权执行框架
**优点**
- 长期最完整

**缺点**
- 需求面太大
- 当前系统没有足够基础支持
- 高风险，不符合“稳健优先”

**推荐结论**
采用方案 B，先建设 `paper-only covered call pilot`。

---

## 四、目标行为

### 4.1 用户视角
给定一个 `paper` 账户和当前持仓，系统应能：
- 找出哪些标的满足备兑看涨资格
- 为每个合格标的筛选候选 call 合约
- 给出最小化的建议结果：
  - 标的
  - 可卖张数
  - 到期日
  - 行权价
  - 参考 bid/ask/mid
  - 预计权利金
  - 主要门禁原因或风险标签
- 生成 dry-run 订单计划和审计产物

### 4.2 系统行为
- 若账户持仓不足 100 股，或存在未完成的股票/期权挂单，则该标的不进入 covered call 候选。
- 若 Gateway/IB 运行态不健康，则整个期权试点不执行，返回明确阻断原因。
- 若期权链不足、行情不完整、价差过宽、到期日异常，则标记为 `ineligible` 而不是强行选约。

---

## 五、架构设计

### 5.1 模块划分

#### A. `ib_options_market.py`
职责：
- 面向 IB 拉取期权链元数据与合约详情
- 输出标准化候选列表

建议能力：
- `fetch_option_chain(symbol, mode)`
- `fetch_option_quotes(contracts, mode)`
- `fetch_contract_details(contract_spec, mode)`

说明：
- 本阶段不做历史期权数据归档
- 只做即时读取与标准化输出

#### B. `options_eligibility.py`
职责：
- 根据当前持仓、open orders、运行健康和策略门槛，判断 covered call 是否允许进行

核心规则：
- 标的持仓必须 `>= 100` 且为 100 的整数倍部分才可覆盖
- 禁止对已有期权仓位或相关未完成订单的标的再次出建议
- `runtime_health != healthy` 时整体阻断
- `paper` 以外模式整体阻断

#### C. `covered_call_planner.py`
职责：
- 在合格标的上执行候选合约打分和最终建议输出

最小选约规则建议：
- 仅看 call
- DTE 目标窗口：`21-45` 天
- 只选 OTM 合约
- 优先更小价差、更合理 mid、较近但不过度逼近的到期日
- 本阶段不强依赖 Greeks；若 IB 返回 `delta/modelGreeks` 则作为加分项，而不是硬依赖项

#### D. `covered_call_pilot.py`
职责：
- 串起资格判断、期权链获取、选约、dry-run 计划、审计落盘
- 形成统一 API 输出

#### E. `trade_option_models.py`
职责：
- 定义期权合约与 dry-run 订单计划的数据结构
- 与股票订单模型分离，避免污染现有主交易路径

### 5.2 为什么不直接复用股票订单模型
当前 [trade_order_builder.py](/app/stocklean/backend/app/services/trade_order_builder.py) 是按股票仓位权重设计的。期权订单至少需要：
- `underlying_symbol`
- `expiry`
- `strike`
- `right`
- `multiplier`
- `contracts`
- `limit_price`

把这些字段直接硬塞进现有股票订单模型，会污染主路径。更稳妥的做法是：
- 本阶段独立建模
- 先做 `pilot preview + dry-run artifacts`
- 真正进入 paper 期权下单时，再决定如何与现有订单表集成

---

## 六、数据流

### 6.1 读取路径
1. 从当前 `paper` 持仓读取股票持仓
2. 读取 open orders，过滤已有未完成动作的标的
3. 读取 Gateway/Bridge 运行健康
4. 对合格标的拉取 IB 期权链与报价
5. 根据规则筛选候选 call
6. 输出建议与 dry-run 计划

### 6.2 输出路径
输出内容包括：
- `eligible_underlyings`
- `rejected_underlyings`
- `candidate_contracts`
- `recommended_contracts`
- `dry_run_orders`
- `audit_summary`

产物建议落盘到：
- `artifacts/options_pilot_<timestamp>/summary.json`
- `artifacts/options_pilot_<timestamp>/candidates.json`
- `artifacts/options_pilot_<timestamp>/dry_run_orders.json`

---

## 七、风险门禁

### 7.1 系统级门禁
满足任一条件则整体阻断：
- `mode != paper`
- Gateway/Bridge 非 `healthy`
- 最近一次 probe 失败
- open orders 同步 stale

### 7.2 标的级门禁
满足任一条件则该标的不参与：
- 持仓少于 `100` 股
- 持仓不是整百可覆盖
- 存在未完成股票订单
- 已有相关期权头寸
- 期权链为空
- 价差过宽
- 到期日不在目标窗口

### 7.3 合约级门禁
满足任一条件则合约不参与：
- 非 `CALL`
- 非 OTM
- bid/ask 缺失
- `ask <= 0` 或 `bid < 0`
- `spread / mid` 超过阈值
- 合约细节不完整

---

## 八、API 设计

建议新增只读试点接口：

### `POST /api/trade/options/covered-call/pilot`
用途：
- 运行一次 `paper-only covered call pilot`

请求：
```json
{
  "mode": "paper",
  "symbols": ["AAPL", "MSFT"],
  "max_candidates_per_symbol": 5,
  "dte_min": 21,
  "dte_max": 45,
  "max_spread_ratio": 0.15,
  "dry_run": true
}
```

响应：
```json
{
  "mode": "paper",
  "status": "ok",
  "eligible": [
    {
      "symbol": "AAPL",
      "shares": 200,
      "coverable_contracts": 2,
      "recommended": {
        "expiry": "2026-05-15",
        "strike": 230.0,
        "right": "C",
        "contracts": 2,
        "bid": 1.2,
        "ask": 1.3,
        "mid": 1.25
      }
    }
  ],
  "rejected": [
    {
      "symbol": "NVDA",
      "reason": "shares_below_100"
    }
  ],
  "artifacts": {
    "summary": ".../summary.json",
    "orders": ".../dry_run_orders.json"
  }
}
```

说明：
- 本阶段只支持 `dry_run=true`
- 若后续进入真实 paper 下单，再新增单独执行接口，不复用这个试点接口

---

## 九、测试策略

### 9.1 单元测试
至少覆盖：
- 持仓不足 100 股被拒绝
- 有 200/300 股时正确计算可覆盖张数
- 非 OTM/价差过宽合约被过滤
- 运行健康异常时整体阻断
- dry-run 计划输出结构稳定

### 9.2 服务测试
- mock IB 期权链与报价
- 验证 planner 能给出唯一推荐合约
- 验证 artifacts 正确落盘

### 9.3 运行验证
- 在真实 `paper` 账户上跑试点接口
- 确认没有真实下单
- 确认输出的候选与账户持仓一致

---

## 十、成功标准

本阶段完成的标准不是“完成真实期权交易”，而是：
- 能稳定识别 covered call 资格
- 能稳定拉取并筛选 IB 期权链
- 能生成可解释的 dry-run 建议
- 能在 Gateway 不健康时安全阻断
- 不污染现有股票主交易路径

如果这些达成，下一阶段才有资格讨论：
- 真实 `paper` 期权下单
- 订单表建模整合
- 滚动/平仓/指派处理

---

## 十一、默认后续方向

默认下一阶段是：
1. 先实现 `paper-only covered call pilot` 的后端只读能力
2. 用真实 `paper` 账户做若干次 dry-run 预演
3. 只有当资格判断、候选稳定性、Gateway 门禁都可信后，才进入真实 `paper` 下单阶段

当前不建议直接推进 `live`。
