# Paper Covered Call Audit Query 设计

## 目标
新增一个统一只读查询面，把 `review / submit / receipt / timeline` 四层信息聚合成单次响应，便于后续前端只读接入和人工审计。

## 范围
- 新增后端服务 `covered_call_audit.py`
- 新增接口 `POST /api/trade/options/covered-call/audit`
- 只允许 `mode=paper`
- 只读，不触发任何新命令

## 输入输出
输入：
- `mode`
- `review_id`

输出：
- `status`
- `timeline_state`
- `review`
- `submit`
- `receipt`
- `timeline`
- 相关 artifact 路径

## 聚合方式
1. 先调用 timeline 聚合，复用其命令关联规则
2. 再按 timeline artifacts 反查原始 review bundle、submit summary、receipt summary
3. 返回统一 audit 负载，避免调用方自己拼路径和 JSON

## 错误处理
- 非 `paper`：`paper_only`
- 空 `review_id`：`review_id_required`
- timeline/review bundle 缺失：透传现有错误

## 测试
- 服务层：统一聚合、缺失 submit/receipt、paper_only
- 路由层：paper_only 映射、服务透传
