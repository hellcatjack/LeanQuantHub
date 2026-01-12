# 回测优化综合报告（Final）

## 目标约束
- MaxDD_all ≤ 0.12
- MaxDD_52w ≤ 0.12
- CAGR ≥ 0.10
- Turnover_week ≤ 0.08

## 本轮最终修正
- 新增 `drawdown_exposure_floor`，避免分层降仓触发“归零持仓”导致收益塌陷。
- 风控与波动率门控保持启用，风险资产与防御篮子切换逻辑不变。

## 最新回测结果（基线验证）
- 运行 ID: 150
- MaxDD_all: 11.43%
- MaxDD_52w: 11.43%
- CAGR: 13.191%
- Sharpe: 1.009
- Turnover_week: 8.00%
- RiskOff_Count: 1
- MarketFilter_Count: 5
- ExposureCap: 28.00%

## 固化为默认回测参数（项目 16）
- market_ma_window=250
- top_n=30
- max_weight=0.04
- max_exposure=0.28
- vol_target=0.08
- risk_off_mode=defensive
- risk_off_symbols=SHY,IEF,GLD,TLT
- risk_off_pick=lowest_vol
- drawdown_tiers=0.08,0.10,0.12
- drawdown_exposures=0.4,0.25,0.0
- drawdown_exposure_floor=0.05
- market_filter=true
- max_drawdown=0.12
- max_drawdown_52w=0.12
- max_turnover_week=0.08
- rebalance_frequency=Weekly（周一开盘调仓）

## 结论
在新增“最低风险敞口”的前提下，最新回测仍满足全部硬约束，且收益与夏普维持在当前最优水平。已将该组合固化为项目 16 默认回测参数。
