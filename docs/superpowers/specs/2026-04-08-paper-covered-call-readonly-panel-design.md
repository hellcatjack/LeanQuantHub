# Paper Covered Call 只读前端面板设计

## 背景
当前后端已经具备 `pilot / prepare / review / submit / receipt / timeline / audit / audit/recent` 只读与半只读能力，但前端还没有统一入口查看最近审核、单条审计聚合和时间线。用户只能手工记 `review_id` 再调用接口，操作成本高，也不利于后续稳健推进期权试点。

本阶段只做 `paper` 模式下的只读面板，不引入任何真实期权提交流程，不改变现有股票交易主路径。

## 目标
在 `LiveTrade` 页面增加一个 `Covered Call Pilot` 只读面板，支持：

1. 查看最近的 covered call review 记录
2. 选择某条 review 并查看聚合 audit
3. 展示 review / submit / receipt / timeline 的关键状态
4. 明确标识 `paper-only` 和只读性质
5. 保持页面稳健：接口失败时可见错误，不影响现有交易功能

## 范围
### 包含
- 新增前端只读组件 `CoveredCallAuditPanel`
- 在 `LiveTradePage` 的执行区接入组件
- 调用后端：
  - `POST /api/trade/options/covered-call/audit/recent`
  - `POST /api/trade/options/covered-call/audit`
- 组件单测、页面接线单测、Playwright 只读回归
- 中英文文案

### 不包含
- 真实期权 submit
- live 模式期权功能
- 期权交易前端表单
- review token 输入或审批动作
- 新的后端行为变更

## 设计
### 架构分层
1. `LiveTradePage`
   - 负责取数、缓存 `recent` 列表、维护当前选中的 `review_id`
   - 负责错误状态和刷新动作
2. `CoveredCallAuditPanel`
   - 纯展示组件
   - 接收 `recent items / selected review / audit payload / loading / error / callbacks`
3. 后端接口
   - 保持现状，只做前端消费

### 交互
1. 页面进入执行区后加载最近 review 列表
2. 若存在记录且当前未选中 review，默认选中最新一条
3. 选中 review 后加载对应 audit
4. 提供两个只读刷新动作：
   - 刷新最近记录
   - 刷新当前审计
5. 审计面板至少展示：
   - review id
   - status
   - timeline state
   - symbol
   - latest command id
   - review / submit / receipt 状态摘要
   - timeline stages
   - artifact 摘要路径

### 错误处理
- `recent` 失败：显示列表错误，但不阻断页面其他区域
- `audit` 失败：保留最近列表，只在详情区显示错误
- `paper_only` 或空列表：明确显示空态/限制说明
- 不做自动重试风暴；默认手工刷新即可

## 测试
1. 组件单测
   - 渲染 recent 列表
   - 渲染 audit 摘要与空态
2. 页面单测
   - `LiveTradePage` 包含 covered call 只读面板标题和 `paper-only` 提示
3. Playwright
   - 拦截 `audit/recent` 和 `audit`
   - 验证能看到 recent 列表
   - 点击或自动选中后能看到 audit 详情
   - 验证无 submit 按钮

## 成功标准
- `LiveTrade` 中可直接查看最近 covered call review
- 选中某条 review 后能看到聚合审计与时间线摘要
- 错误和空态可理解
- 不引入真实交易入口
- 前端构建通过，单测和 E2E 回归通过
