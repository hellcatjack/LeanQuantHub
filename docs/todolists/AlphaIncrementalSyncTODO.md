# Alpha 历史数据增量抓取 TODO

## 目标
- 避免每次全量拉取 Alpha 历史数据，改为“先评估系统现状，再按缺口增量更新”
- 减少 API 流量与耗时，同时保持数据完整性与可追溯性
- 保留全量拉取能力作为回退路径

## 范围
- 仅影响 Alpha 数据源（日线历史抓取）
- Stooq/Yahoo 已禁用，本 TODO 仅覆盖 Alpha 抓取逻辑
- 适用于数据页“全量抓取（全美股）”与单标的 sync

## 关键策略（设计要点）
- Listing 刷新应可控（默认“仅在过期时刷新”）
- 拉取策略基于本地 `coverage_end` 与最新交易日缺口
- 小缺口走 `outputsize=compact`，大缺口或无历史走 `full`
- 在 compact 数据不足覆盖缺口时自动升级为 full

## 任务清单

### Phase 0：现状盘点
1. 统计所有 Alpha dataset 的 `coverage_end` 与最新交易日差值分布
2. 记录“已有数据但未更新”的标的数量与分段（0~30/31~120/120+天）
3. 确认当前 `only_missing` 默认值与全量抓取的行为
4. 检查 listing 文件最近更新时间与刷新频率

### Phase 1：Listing 刷新可控化
1. 新增 `refresh_listing_mode`：
   - `always`：每次刷新
   - `stale_only`：超过 TTL 才刷新（默认）
   - `never`：不刷新
2. 增加 TTL 配置（默认 7 天，可调）
3. 在 bulk job 日志与 message 中输出 refresh 策略与是否触发
4. UI 增加刷新策略与 TTL 的说明字段

### Phase 2：Alpha 增量抓取逻辑
1. 计算缺口：`gap_days = latest_complete - coverage_end`
2. 决策规则：
   - `reset_history=true` 或 `coverage_end` 为空 → 强制 full
   - `gap_days <= compact_days` → 使用 compact
   - 其他情况 → full
3. 新增配置项：
   - `alpha_compact_days`（默认 120）
   - `alpha_incremental_enabled`（默认 true）
4. compact 结果校验：
   - 若 compact 数据最早日期仍晚于 `coverage_end` → 立即升级为 full 或重排 full
5. Job message 增加：
   - `alpha_outputsize=compact/full`
   - `gap_days`
   - `coverage_end`
   - `latest_complete`

### Phase 3：UI 与 API 参数接入
1. 数据页全量抓取增加“增量策略”设置：
   - 增量开关
   - compact 阈值天数
   - refresh listing 策略与 TTL
2. 单标的同步支持“增量/全量”模式提示
3. i18n 文案补齐

### Phase 4：可观测性与审计
1. 将 outputsize 与缺口信息写入 `DataSyncJob.message`
2. 在任务列表中显示 compact/full 与 gap_days
3. 为 rate limit 触发记录自动调速动作

### Phase 5：验证与回归
1. 手动验证：
   - 有历史、缺口 < 120 天 → compact
   - 缺口 > 120 天 → full
   - 无历史 → full
2. compact 缺口覆盖不足时是否自动升级为 full
3. 校验 `coverage_end` 与新增数据的日期一致性
4. 回归：全量抓取仍可用

## 验证标准
- 同一标的在连续日更新时，不再重复 full 拉取
- 仍能覆盖缺口，`coverage_end` 正常前移
- listing 刷新不会每次触发，符合 TTL 策略

## 验证记录（2026-01-10）
- 增量开关打开：`Alpha_S_Daily` gap=0 -> `alpha_outputsize=compact`
- 增量开关关闭：`Alpha_S_Daily` -> `alpha_outputsize=full`
- 大缺口：`Alpha_RTN_Daily` gap=2107 -> `alpha_outputsize=full`
- 回退验证：临时将 `Alpha_S_Daily` coverage_end 调整到 2025-06-23 且 compact_days=365，触发 `alpha_compact_fallback=1` 并回退 full
- listing TTL：bulk job message 显示 `refresh_listing; mode=stale_only; ttl_days=7; listing_age_days=6; refresh=0`
- UI：更新任务列表显示 `alpha=compact/full`、`gap` 与 “compact 回退” pill，`gap_days=0` 可正确展示

## 风险与回滚
- 风险：compact 缺口不足导致漏数据 → 自动升级 full + 日志提示
- 回滚：关闭 `alpha_incremental_enabled` 或强制 full
