# PIT 市值与成交额权重 TODO

## 目标与约束
- **成交额口径**：使用 `raw close × raw volume`（来自 `data/curated`），不使用“复权价×原始成交量”。
- **权重方案**：采用方案 A（加权和，更可控）  
  `w = α·log1p(mcap) + (1-α)·log1p(dv)`，再做归一化（默认均值归一化）。
- **PIT 市值**：从 Alpha `SHARES_OUTSTANDING` 补抓，按 **available_date <= cutoff_date** 选最近股本，再乘以 **快照日 raw close** 生成 `pit_market_cap`。
- **防前视**：股本无披露时间，默认 `shares_delay_days=45`（可配置）作为保守可用日。
- **幂等与并发**：所有抓取与生成任务必须可重复、可恢复；同一服务器多副本时需全局锁。

## 数据来源与落盘结构
- Alpha 基本面目录：`data/fundamentals/alpha/<SYMBOL>/`
- 新增股本缓存：`shares_outstanding.json`
- PIT 周度快照：`data/factors/pit_weekly_fundamentals/pit_fundamentals_YYYYMMDD.csv`
- 快照新增字段（建议）：
  - `shares_outstanding`、`shares_available_date`、`shares_source`
  - `pit_market_cap`（PIT 市值）

## 任务清单（按顺序）

### Phase 1：补抓 SHARES_OUTSTANDING
- [ ] 扩展 `scripts/fetch_alpha_fundamentals.py` 的 `ALPHA_FUNCTIONS`，新增 `SHARES_OUTSTANDING → shares_outstanding.json`。
- [ ] 延用 `JobLock(alpha_fetch)`，确保全局唯一抓取；保持限速/重试逻辑一致。
- [ ] 文档更新：`docs/data_sources/alpha.md` 补充 `SHARES_OUTSTANDING` 的输出路径与用途。
- [ ] 自测：手动抓取单一 symbol（AAPL），确认输出结构含 `date` + `shares_outstanding_basic/diluted`。

### Phase 2：PIT 市值生成
- [ ] 在 `scripts/build_pit_fundamentals_snapshots.py` 增加 CLI 参数：
  - `--shares-delay-days`（默认 45）
  - `--shares-preference`（basic/diluted，默认 diluted）
  - `--price-source`（raw/adjusted，默认 raw）
- [ ] 加载股本：读 `shares_outstanding.json`，解析为 `[(date, shares)]`，并生成 `available_date = date + shares_delay_days`。
- [ ] 对齐规则：对每个 `snapshot_date` 计算 `cutoff_date`（已有 `report_delay_days` 逻辑），选择 `available_date <= cutoff_date` 的最近股本记录。
- [ ] 价格口径：从 `data/curated` 读取 **raw close**，用 `snapshot_date` 当日（或前一交易日）价格。
- [ ] 计算 `pit_market_cap = shares_outstanding × raw_close`。
- [ ] 写入快照字段：`shares_outstanding`、`shares_available_date`、`shares_source`、`pit_market_cap`。
- [ ] 更新 `pit_fundamentals_meta.json`：记录 `shares_delay_days`、`shares_preference`、`price_source`。
- [ ] 自测：抽样 1~2 个快照文件检查字段存在与数值合理。

### Phase 3：训练权重逻辑（方案 A）
- [ ] 在 `ml/train_torch.py` 增加权重配置：
  - `sample_weight.scheme = mcap_dv_mix`（或 `market_cap_dollar_volume_mix`，二选一并统一）
  - `sample_weight.alpha`（默认 0.6）
  - `sample_weight.dv_window_days`（可选，默认 20）
- [ ] 成交额计算：读取 `data/curated` 的 raw close/volume，计算 `dv_raw`（可选做 20 日均值）。
- [ ] 市值来源：优先使用 PIT 快照中的 `pit_market_cap`；若缺失才 fallback 到 `OVERVIEW.MarketCapitalization`（并打印告警）。
- [ ] 归一化：默认均值归一化；保留 `clip_min/clip_max` 以防极端值。
- [ ] 训练 metrics 写入 `sample_weight` 统计（mean/min/max/coverage/alpha）。
- [ ] 自测：训练一次，日志中打印 `scheme/alpha/coverage`，训练详情可见统计。

### Phase 4：前端与配置
- [ ] ML 训练参数表单新增：
  - 权重方案下拉：none / dv / mcap / mcap_dv_mix
  - `alpha` 输入框（0–1）
  - `dv_window_days` 输入框（可选）
- [ ] i18n 文案补齐（中文/英文）。
- [ ] `ml/config.json` 更新默认值与注释说明。
- [ ] 前端 build + 重启服务，自测 UI 传参与生效。

### Phase 5：回填与验证
- [ ] 全量补抓 `SHARES_OUTSTANDING`（全美股）。
- [ ] 全量重建 PIT 周度快照（新增 `pit_market_cap`）。
- [ ] 对比训练/回测：  
  - baseline（无权重） vs 方案A（α=0.6）  
  - 观察 NDCG、IC、RankIC 与回测指标变化。
- [ ] 记录结果到训练/回测报告或新文档。

## 风险与注意点
- `OVERVIEW.MarketCapitalization` 非 PIT，仅能用于 fallback；优先使用 `shares_outstanding × raw close`。
- `curated_adjusted` 只调价格不调成交量，因此成交额**必须使用 raw close × raw volume**。
- `shares_outstanding` 无披露日期，`shares_delay_days` 必须足够保守以避免前视。

## 验收标准（最低）
- PIT 快照新增 `pit_market_cap` 字段，并与 raw close 口径一致。
- 训练任务能选择 `mcap_dv_mix`，日志与 metrics 中显示 `alpha/coverage`。
- 同一训练参数重复运行结果稳定，未出现前视或异常漏算。
