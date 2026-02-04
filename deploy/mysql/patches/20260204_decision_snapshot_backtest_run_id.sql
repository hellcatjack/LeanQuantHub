-- [DESCRIPTION] add backtest_run_id to decision_snapshots
-- [IMPACT] allow decision snapshot to reference a backtest run
-- [ROLLBACK] manually drop column and index if needed

SET @col_exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'decision_snapshots'
    AND COLUMN_NAME = 'backtest_run_id'
);
SET @sql = IF(@col_exists = 0,
  'ALTER TABLE decision_snapshots ADD COLUMN backtest_run_id INT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'decision_snapshots'
    AND INDEX_NAME = 'idx_decision_snapshots_backtest_run_id'
);
SET @sql = IF(@idx_exists = 0,
  'CREATE INDEX idx_decision_snapshots_backtest_run_id ON decision_snapshots (backtest_run_id)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
