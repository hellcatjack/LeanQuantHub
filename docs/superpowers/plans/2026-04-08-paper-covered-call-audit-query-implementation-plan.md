# Paper Covered Call Audit Query 实施计划

- [x] 为 audit 查询定义 request/result 模型与 schema
- [x] 新增 `covered_call_audit.py`，复用 timeline 聚合并加载原始阶段摘要
- [x] 新增 `/api/trade/options/covered-call/audit` 路由
- [x] 先写服务层与路由层红灯测试
- [x] 实现最小代码并跑绿灯
- [x] 运行整组 covered call 后端回归
- [x] 做一次真实 HTTP 自测并确认返回结构
