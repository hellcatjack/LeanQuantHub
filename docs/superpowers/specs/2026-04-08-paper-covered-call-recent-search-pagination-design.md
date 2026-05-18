# Paper Covered Call Recent Search/Pagination 设计

## 背景
当前 `Covered Call Pilot` 只读面板已经能展示最近 review 和聚合 audit，但最近记录列表仍是固定数量、无搜索、无真实分页。随着 review 记录持续累积，前端会很快失去可用性。

## 目标
为 `POST /api/trade/options/covered-call/audit/recent` 增加真实搜索和分页能力，并在 `LiveTrade` 前端面板接入：

1. 按 `review_id / symbol / status / timeline_state` 模糊搜索
2. 使用服务端 `offset + limit` 分页
3. 返回 `total` 和 `has_more`，避免前端猜测页数
4. 前端提供搜索框、上一页/下一页、当前结果计数
5. 继续保持 `paper-only + read-only`

## 设计选择
### 方案 A：前端假分页
只请求固定前 N 条，前端本地搜索/分页。

问题：
- 记录增长后会丢数据
- 搜索结果不完整
- 与真实审计历史不一致

### 方案 B：服务端搜索 + offset 分页，采用
- 接口扩展为 `mode / limit / offset / query`
- 后端先读取 review bundle，再按 query 过滤，再按时间倒序分页
- 返回 `items / total / has_more`

理由：
- 语义正确
- 前端简单
- 后续扩展到更多过滤条件也不需要重写前端

## 接口变更
请求：
- `mode: paper`
- `limit: int`
- `offset: int`
- `query: str`

响应新增：
- `total: int`
- `has_more: bool`

## 前端交互
- 搜索框默认空
- 输入查询词后重置到第一页
- 点击上一页/下一页时，根据 `offset/limit` 请求新页
- 当前选中 review 如果不在新页中：
  - 自动选中新页第一条
  - 若新页为空则清空详情

## 测试
### 后端
- query 能按 `review_id` 过滤
- query 能按 `symbol/status/timeline_state` 过滤
- offset/limit 生效
- total/has_more 正确

### 前端
- 搜索输入存在
- 翻页控件存在
- 搜索后会刷新 recent 列表
- 翻页后显示新的 review

### E2E
- mock 两页 recent 数据
- 搜索并翻页
- 审计详情仍可自动切换
- 仍无 submit 按钮

## 成功标准
- recent 列表支持真实搜索和分页
- 审计详情与选中项保持一致
- 搜索/翻页不会破坏现有只读边界
