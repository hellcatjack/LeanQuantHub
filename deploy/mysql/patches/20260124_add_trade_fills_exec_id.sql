-- 变更说明: 为 trade_fills 增加 exec_id 字段，用于记录成交回报的执行编号。
-- 影响范围: trade_fills
-- 回滚指引: ALTER TABLE trade_fills DROP COLUMN exec_id;

SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'trade_fills'
  AND COLUMN_NAME = 'exec_id';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE trade_fills ADD COLUMN exec_id VARCHAR(64) NULL',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
