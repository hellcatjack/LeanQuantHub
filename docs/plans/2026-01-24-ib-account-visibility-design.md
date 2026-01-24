# 实盘交易页账户信息可视化设计（IB）

## 背景与问题
当前实盘交易页面无法展示模拟账户的资金与持仓信息。后端 `ib_account` 为 stub，缺少 IB API 账户摘要与持仓的采集接口，前端也未请求相关数据，导致页面只有连接概览与账户号但无账户资产信息。

## 目标
- 页面可稳定展示**核心账户摘要**（白名单字段），并提供**全量账户字段**的折叠展示。
- 展示**当前持仓**与关键估值字段，支持排序与列折叠。
- 保持页面稳定性：自动 60s 刷新核心字段，全量字段通过手动刷新获取。
- IB 连接异常时仍显示最近一次可用数据并提示过期状态。

## 范围与非目标
**范围**
- 新增 IB 账户摘要与持仓 API。
- LiveTradePage 增加账户概览与持仓表格展示。

**非目标**
- 不做历史账户资金曲线。
- 不做复杂 PnL 分解与报表（仅展示 IB 返回字段与简单映射）。

## 方案选型
采用“核心字段缓存 + 全量字段手动刷新”混合模式：
- 核心字段定时缓存（60s）保障稳定可见。
- 全量字段手动刷新，减少 IB 请求压力与噪声。

## 页面与交互设计
- 新增“账户概览”卡片：
  - 默认展示核心字段（白名单）。
  - 展示更新时间、数据来源（cache/refresh）与过期标记。
  - 提供“手动刷新（全量）”按钮，获取 B 组全量标签。
- 新增“当前持仓”表格：
  - 列：Symbol / Position / AvgCost / MarketPrice / MarketValue / UnrealizedPnL / RealizedPnL / Account / Currency。
  - 支持排序与列折叠。
- 全量字段（B 组）折叠展示：
  - 默认隐藏，按分类或搜索过滤查看。
  - tag 原始名称优先显示，逐步补充中文别名。

## 字段范围（A 组白名单）
核心字段建议：
- NetLiquidation
- TotalCashValue
- AvailableFunds
- BuyingPower
- GrossPositionValue
- EquityWithLoanValue
- UnrealizedPnL
- RealizedPnL
- InitMarginReq
- MaintMarginReq
- AccruedCash
- CashBalance

## 后端接口设计
- `GET /api/ib/account/summary?mode=paper|live&full=false`
  - 返回核心字段（A 组）与 `refreshed_at`、`source`、`stale`。
  - full=true 时返回全量字段（B 组）。
- `GET /api/ib/account/positions?mode=paper|live`
  - 返回持仓列表与 `refreshed_at`。
- 可选：`POST /api/ib/account/refresh`
  - 触发一次全量刷新并更新缓存，返回刷新状态与错误信息。

## 后端服务设计
- 扩展 `ib_account.py`：
  - 使用 IB API `reqAccountSummary`/`accountSummary` 收集 tag->value。
  - 白名单过滤生成核心字段。
  - 全量字段保留原始 tag。
  - 解析数值与单位（货币字段保留 currency）。
- 扩展持仓采集：
  - 使用 `reqPositions`/`position` 收集 symbol、position、avgCost、account。
  - 通过市场快照补齐 marketPrice、marketValue、unrealizedPnL（若可用）。
- 缓存策略：
  - 核心字段定时 60s 刷新。
  - 手动刷新覆盖缓存并返回 full=true 数据。

## 错误处理与状态
- IB 错误码（1100/1101/1102、502/503/504）统一映射为连接异常。
- 自动刷新失败：保留旧数据并标记 stale。
- 手动刷新失败：保留旧数据并返回错误提示。
- 无市场价时，仅展示 position/avgCost，MarketPrice/Value 标记为不可用。

## 安全与脱敏
- account_id 继续脱敏展示。
- 全量字段仅在手动刷新后显示，默认折叠。
- 前端不显示敏感/可识别字段（如未授权标记）。

## 测试与验收
测试：
- 单测：tag 解析、白名单过滤、错误码映射、缓存读写。
- API 测试：summary/positions 返回结构、stale 标记逻辑。
- 前端：空状态、过期提示、手动刷新失败提示。

验收：
- 实盘交易页可看到核心账户信息（60s 自动更新）。
- 手动刷新后可展开查看全量字段。
- 持仓表正常展示，异常时有清晰提示。
