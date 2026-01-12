# 正式交易前数据同步 TODO（周度调仓）

> 目标：在周一开盘前完成「价格增量 + 基本面增量 + PIT 快照 + 训练/评分」闭环，确保可回退、可复跑、可审计。

## 前提与约束
- Alpha 限速：~154 次/分钟（实测上限，实时可调；以 `alpha_rate.json` 为准）
- 基本面刷新耗时：~13 小时（当前评估）
- 价格历史增量耗时：~3 小时（当前评估）
- `alpha_fetch` 全局锁：价格同步与基本面刷新必须串行
- PreTrade checklist 全局锁：同一时间只允许一个 checklist 运行
- 最新交易日判定必须基于交易日历（节假日不偏差）
- 交易日历刷新耗时：秒级（exchange_calendars，本地生成）

## 周度时间轴（ET）
### T-2（周六）
1) 交易日历刷新（本地日历）
   - 使用 `DATA_ROOT/config/trading_calendar.json` 配置生成 `universe/trading_calendar/*`
   - 验收：calendar_end 覆盖到下一个交易周；来源为 `exchange_calendars+spy`
2) Listing 刷新（低频）
   - `refresh_listing_mode=stale_only`，TTL=7 天
   - 验收：若未过期则跳过，message 显示 refresh=0
3) 价格增量同步（3h）
   - 触发全量抓取/增量策略，仅更新缺口
   - 验收：增量任务成功，`alpha_outputsize`/`gap_days` 可见

### T-1（周日）
4) 基本面增量刷新（~13h）
   - 建议早上启动（如 06:00）
   - 验收：fundamentals 缓存更新完成，缺失清单可追踪
5) PIT 周度快照生成
   - 规则：周一开盘调仓，快照取上一个交易日收盘
   - 验收：`universe/pit_weekly` 连续无缺失
6) PIT 基本面快照生成
   - 输入：fundamentals 缓存 + PIT 周度快照日期
   - 验收：`factors/pit_weekly_fundamentals` 写入成功
7) 模型训练/评分
   - 训练完成则进入调仓；否则回退上次模型

### T（周一开盘）
8) 调仓前检查
   - 覆盖率、缺失清单、最新快照一致性
   - 验收：若失败则回退上次周度产物

> 补充：周一开盘前也允许触发完整 checklist（非仅限周六/周日）。

## 执行流程 TODO（串行）
### Phase 0 — 预检查
- [ ] Checklist 全局锁：同一时间只允许一个 checklist 运行
- [ ] 确认 `alpha_fetch` 未被占用（避免并发抓取）
- [ ] 确认 `alpha_rate.json` 与 `alpha_fetch.json` 配置正确
- [ ] 校验 `alpha_rate.json` 目标 `max_rpm≈154`（可调）并记录到本次 run
- [ ] 确认 `trading_calendar.json` 配置有效，必要时执行 refresh
- [ ] 检查最新 `alpha_symbol_life.csv` 更新时间（TTL）
- [ ] 交易日校验：以交易日历为准确认“上一交易日”日期（auto=exchange_calendars+spy）
- [ ] 数据完整性门控：`coverage_end >= 上一交易日`，未达标则延后同步/快照

### Phase 1 — 价格增量同步（T-2）
- [ ] 触发批量增量同步（仅缺口）
- [ ] 价格增量 latest_complete 由交易日历驱动（非仅周末回退）
- [ ] 确认 `alpha_outputsize` 与 `gap_days` 记录入 job message
- [ ] 运行价格质量扫描（可选）

### Phase 2 — 基本面增量刷新（T-1）
- [ ] 启动基本面刷新（refresh_days 可调）
- [ ] 跟踪进度与速率（RPM/间隔）
- [ ] 缺失清单输出并归档

### Phase 3 — PIT 快照生成
- [ ] 生成 PIT 周度快照
- [ ] 生成 PIT 基本面快照
- [ ] 运行 PIT 快照校验（缺失日期报告）
- [ ] PIT 基本面 as‑of 校验：确保 `available_date <= snapshot_date`
- [ ] 说明：PIT 基本面快照依赖 PIT 周度快照日期

### Phase 4 — 训练/评分
- [ ] 训练或载入最近可用模型
- [ ] 评分/信号生成并归档

### Phase 5 — 调仓前验收
- [ ] `audit-trade` / `audit-alpha` 覆盖审计
- [ ] 若失败：回退上次周度快照与模型

