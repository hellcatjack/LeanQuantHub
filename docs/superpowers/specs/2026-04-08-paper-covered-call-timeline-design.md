# Paper Covered Call Timeline 设计

## 目标
为 `paper-only covered call` 试点补一层只读时间线查询，把 `review -> submit -> receipt` 串成单一审计视图，避免调用方自己拼接 artifacts。

## 范围
- 新增后端聚合服务 `covered_call_timeline.py`
- 新增接口 `POST /api/trade/options/covered-call/timeline`
- 只允许 `mode=paper`
- 只读，不触发任何新命令

## 输入输出
输入：
- `mode`
- `review_id`

输出：
- `status`
- `timeline_state`
- `latest_submit`
- `latest_receipt`
- `stages`
- 关联 artifact 路径

## 聚合规则
1. 从 `artifacts/<review_id>/review_bundle.json` 读取 review 基线
2. 扫描 `options_submit_*/summary.json`，取同 `review_id` 的最新 submit
3. 扫描 `options_receipt_*/summary.json`，取同 `review_id` 的最新 receipt
4. 优先级：`receipt > submit > review`

## timeline_state 规则
- review 被阻断：`review_blocked`
- 只有 review：`review_<status>`
- submit 被阻断：`submit_blocked`
- submit 已提交但无 receipt：`submit_submitted`
- receipt 存在：直接采用 `receipt_state`

## 错误处理
- 非 `paper`：`paper_only`
- 空 `review_id`：`review_id_required`
- review bundle 缺失：`review_not_found`

## 测试
- 服务层：review-only、latest submit/receipt 聚合、paper_only
- 路由层：paper_only 映射、服务透传
