# Paper Covered Call Submit 设计

**目标**
在现有 `paper-only covered call review gate` 基础上，新增真实 `paper` 期权提交入口。提交必须显式依赖 `review_id + approval_token`，并在提交前再次校验 Gateway 运行态、持仓、open orders 与 review 有效期。执行仍走长期运行的 Lean bridge，不新增后端直连下单分支。

**结论先行**
推荐方案是继续复用现有 leader command 链路，但将命令协议最小化扩展为“单腿 covered call 期权合约提交”。
- 只支持 `paper`
- 只支持 `covered call`
- 只支持单腿 `SELL CALL`
- 必须提供 `review_id + approval_token`
- 提交前再次做 runtime / positions / open orders 门禁
- 真正下单继续由长连 Lean bridge 执行
- 不把当前股票 one-shot 执行器改成通用期权执行器

---

## 一、为什么不能直接复用当前股票 submit

当前股票 submit 链路由两部分构成：
- Python 侧写入 `submit_order` command JSON
- Lean bridge 长连消费命令并调用 `brokerage.PlaceOrder()`

但现有协议只支持股票字段：
- `symbol`
- `quantity`
- `order_type`
- `limit_price`
- `outside_rth`
- `adaptive_priority`

Lean 消费端也直接固定创建：
- `SecurityType.Equity`
- `MarketOrder / LimitOrder`

这意味着如果直接把期权订单塞进现有路径：
- 合约身份无法表达
- Lean 端无法构造 `Option` 合约
- 结果回执无法反映期权合约信息
- 后续审计会混乱

所以 submit 阶段的核心不是新增一个 API，而是把命令协议和 bridge 消费端同步扩到“最小期权合约提交”。

---

## 二、范围边界

### 2.1 本阶段纳入范围
- `POST /api/trade/options/covered-call/submit`
- 只允许 `mode=paper`
- 只允许 `dry_run=false`
- 必须验证：
  - `review_id`
  - `approval_token`
  - `approval_expires_at`
  - runtime health
  - 持仓仍满足 covered call 条件
  - 当前不存在同标的 open option order 冲突
- Python 侧期权 submit command 写入
- Lean bridge 侧期权 submit command 解析与实际 `PlaceOrder`
- command result 回写与后端轮询
- submit artifact 与 audit log

### 2.2 本阶段明确不做
- `live` 期权交易
- 通用多腿期权框架
- 裸卖、价差、collar
- 前端 UI
- TradeOrder 数据库结构泛化到完整期权模型
- 长期审批 token 持久化入库

---

## 三、方案对比

### 方案 A：后端直连 IB 提交期权单
**优点**
- 实现路径短

**缺点**
- 与现有长连 bridge 架构分叉
- 多 client id / 连接竞争风险更高
- 稳健性最差

### 方案 B：扩展 leader command 为期权合约 submit，推荐
**优点**
- 复用现有 submit/result 轮询骨架
- 继续由长连 Lean/IB 负责真实下单
- 更符合“稳健优先”

**缺点**
- Python 与 Lean 两侧都要改
- 需要新的 C# 测试覆盖

### 方案 C：仅做 submit 记录，不实际下单
**优点**
- 风险最低

**缺点**
- 无法验证真实执行链路
- 对 pilot 推进价值不足

---

## 四、目标行为

用户已通过 `review` 获得：
- `review_id`
- `approval_token`
- `approval_expires_at`
- `order_plan`

调用 submit 时，系统应：
1. 校验 `mode=paper`
2. 校验 `dry_run=false`
3. 重新加载 review bundle
4. 校验 token 和过期时间
5. 再次检查：
   - runtime health 必须 `healthy`
   - 标的持仓仍然满足 `100 * contracts`
   - open orders 对该 underlying 无冲突
6. 写入期权 submit command
7. 轮询 `command_results/<command_id>.json`
8. 返回：
   - `submitted`
   - `rejected`
   - `timeout_pending`
9. 落盘 submit artifact 并写 audit log

---

## 五、架构设计

### 5.1 Python 侧

#### A. `covered_call_submit.py`
职责：
- 读取 review bundle
- 校验 token、过期时间、运行门禁
- 生成 submit artifact
- 写入扩展后的期权 submit command
- 轮询 command result
- 生成 submit 结果

#### B. `trade_option_models.py`
新增：
- `CoveredCallSubmitRequest`
- `CoveredCallSubmitResult`
- `OptionSubmitPlan`