## Checklist 运行设计（执行逻辑）
- 每周生成一个 checklist 实例（单用户，无需授权）
- 每个步骤可单独重试，失败后自动加入重试队列
- 仅在**重试失败 + 超过最后允许完成时间**后触发回退（上一周快照与模型）
- 步骤状态机：`queued → running → success | failed | skipped | canceled`
- 记录：时间窗、耗时、错误原因、产物路径、回退记录
- 数据更新互斥：涉及数据更新的步骤严禁并发与重复触发
- 互斥实现：PreTrade checklist 锁 + `alpha_fetch`/`pit_*` 细粒度锁协同

## 提醒机制（Telegram）
- 统一使用 Telegram Bot 通知
- UI 支持配置：
  - `telegram_bot_token`
  - `telegram_chat_id`
- 触发时机：
  - 步骤失败（首次失败）
  - 重试失败 → 执行回退
  - Checklist 全部完成（成功/失败摘要）

## UI 展现（概念草案）
- 当前周期 checklist 卡片：进度条 + 关键失败提示
- 步骤列表：状态/耗时/日志入口/重试按钮/回退说明
- 历史 checklist：按周索引，支持展开查看每步详情
- 回退指向：明确显示“回退到上一次成功的 checklist run”
- 数据页摘要：显示本周 checklist 状态与关键告警

## 开发拆解计划（确认版）
### Phase 1 — 数据模型与配置
- 新增表：`pretrade_runs` / `pretrade_steps` / `pretrade_templates` / `pretrade_settings`
- 字段：`window_start/end`、`status`、`retry_count`、`fallback_used`、`artifacts`
- Telegram 配置存储（token/chat_id），UI 侧掩码显示
- 重试配置：最大重试次数/退避参数/最后允许完成时间（deadline）
- 复用现有配置：读取 data 页已存在的 alpha_rate / alpha_fetch / listing TTL
- PreTrade 记录追加 `max_rpm` 与 `min_delay` 的实际取值（便于回溯）

### Phase 2 — 执行器与调度
- Checklist 状态机（串行执行，失败后重试，重试失败触发回退）
- 步骤：交易日历刷新 → 交易日校验 → 价格增量 → Listing TTL → 基本面增量 → PIT 周度 → PIT 基本面 → 训练评分 → 审计验收
- 执行窗口：周六/周日/周一开盘前均可触发
- 互斥规则：全局 checklist 锁 + 数据更新步骤锁（拒绝并发重复触发）
- 交易日历驱动：替换“最新交易日”判定为交易日历（节假日一致）
- 编排复用：直接调用现有数据页 API（bulk sync / PIT / audit），仅新增编排与记录

### Phase 3 — API
- Run/Step：创建/取消/重试/详情/历史查询
- 配置：Telegram 设置与测试发送接口
- 审计：所有运行与步骤写入审计日志
- 聚合接口：返回“本周 checklist 状态摘要”供数据页展示

### Phase 4 — 前端 UI
- PreTrade 控制台：当前周期 + 步骤表 + 历史记录
- 设置面板：Telegram 配置 + 执行窗口提示
- 交互：手动触发、步骤重试、查看日志
- 展示：重试阈值/最后允许完成时间/回退到的成功 run
- 数据页摘要：只展示状态/错误，避免与现有配置重复

### Phase 5 — 测试与验收
- Playwright：流程 UI + 历史记录 + 配置保存
- 后端：重试/回退路径、锁冲突提示
- 通知：Telegram 测试发送（可选真实或模拟）

## 评审建议（对照现有数据页）
- 已具备能力优先复用（listing TTL、增量策略、PIT 周度/基本面入口、速率/进度展示）
- PreTrade 只新增“编排层/历史追踪/回退/通知”，避免重复配置
- 数据页保留配置中心地位，PreTrade 仅显示摘要与运行入口

## QC 对比（扬长避短）
### 可借鉴（QC 优势）
- **数据完整性**：多源冗余、长期历史连续性更强
- **PIT 体系成熟**：财务/因子更新频率与披露时点较完善
- **符号映射**：历史改名/退市映射系统化（避免幸存者偏差）
- **质量监控**：自动修复与异常检测链路更完整

### 本系统优势（可保留）
- **可控性强**：增量/全量可调、策略可视化
- **幂等与唯一性**：文件锁 + 原子写入 + 队列控制
- **成本可控**：Alpha 单源直连，配置透明
- **可观测性**：任务级别速率与进度展示

### 需要补强（短板）
- **基础数据广度**：单源 Alpha 覆盖存在缺口
- **PIT 财务质量**：披露滞后与字段完备性需持续校验
- **历史映射**：改名/退市映射仍需更多人工校验

## 验收标准
- 周一开盘前 PIT 周度快照与基本面快照完整可用
- 价格增量与基本面刷新在时间窗内完成
- 任一流程失败可自动回退上一次周度产物
