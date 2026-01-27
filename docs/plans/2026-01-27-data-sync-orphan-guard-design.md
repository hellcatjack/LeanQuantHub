# 数据同步孤儿任务自动识别与回收设计

## 背景
全量同步（bulk_sync）在 `syncing` 阶段依赖 `data_sync_jobs` 的 `pending/running` 统计收敛。当历史运行中的 `DataSyncJob` 因进程中断未落盘 `ended_at` 时，会导致 bulk_job 永久停留在 `syncing`。

本设计目标是在 **不以时间阈值** 为唯一依据的前提下，通过“队列状态 + 文件落地证据”的联合信号自动识别孤儿任务，并安全回收，解除 PreTrade 阻塞。

## 判定信号（A+B 联合）
A) bulk_job 窗口内仍存在 `DataSyncJob.status=running`，且 `pending=0`。
B) 同步队列处于空闲（`SYNC_QUEUE_RUNNING=false` 且 `data_sync_queue` 锁可获取），判定队列无活跃执行。

满足 A+B 后，对每个候选 job 做“落盘证据”验证：
- `curated/{dataset_id}_*.csv` 或 `curated_adjusted/{dataset_id}_*.csv` 存在
- 或 `lean/equity/usa/daily/{symbol}.zip` / `lean_adjusted` 存在
- 或 `curated_versions/{dataset_id}_*/*.csv` 最新快照存在

任一证据成立，即视为“数据产出已落地”，允许回收该 running 任务。

## 实现流程
1. 在 `backend/app/routes/datasets.py::_run_bulk_sync_job` 的 `syncing` 循环中，增加 `evaluate_orphaned_sync_jobs(session, job)`。
2. 函数基于 bulk_job 窗口筛选 `status=running` 的 `DataSyncJob`。
3. 检查队列是否空闲（`SYNC_QUEUE_RUNNING` + `data_sync_queue` 锁），非空闲直接返回（不回收）。
4. 对候选 job 执行文件证据检查，满足条件则：
   - `status=failed`，`message` 追加 `orphaned_worker`，写入 `ended_at`。
   - 写审计事件 `data.sync.orphaned`，记录 job_id/dataset_id/source_path/证据路径。
5. 返回被回收的 job 数量，供 bulk_job 统计更新。

## 配置与开关
新增配置文件：`/data/share/stock/data/config/data_sync_orphan_guard.json`
- `enabled`（bool，默认 true）
- `dry_run`（bool，默认 false）
- `evidence_required`（bool，默认 true）

支持“仅观察”模式：`dry_run=true` 时不修改 DB，仅记录审计事件与候选清单。

## 审计与回滚
- 所有回收动作记录审计事件 `data.sync.orphaned`，附证据路径与状态快照。
- 回滚方式：根据审计记录手工将指定 job 标记回 `success` 或重新发起同步任务。

## 测试计划
1. 单元/脚本验证：构造 `running` + `pending=0` + 队列空闲 + 文件存在，验证回收；反例不回收。
2. 集成验证：在项目 16 的 PreTrade 中触发 `price_incremental`，制造队列空闲但 running 存在的场景，验证 bulk_job 可完成。

## 影响范围
- 仅在 bulk_sync 的 `syncing` 阶段生效，不影响单个手工 sync。
- 依赖文件落地证据，避免误杀真实运行任务。
