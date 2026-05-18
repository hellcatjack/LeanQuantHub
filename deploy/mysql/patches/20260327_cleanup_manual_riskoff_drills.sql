-- 变更说明: 清理 2026-03-27 手工 paper risk_off dry-run 演练生成的临时记录。
-- 影响范围: trade_orders, trade_runs, decision_snapshots。
-- 回滚指引: 本脚本为一次性数据清理，回滚需从数据库备份恢复；脚本本身保证按指定 ID 幂等删除，不影响其他记录。

SET @run_ids := '1159,1160,1161';
SET @snapshot_ids := '99,100,101';

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_orders'
);
SET @sql := IF(
  @table_exists > 0,
  "DELETE FROM trade_orders WHERE run_id IN (1159,1160,1161)",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_runs'
);
SET @sql := IF(
  @table_exists > 0,
  "DELETE FROM trade_runs
   WHERE id IN (1159,1160,1161)
     AND JSON_EXTRACT(params, '$.manual_drill') = true",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'decision_snapshots'
);
SET @sql := IF(
  @table_exists > 0,
  "DELETE FROM decision_snapshots
   WHERE id IN (99,100,101)
     AND message IN (
       'manual_paper_riskoff_dry_run:defensive_sgov',
       'manual_paper_riskoff_dry_run:benchmark_spy',
       'manual_paper_riskoff_dry_run:cash'
     )",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260327_cleanup_manual_riskoff_drills',
  'cleanup manual paper risk-off dry-run records',
  SHA2('20260327_cleanup_manual_riskoff_drills', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260327_cleanup_manual_riskoff_drills'
);
