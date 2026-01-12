Phase 1 — 数据获取唯一性（锁/互斥）

- [x] T1 JobLock 心跳/TTL：已验证心跳更新与释放（data_root/locks）
- [x] T2 bulk_sync 锁生效：持锁时全量抓取任务 blocked 且写入 message
- [x] T3 alpha_fetch 锁生效：持锁时 listing/fundamentals 抓取脚本直接失败（alpha_lock_busy）

Phase 2 — 限速/重试/幂等

- [x] T4 速率配置实时生效：更新 alpha_rate.json → /sync-jobs/speed 有效间隔变化 → 还原
- [x] T5 重试入队：_schedule_retry 追加重试次数、next_retry_at、created_at 前移
- [x] T6 同步任务阶段进度：写入 stage+progress → UI 显示阶段百分比

Phase 3 — 数据生成流程

- [x] T7 listing 版本化：已补跑真实 Alpha 网络请求，listing_versions 新文件落盘
- [x] T8 PIT 周度快照校验：validate 脚本写 summary（只读/不修复）
- [x] T9 PIT 基本面快照小窗：生成快照 + 缺失清单 + 进度输出

Phase 4 — 观测与可控性

- [x] T10 PIT 进度 API：weekly/fundamental progress 均返回有效响应
- [x] T11 UI 可视化：数据页速度卡/阶段进度/refresh_days 输入已可见（Playwright）

Phase 5 — 运行规范（多副本互斥）

- [x] T12 alpha_fetch 单实例：持锁时 fundamentals/listing 抓取任务无法并发启动
