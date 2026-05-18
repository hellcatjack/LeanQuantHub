# Paper Covered Call Execution Prep 设计

**目标**
在现有 `paper-only covered call pilot` 的基础上，再增加一层更稳的“执行准备”能力：把推荐结果转换成可审计的期权订单计划，并在真实下单之前完成门禁判定、风险标签汇总和 artifact 落盘。

**结论先行**
当前阶段仍然不应该直接进入真实 `paper` 期权下单。推荐先建设一层 `execution prep`：
- 只支持 `paper`
- 只支持 `covered call`
- 只支持 `dry-run`
- 只为单个标的生成执行计划
- 明确区分 `ready / review_required / blocked`
- 输出独立的期权订单模型与审计 artifact

---

## 一、为什么要先做 execution prep

目前 pilot 已经具备：
- 账户资格筛选
- IB 期权候选读取
- 最小选约
- 风险标签与 dry-run artifact

但 pilot 仍然缺一层关键边界：
- 推荐结果还不是“可执行订单”
- 没有独立的期权订单模型
- 没有门禁状态机来区分“可直接进入 paper 下单”和“需要人工复核”
- 没有把下单前的审计结构单独固化

如果现在跳过这一层直接做真实 `paper` 下单，后续任何问题都会混在“推荐逻辑”和“执行逻辑”里，不利于稳健推进。

---

## 二、范围边界

### 2.1 本阶段纳入范围
- 独立期权订单计划模型
- `paper-only covered call execution prep` 服务
- 单标的执行准备接口
- 门禁状态输出：`ready / review_required / blocked`
- 执行计划 artifact 落盘

### 2.2 本阶段明确不做
- 真实 `paper` 期权下单
- `live` 期权交易
- 多标的批量期权执行
- 滚动展期、平仓、指派处理
- 前端 UI

---

## 三、方案对比

### 方案 A：继续只保留 pilot
**优点**
- 改动最少

**缺点**
- 推荐结果和执行层没有清晰边界
- 进入真实 `paper` 下单前还要补一层，同样要返工

### 方案 B：新增 execution prep，推荐
**优点**
- 推荐、门禁、订单计划三层清晰分离
- 后续进入真实 `paper` 下单时可以复用结构
- 更符合“稳健优先”

**缺点**
- 增加一层服务与 schema

### 方案 C：直接做真实 `paper` 下单
**优点**
- 表面推进更快

**缺点**
- 风险过高
- 当前系统缺少足够门禁与审计边界

---

## 四、目标行为

给定一个 `paper` 账户中的单个标的，系统应能：
- 重新运行该标的的 covered call pilot
- 若无合格推荐，返回 `blocked`
- 若有推荐但存在风险标签，返回 `review_required`
- 若推荐结果和门禁都满足，返回 `ready`
- 生成独立的期权订单计划，例如：
  - `underlying_symbol`
  - `expiry`
  - `strike`
  - `right`
  - `contracts`
  - `side`
  - `order_type`
  - `limit_price`
  - `multiplier`
- 将执行计划与门禁摘要落盘到 artifact

---

## 五、架构设计

### 5.1 新增模块

#### A. `covered_call_execution.py`
职责：
- 面向单标的执行 `execution prep`
- 调用现有 pilot 结果
- 构造期权订单计划
- 产出门禁状态和 artifact

#### B. `trade_option_models.py`
扩展：
- 新增执行准备请求/响应模型
- 新增期权订单计划模型

### 5.2 路由
新增：
- `POST /api/trade/options/covered-call/prepare`

请求示例：
```json
{
  "mode": "paper",
  "symbol": "AAPL",
  "dry_run": true,
  "dte_min": 21,
  "dte_max": 45,
  "max_spread_ratio": 0.15
}
```

响应示例：
```json
{
  "mode": "paper",
  "status": "review_required",
  "symbol": "AAPL",
  "gate_reason": "risk_tags_present",
  "warnings": ["tight_otm_buffer", "spread_near_limit"],
  "recommended": {...},
  "order": {
    "underlying_symbol": "AAPL",
    "sec_type": "OPT",
    "expiry": "2026-05-15",
    "strike": 230.0,
    "right": "C",
    "multiplier": 100,
    "contracts": 2,
    "side": "SELL",
    "order_type": "LMT",
    "limit_price": 1.25,
    "dry_run": true
  },
  "artifacts": {
    "summary": ".../summary.json",
    "execution_plan": ".../execution_plan.json"
  }
}
```

---

## 六、门禁状态机

### `blocked`
任一条件满足：
- `mode != paper`
- `dry_run != true`
- Gateway/Bridge 不健康
- pilot 没有合格推荐
- 推荐的限价无效
- 可卖张数小于 1

### `review_required`
满足以下任一条件：
- 推荐存在 `risk_tags`
- 价差接近阈值
- OTM buffer 过窄
- DTE 贴近区间边界

### `ready`
- 推荐存在
- 无阻断原因
- 无 review 风险标签
- 订单计划字段完整

---

## 七、测试策略

至少覆盖：
- `mode=live` 被 `400/paper_only` 拦截
- `dry_run=false` 被 `400/dry_run_only` 拦截
- pilot 无推荐时返回 `blocked`
- pilot 有推荐且带 risk tags 时返回 `review_required`
- pilot 有推荐且无 risk tags 时返回 `ready`
- `execution_plan.json` 正常落盘

---

## 八、成功标准

本阶段完成标准：
- 推荐结果与执行计划彻底分离
- 期权订单建模不污染股票主路径
- 可以稳定输出 `ready / review_required / blocked`
- 所有执行准备都可审计
- 仍然不触发真实期权下单

---

## 九、默认后续方向

完成 execution prep 后，默认下一阶段才讨论：
1. 真实 `paper` 期权下单
2. 更严格的价格保护与有效期控制
3. 订单状态回收与指派风险处理

当前仍不建议推进 `live`。
