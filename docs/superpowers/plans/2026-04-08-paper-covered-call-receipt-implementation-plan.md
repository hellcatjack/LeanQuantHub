# Paper Covered Call Receipt Implementation Plan

- [x] 为 receipt 服务写失败测试：参数校验、rejected、open_confirmed、submitted_unconfirmed
- [x] 为 receipt 路由写失败测试：paper_only、空字段、服务透传
- [x] 新增 `CoveredCallReceiptRequest/Result` 模型与 schema
- [x] 实现 `covered_call_receipt.py`
- [x] 接入 `POST /api/trade/options/covered-call/receipt`
- [x] 运行 pytest 回归
- [x] 运行 `py_compile`
- [x] 重启 `stocklean-backend`
- [x] 做 HTTP receipt 自测
