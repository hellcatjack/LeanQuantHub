# Paper Covered Call Review Gate 设计

**目标**
在现有 `paper-only covered call prepare` 基础上，再增加一层“审核与审批”边界：冻结执行前快照、生成短期有效的审批令牌、记录审计日志，为后续真实 `paper` 期权下单提供稳定入口。

**结论先行**
当前阶段仍然不应该直接进入真实期权提交。推荐先建设独立 `review gate`：
- 只支持 `paper`
- 只支持 `covered call`
- 只支持 `dry-run`
- 基于单标的执行准备结果生成审核包
- 输出 `review_id / approval_token / approval_expires_at`
- 记录 audit log
- 仍然不触发真实期权下单

---

## 一、为什么还要再加一层 review gate

`prepare` 已经完成三件事：
- 重新运行 pilot 并生成期权订单计划
- 区分 `blocked / review_required / ready`
- 输出 dry-run artifact

但它还缺一层执行前稳定边界：
- 没有短期审批令牌
- 没有冻结执行前运行态、持仓和 open orders 摘要
- 没有独立 review artifact
- 没有审计日志，无法形成“谁在什么状态下批准过什么计划”的链路

如果直接从 `prepare` 跳到未来的真实 `paper submit`，就会把推荐、执行准备、审核批准三层逻辑混在一起，不利于稳健推进。

---

## 二、范围边界

### 2.1 本阶段纳入范围
- `paper-only` 单标的 covered call review gate
- review bundle artifact
- approval token 生成与过期时间
- review 级 audit log
- 更严格的 Gateway/持仓/open orders 门禁摘要

### 2.2 本阶段明确不做
- 真实 `paper` 期权下单
- `live` 期权交易
- token 持久化到数据库
- 多标的批量 review
- 前端 UI

---

## 三、方案对比

### 方案 A：直接在未来 submit 时临时做审核
**优点**
- 少一层接口

**缺点**
- submit 逻辑会过重
- 复核与执行耦合，不利于回放与审计

### 方案 B：独立 review gate，推荐
**优点**
- 推荐、执行准备、审核批准边界清晰
- 后续真实 submit 只需验证 token 与 bundle
- 更符合稳健优先

**缺点**
- 新增一层服务、schema 和 route

### 方案 C：只补日志，不生成 token
**优点**
- 改动更少

**缺点**
- 不能形成后续真实 submit 的稳定接口

---

## 四、目标行为

给定一个 `paper` 账户中的单个标的，系统应能：
- 调用现有 `prepare` 结果
- 冻结当前 review 摘要：
  - runtime health 关键字段
  - 当前标的持仓摘要
  - open orders stale/conflict 摘要
- 若 `prepare=blocked`，返回 `blocked`，不生成 token
- 若 `prepare=review_required` 或 `ready`，生成：
  - `review_id`
  - `approval_token`
  - `approval_expires_at`
- 产出 review bundle artifact
- 写入 audit log

---

## 五、架构设计

### 5.1 新增模块

#### A. `covered_call_review.py`
职责：
- 调用 `prepare_covered_call_execution()`
- 读取并冻结 review 摘要
- 生成审批令牌和过期时间
- 写 review artifact 与 audit log

### 5.2 扩展模型
在 `trade_option_models.py` 与 `schemas.py` 中新增：
- `CoveredCallReviewRequest`
- `CoveredCallReviewArtifacts`
- `CoveredCallReviewResult`

### 5.3 新路由
新增：
- `POST /api/trade/options/covered-call/review`

---

## 六、Review 状态机

### `blocked`
任一条件满足：
- `mode != paper`
- `dry_run != true`
- `prepare.status == blocked`
- runtime/open_orders/positions 摘要不满足 review 要求

### `review_required`
- `prepare.status == review_required`
- 生成 token，但保留风险标签，后续真实 submit 必须显式确认

### `ready`
- `prepare.status == ready`
- review 摘要通过
- 生成 token，后续真实 submit 仍必须显式确认

说明：
- `review_required` 和 `ready` 都生成 token
- `blocked` 不生成 token

---

## 七、审批令牌策略

- 令牌使用随机高熵字符串生成
- 过期时间默认 `15 分钟`
- 令牌仅写入 review bundle artifact，不入库
- 返回值中包含：
  - `review_id`
  - `approval_token`
  - `approval_expires_at`

后续真实 submit 阶段再决定如何基于 `review_id + approval_token` 做校验。

---

## 八、Artifacts 与审计

建议落盘：
- `artifacts/options_review_<timestamp>/summary.json`
- `artifacts/options_review_<timestamp>/review_bundle.json`

bundle 至少包含：
- review 状态
- 审批令牌与过期时间
- `prepare` 返回的 `eligible/order_plan`
- runtime health 摘要
- 当前标的持仓摘要
- open orders 摘要
- 上游 prepare artifact 路径

审计日志：
- action: `covered_call_review_prepared`
- resource_type: `options_review`
- detail 包含：`symbol/status/review_id/approval_expires_at`

---

## 九、测试策略

至少覆盖：
- `mode=live` 被 `400/paper_only` 拦截
- `dry_run=false` 被 `400/dry_run_only` 拦截
- `prepare=blocked` 时无 token
- `prepare=ready` 时生成 token 与 bundle
- `prepare=review_required` 时仍生成 token，并保留风险标签
- audit log 被写入
- artifact 正常落盘

---

## 十、成功标准

本阶段完成标准：
- `prepare` 与 `review` 清晰分层
- review 结果可审计、可回放
- 审批令牌具备有效期
- 后续真实 `paper submit` 可以基于 review gate 接入
- 仍然不触发真实期权下单
