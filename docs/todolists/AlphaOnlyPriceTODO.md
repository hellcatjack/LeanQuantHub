# AlphaOnlyPriceTODO

目标：训练/回测/快照全部使用 Alpha 的复权价格与复权因子，彻底杜绝 Lean/Yahoo/Stooq 的价格回退与复权口径混用（Stooq/Yahoo 已禁用，禁止恢复）。

## Phase 0 现状审计与基线确认
- [ ] 盘点 `curated_adjusted/` 中 Alpha 与非 Alpha 的文件数量与覆盖率（按项目主题与全量两套口径输出）。
- [ ] 生成缺失清单：在“仅 Alpha”前提下无法覆盖的标的列表（含项目 16 / DATA_COMPLETE）。
- [ ] 核对训练/回测当前默认 vendor_preference 与价格选择逻辑（训练、回测、PIT 快照）。
- [ ] 核对 Alpha 抓取路径是否全部走 `TIME_SERIES_DAILY_ADJUSTED`。

## Phase 1 价格来源强制为 Alpha
- [ ] 训练默认 vendor_preference 改为 `["Alpha"]`：
  - [ ] `ml/config.json` 只保留 Alpha。
  - [ ] `backend/app/services/ml_runner.py` 默认值与传参对齐。
- [ ] 回测价格选择强制 Alpha：
  - [ ] `scripts/universe_pipeline.py` 增加 `price_vendor_preference` 过滤，只匹配 `*_Alpha_*_Daily.csv`。
  - [ ] `price_source_policy` 保持 `adjusted_only`，当 Alpha 缺失时直接剔除。
- [ ] 交易日历统一 Alpha：
  - [ ] `backend/app/services/trading_calendar.py` 与 `backend/app/routes/datasets.py` 的 trading_days 加入 vendor_preference=Alpha。
- [ ] PIT / 周度快照与因子脚本默认价格来源仅 Alpha（如 `build_pit_weekly_snapshots.py` / `build_pit_fundamentals_snapshots.py`）。

## Phase 2 复权因子逻辑统一为 Alpha
- [ ] Alpha 同步任务中复权因子来源固定为 Alpha：
  - [ ] `_build_factors_from_alpha_csv` 作为唯一来源，禁止 fallback 到 Lean/Yahoo。
  - [ ] 若 Alpha 缺失/不完整，标记为“无复权因子”，不生成 `curated_adjusted`。
- [ ] 删除/隔离非 Alpha 复权产物：
  - [ ] 清理或移出 `curated_adjusted` 中 `*_Lean_*_Daily.csv`、`*_Stooq_*_Daily.csv`。
  - [ ] 历史数据归档至单独目录，防止被回测误选。

## Phase 3 UI 与配置收敛
- [ ] 数据页/训练页/回测页显示当前价格源策略（只读：Alpha-only）。
- [ ] 统一隐藏/移除 Lean/Yahoo/Stooq 作为价格回退的入口与选项。
- [ ] 对“Alpha 未覆盖的标的”给出明确 UI 提示与剔除原因。

## Phase 4 数据重建与一致性校验
- [ ] 全量重建 Alpha 复权价：重新生成 `curated_adjusted`（仅 Alpha）。
- [ ] 复权质量审计：
  - [ ] 检查异常跳变、负值、重复日期。
  - [ ] 与 Alpha 原始 `adjusted_close` 做 spot check（如 NVDA / SPY / AAPL）。
- [ ] 项目 16 训练/回测覆盖率重算，记录变化与缺失原因。

## Phase 5 自动化与回归测试
- [ ] 价格选择与复权来源加入单元/集成测试（训练/回测/快照）。
- [ ] Playwright 走一遍项目 16：训练/回测/快照路径的 UI 检查。
- [ ] 生成审计报告（Alpha-only 覆盖率、缺失清单、口径一致性）。

## 交付验收标准
- [ ] 训练与回测的价格与复权因子仅来自 Alpha。
- [ ] `curated_adjusted` 不含非 Alpha 文件或无法被选择。
- [ ] 任意项目若使用 Alpha-only，覆盖率/缺失原因可追溯可解释。
- [ ] NVDA / SPY 等标的复权口径一致，价格不会出现 Lean 异常倍率。
