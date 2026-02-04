-- 变更说明: 为 trade_runs 增加停滞进度字段
-- 影响范围: trade_runs
-- 回滚指引: ALTER TABLE trade_runs DROP COLUMN last_progress_at, DROP COLUMN progress_stage, DROP COLUMN progress_reason, DROP COLUMN stalled_at, DROP COLUMN stalled_reason;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_runs'
    AND column_name = 'last_progress_at'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE trade_runs ADD COLUMN last_progress_at DATETIME NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_runs'
    AND column_name = 'progress_stage'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE trade_runs ADD COLUMN progress_stage VARCHAR(64) NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_runs'
    AND column_name = 'progress_reason'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE trade_runs ADD COLUMN progress_reason TEXT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_runs'
    AND column_name = 'stalled_at'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE trade_runs ADD COLUMN stalled_at DATETIME NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_runs'
    AND column_name = 'stalled_reason'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE trade_runs ADD COLUMN stalled_reason TEXT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260204_trade_run_stalled',
  'add trade_runs progress + stalled fields',
  SHA2('20260204_trade_run_stalled', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260204_trade_run_stalled'
);
