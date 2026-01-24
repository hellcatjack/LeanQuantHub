-- 变更说明: 为 trade_settings 增加 execution_data_source 字段，用于记录下单执行来源（ib/mock 等）。
-- 影响范围: trade_settings
-- 回滚指引: ALTER TABLE trade_settings DROP COLUMN execution_data_source;

SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'trade_settings'
  AND COLUMN_NAME = 'execution_data_source';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE trade_settings ADD COLUMN execution_data_source VARCHAR(32) NOT NULL DEFAULT ''ib''',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
