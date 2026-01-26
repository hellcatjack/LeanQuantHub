# 数据页分页 + PreTrade 取消堆积修复 设计

**目标**
- 数据页 PIT 周度历史、PIT 财报历史、PreTrade 历史新增分页，默认每页 10 条。
- 修复 PreTrade 周度检查“取消中”长期堆积，确保取消可及时落盘为 `canceled`。

## 架构与数据流
后端新增 `page` 版本接口统一返回 `Paginated`，前端 DataPage 接入 `PaginationBar`。PreTrade 取消堆积从状态落地不完整入手：
- 若 `run` 仍处 `queued`，取消时直接落 `canceled` 并同步 steps 为 `canceled`。
- 若 `cancel_requested` 且 steps 已全终态，则在读取或 runner 末尾自动落 `canceled`。

## 组件/接口与错误处理
- 新增接口：
  - `GET /api/pit/weekly-jobs/page?page=&page_size=`
  - `GET /api/pit/fundamental-jobs/page?page=&page_size=`
  - `GET /api/pretrade/runs/page?project_id=&page=&page_size=`
  - 返回 `{items,total,page,page_size}`，采用统一 `MAX_PAGE_SIZE`。
- 前端 `DataPage` 增加 `page/pageSize/total` 状态，对三处历史表格使用 `PaginationBar`，默认 10。
- 取消落盘：
  - `cancel_pretrade_run` 中处理 `queued` 直接 `canceled` + steps canceled。
  - `run_pretrade_run` 末尾或 `get_pretrade_run` 前置修复 `cancel_requested` + steps 终态落 `canceled`。
- 错误处理：参数非法返回 422；前端以 `form-error` 显示。

## 测试与验收
- 后端单测：分页接口（page/page_size/total/offset），PreTrade 取消落盘与 `cancel_requested` 终态收敛。
- 前端：数据页三处分页条显示、默认 10 条、翻页生效（Playwright 验证）。

**验收标准**
- PIT 周度/财报/PreTrade 历史均有分页条，默认 10 条/页。
- PreTrade 周度检查取消后不再长期停留在“取消中”。
- 旧非分页接口兼容保留。
