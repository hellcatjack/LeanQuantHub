# 实盘交易页评测与持仓修复设计

## 目标
- 解决实盘交易页“持仓为空”问题（Paper 模式有真实持仓但页面为空）。
- 精修实盘交易页关键文案，风格为“专业简洁”。
- 用 Playwright 验证页面显示与数据链路正确。

## 现状与根因
- 前端实盘交易页读取 `/api/brokerage/account/positions`。
- Lean bridge 输出 `positions.json` 字段为 `quantity`。
- 后端接口 `get_account_positions()` 直接透传 `items`，前端展示字段为 `position`。
→ 字段不一致导致持仓显示为空。

## 修复方案（后端归一化）
1) `backend/app/services/ib_account.py`
   - 在 `get_account_positions()` 中归一化字段：
     - 若条目包含 `quantity` 且缺少 `position`，补齐 `position = quantity`。
     - 若 `market_price` 为空且存在 `market_value` 与 `position`（非 0），补算 `market_price` 便于展示。
   - 其他字段保持原样，不破坏兼容。
2) 单测先行：
   - 扩展 `backend/tests/test_ib_account_positions.py`，输入 `quantity/market_value`，期望输出 `position/market_price`。

## 文案精修（专业简洁）
范围：`frontend/src/i18n.tsx` 实盘交易页相关字段。
- “账户概览/持仓”说明改为“Lean bridge 快照”。
- “更新时间”改为“最近刷新”。
- 空状态提示改为“暂无持仓或未刷新 / 暂无摘要数据”。

## 验证方案
- 后端：`pytest` 运行修改后的 ib_account_positions 测试。
- 前端：运行 Playwright `frontend/tests/live-trade.spec.ts`（如需要扩展，加入持仓表格非空断言）。
- UI 发布：`npm run build` + 重启 `stocklean-frontend`。

## 风险与边界
- 若 Lean bridge 路径/模式错误，仍会显示空数据；通过“Lean bridge 快照”文案提示数据源。
- 该修复仅做展示字段归一化，不改变交易逻辑。
