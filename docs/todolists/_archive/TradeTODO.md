  方案设计（周频模拟盘/实盘数据获取 Workflow）

  本文件会根据系统演进持续更新：每完成或调整一项能力，需同步刷新对应状态与验收标准。

  一、当前系统的数据获取方式（现状梳理）

  - 价格数据：data_root/curated_adjusted（回测/训练默认用复权数据）
  - Universe & 生命周期：data_root/universe/alpha_symbol_life.csv
  - PIT 周度快照：
      - 生成脚本：scripts/build_pit_weekly_snapshots.py
      - 输出目录：data_root/universe/pit_weekly/pit_YYYYMMDD.csv
      - 校验修复：scripts/validate_pit_weekly_snapshots.py（可重写文件）
  - 基本面抓取（Alpha）：
      - 脚本：scripts/fetch_alpha_fundamentals.py
      - 输出：data_root/fundamentals/alpha/<SYMBOL>/*.json + fundamentals_status.csv
  - PIT 基本面快照：
      - 脚本：scripts/build_pit_fundamentals_snapshots.py
      - 输出：data_root/factors/pit_weekly_fundamentals/pit_fundamentals_YYYYMMDD.csv
  - Alpha 抓取限速与唯一性（已落地）
      - 运行时速率配置：data_root/config/alpha_rate.json（可动态调整）
      - 全局抓取锁：data_root/locks/alpha_fetch.lock（文件锁）
      - 队列唯一性：data_root/locks/data_sync_queue.lock（文件锁）
      - 限速重试：Note/Information 视为可重试
      - 原子写入：临时文件 + rename
  - 覆盖审计（已落地）
      - 接口：POST /api/datasets/actions/audit-alpha / audit-trade
      - 输出：artifacts/data_audit/alpha_YYYYMMDD_HHMMSS/*.csv
             artifacts/data_audit/trade_YYYYMMDD_HHMMSS/*.csv

  二、Alpha 能力与“周频模拟盘/实盘”所需数据对照

  - 价格/执行（周频可用）
      - TIME_SERIES_DAILY_ADJUSTED：用于周度回测/信号
      - TIME_SERIES_INTRADAY / GLOBAL_QUOTE：用于周一开盘的近似执行价（实盘或模拟盘）
  - 公司行为
      - DIVIDENDS, SPLITS（或直接使用 ADJUSTED 序列）
  - 基本面/PIT
      - OVERVIEW, INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW, EARNINGS
  - 交易日历
      - 以 SPY 交易日构建（系统已支持）
  - 限制
      - Alpha 不提供超低延迟行情；实盘仅能做“低频/日内近似”，需谨慎使用

  三、建议的周频模拟盘/实盘数据 Workflow

  A. 日频更新（T+1，交易日收盘后）

  1. 价格更新
      - 拉取/刷新日线：TIME_SERIES_DAILY_ADJUSTED
      - 存入 curated_adjusted（或等效缓存层）
  2. 异常扫描（可选）
      - 运行价格质量扫描（缺失/异常）
  3. Listing 状态刷新（低频）
      - LISTING_STATUS 每周或每月更新生命周期表

  B. 周度调仓前（周一开盘前）

  1. PIT 周度快照生成
      - 输入：curated_adjusted + alpha_symbol_life.csv
      - 输出：universe/pit_weekly/pit_YYYYMMDD.csv
  2. PIT 基本面快照生成
      - 先增量抓取基本面（Alpha）
      - 再生成 PIT 基本面快照（factors/pit_weekly_fundamentals）

  C. 周一开盘（模拟盘/实盘）

  1. 执行价近似
      - 优先用 TIME_SERIES_INTRADAY（5min）取开盘价附近
      - 限速时回退 GLOBAL_QUOTE 或上一日 close + 滑点模型
  2. 生成并记录交易指令与回放

  四、效率与幂等性设计（重点）

  效率优化

  - 增量抓取：
      - 基本面按 refresh_days，仅更新过期文件
  - 限速调度：
      - min_delay_seconds + rate_limit_sleep + rate_limit_retries
  - 批次队列：
      - symbol 队列分块，避免单次超长任务
  - 缓存复用：
      - PIT 快照生成从现有缓存读取，不重复解析

  幂等性保障

  - 输出按日期命名：pit_YYYYMMDD.csv / pit_fundamentals_YYYYMMDD.csv
  - 写入原子性：临时文件 + rename（现有 PIT/Fundamental 进度写入已有类似机制）
  - 重复运行可覆写：同日期文件重复生成结果一致
  - 加锁避免并发覆盖：同一 DATA_ROOT 下同类任务串行运行
  - 校验修复幂等：validate_pit_weekly_snapshots.py --fix 可重复运行且结果稳定

  五、完整闭环（周频模拟盘/实盘）

  - 日线更新 → PIT 周度快照 → 基本面增量抓取 → PIT 基本面快照
    → 模型打分/信号 → 周一开盘执行 → 记录与回放
    → 下周循环

目前计划暂缓开发 C. 周一开盘（模拟盘/实盘） 的相关功能，其他开发内容按方案进行breakdown并生成详细的todolist,其中数据获取要考虑系统当前有无遗漏，如有遗漏需一并补齐，且严格注意幂等性，接口获取要能精确控速，
  ALPHA的接口目前最高支持75次每分钟（作为配置项），程序需要支持实时调整访问间隔，并且保证被限速的请求能精确重试。从数据源获取数据的代码要注意运行的唯一性，本项目可能会在同一个服务器同时启动多个副本，要绝对
  杜绝并发多个数据抓取事件。

  详细 TODOLIST（不含 C. 周一开盘）

  Phase 0 — 现状与遗漏审计（必做）

  1. 价格数据覆盖审计（curated_adjusted）
      - 对比 alpha_symbol_life.csv 与 curated_adjusted 文件集合，输出缺失清单
      - 目的：确认是否存在“有生命周期但无价格”的标的
      - 验收：输出缺失清单（CSV/MD）+ 缺失数量统计
      - 状态：已完成（audit-trade 输出 price_missing_symbols.csv）
  2. PIT 周度快照完整性审计
      - 检查 data/universe/pit_weekly 连续性（交易周无断档）
      - 验收：连续周覆盖率报告（缺失周与原因）
      - 状态：已完成（audit-trade 输出 pit_weekly_missing_dates.csv）
  3. 基本面缓存覆盖审计（fundamentals/alpha）
      - 对比 PIT 周度快照中的 symbol 与 fundamentals/alpha/<symbol> 缓存
      - 验收：缺失基本面清单（含 symbol、原因、最后更新时间）
      - 状态：已完成（audit-trade 输出 fundamentals_missing_symbols.csv）
  4. PIT 基本面快照覆盖审计
      - 检查 data/factors/pit_weekly_fundamentals 是否与 PIT 周度快照日期一致
      - 验收：缺失快照日期清单
      - 状态：已完成（audit-trade 输出 pit_fundamentals_missing_dates.csv）

  ———

  Phase 1 — 数据获取唯一性（跨副本绝对互斥）
  5) 全局数据抓取锁（分布式/跨进程）

  - 方案：文件锁（data_root/locks/*.lock）
  - 必须包含：job_key、owner、heartbeat、ttl
  - 验收：同一时间仅允许一个 PIT/基本面抓取任务；多副本启动时仍能阻断并发
  - 状态：已完成（文件锁 + owner/heartbeat/ttl 已落地）

  6. 锁的自动恢复机制
      - TTL 到期自动释放；异常退出清理
      - 验收：异常中断后可自动恢复任务，不需要人工干预
      - 状态：已完成（过期心跳在重试时自动接管，异常退出自动释放）

  ———

  Phase 2 — 限速与幂等（Alpha 75 RPM 可配置）
  7) 速率配置统一化（全局配置项）

  - 新增配置项：data_root/config/alpha_rate.json
  - 自动换算最小间隔：min_delay = 60 / ALPHA_MAX_RPM
  - 支持运行时实时调整（无需重启）
  - 验收：UI/配置更新后 1 分钟内生效，实际请求频率精确贴合
  - 状态：已完成（配置文件 + API 已落地）

  8. 精确限速重试机制（可重复、可恢复）
      - 遇到 Note/Information（限速提示）判定为“可重试”
      - 重试应回到队列尾部，保留重试次数与原因
      - 验收：限速触发时不会丢失标的；最终可完整覆盖
      - 状态：已完成（重试回队列尾部 + 原因/次数追踪落地）
  9. 幂等写入策略
      - fundamentals/alpha 写入采用“临时文件 + rename”
      - PIT 快照按日期覆盖写入（重复运行结果一致）
      - 验收：重复跑同一任务不会产生重复/脏数据
      - 状态：已完成（PIT 快照/日历/校验修复均采用临时文件 + rename）

  ———

  Phase 3 — 数据生成流程（可回放、可重跑）
  10) Listing/生命周期更新流程固化

  - LISTING_STATUS → alpha_symbol_life.csv
      - 保留历史快照（版本化）
      - 验收：生命周期表可回溯版本
      - 状态：已完成（刷新时落盘 listing_versions 快照）

  11. PIT 周度快照生成流程固化

  - 输入：交易日历 + symbol_life + curated_adjusted
  - 输出：pit_weekly（按日期写入）
      - 校验：validate_pit_weekly_snapshots.py --fix
      - 验收：快照连续且日期一致
      - 状态：已完成（任务入口已串联 build + validate）

  12. 基本面增量抓取 + PIT 基本面快照

      - 增量抓取（按 refresh_days）
      - PIT 快照仅对已有 PIT 周度快照日期生成
      - 验收：快照覆盖率 ≥ 预期阈值，缺失可追踪
      - 状态：已完成（覆盖率追踪+缺失清单输出+缺失回补已串联）

  ———

  Phase 4 — 观测与可控性
  13) 实时速率展示（RPM 实际值）

  - UI 显示“目标 RPM / 实际 RPM / 当前间隔”
  - 验收：可验证控速生效
  - 状态：已完成（任务速度卡片展示目标 RPM/实际 RPM/当前间隔）

  14. 任务级进度与审计

  - 每个任务输出进度、失败原因、重试次数
  - 验收：无需查日志即可定位失败
  - 状态：已完成（PIT 周度/基本面进度已落地；数据同步已展示重试次数/原因/耗时/阶段/阶段进度）

  ———

  Phase 5 — 运行规范（生产稳定性）
  15) 运行策略

  - 数据抓取任务只允许单实例
  - 生产/研发共用 DATA_ROOT 时必须强制互斥
  - 验收：多副本启动时只有一个获得锁并执行
  - 状态：已完成（数据同步队列改为统一走 data_sync_queue 锁，避免多副本并发抓取）
