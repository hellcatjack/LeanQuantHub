-- 变更说明: 为 trade_settings 增加 auto_recovery 配置
-- 影响范围: trade_settings
-- 回滚指引: ALTER TABLE trade_settings DROP COLUMN auto_recovery;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_settings'
    AND column_name = 'auto_recovery'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE trade_settings ADD COLUMN auto_recovery JSON NULL AFTER execution_data_source',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260203_trade_settings_auto_recovery',
  'add trade_settings.auto_recovery',
  SHA2('20260203_trade_settings_auto_recovery', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260203_trade_settings_auto_recovery'
);