#### C. `lean_bridge_commands.py`
扩展 `write_submit_order_command()`，支持最小期权字段：
- `sec_type`
- `underlying_symbol`
- `expiry`
- `strike`
- `right`
- `multiplier`

仍保留股票默认行为，不破坏现有调用方。

### 5.2 Lean 侧

#### A. `LeanBridgeResultHandler.cs`
扩展 `submit_order` command 解析：
- 若 `sec_type != OPT`，继续按股票路径
- 若 `sec_type == OPT`，校验：
  - `underlying_symbol`
  - `expiry`
  - `strike`
  - `right`
  - `quantity`
- 构造 Option `Symbol`
- 仅允许 `SELL` covered call 对应的负数量
- 仅允许 `LMT`
- 调用 `brokerage.PlaceOrder()`
- command result 写回期权字段，便于审计

#### B. 不改 `LeanBridgeExecutionAlgorithm.cs`
原因：
- 当前它是短生命周期 one-shot 股票执行器
- covered call submit 走的是长连 bridge command 路径
- 本阶段不应顺手把 one-shot 扩成通用期权执行器

---

## 六、Review 与 Submit 的关系

### review 阶段负责
- 生成审批令牌
- 冻结审核摘要
- 产出 `order_plan`

### submit 阶段负责
- 验证审核包仍然有效
- 重新确认运行态与持仓没有漂移
- 真正写入期权 submit command
- 等待或收集 command result

这两层必须分开，避免“审核结果”和“执行结果”混在同一个 artifact 中。

---

## 七、命令协议

提交 command payload 最小结构：

```json
{
  "command_id": "submit_order_cc_123",
  "type": "submit_order",
  "sec_type": "OPT",
  "underlying_symbol": "AAPL",
  "symbol": "AAPL",
  "expiry": "2026-05-15",
  "strike": 210.0,
  "right": "C",
  "multiplier": 100,
  "quantity": -1,
  "tag": "covered_call:review123",
  "order_type": "LMT",
  "limit_price": 1.25,
  "outside_rth": false,
  "requested_at": "...",
  "expires_at": "...",
  "version": 1
}
```

约束：
- `sec_type=OPT` 时必须带完整合约字段
- `quantity` 必须为负值，表示卖出 call
- `order_type` 仅允许 `LMT`
- `adaptive_priority` 在期权路径中不使用

---

## 八、审计与 artifacts

### 8.1 review bundle
继续复用现有 `options_review_<timestamp>/review_bundle.json`

### 8.2 submit artifact
新增目录：
- `artifacts/options_submit_<timestamp>/summary.json`
- `artifacts/options_submit_<timestamp>/submit_request.json`
- `artifacts/options_submit_<timestamp>/command_result.json`

### 8.3 audit log
新增 action：
- `covered_call_submit_requested`
- `covered_call_submit_result`

detail 至少包含：
- `symbol`
- `review_id`
- `command_id`
- `status`
- `command_result_status`

---

## 九、失败与收敛策略

### 9.1 直接阻断
- `paper_only`
- `dry_run_false_required` 之外的非法输入
- token 不匹配
- token 已过期
- runtime health 非 `healthy`
- 持仓不足 `100 * contracts`
- open orders 冲突

### 9.2 可等待状态
- command 尚未回写结果
- 在限定等待窗口内返回 `timeout_pending`
- 保留 artifact，便于后续人工或程序继续轮询

### 9.3 明确拒绝
- Lean command result 返回：
  - `invalid`
  - `expired`
  - `unsupported_order_type`
  - `option_contract_invalid`
  - `place_failed`
  - `not_connected`

---

## 十、测试策略

### Python 测试
- submit request/result model
- token 过期与不匹配
- runtime health 不健康阻断
- 持仓变化后阻断
- open orders 冲突阻断
- command result 成功/拒绝/超时
- route 的 `paper_only` / `symbol_required` / 成功透传
- command writer 能正确输出期权字段

### C# 测试
- `submit_order` 期权 payload 解析成功
- 缺字段时返回 `option_contract_invalid`
- 非 `LMT` 被拒绝
- 正确构造 `Option` 合约并调用 brokerage
- command result 包含期权字段
- 股票 submit 现有行为不回归

---

## 十一、成功标准

本阶段完成标准：
- `paper-only covered call submit` 能真实写入期权 submit command
- Lean bridge 能消费并回写期权 command result
- token / runtime / 持仓 / open orders 门禁全部生效
- 股票 submit 行为不受影响
- 仍然不触碰 `live`
- 仍然不把期权交易泛化进当前股票主交易路径
