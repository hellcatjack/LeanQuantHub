-- 变更说明: 为 trade_fills 增加 currency/exchange/raw_payload/updated_at 字段，补齐成交元信息。
-- 影响范围: trade_fills
-- 回滚指引: ALTER TABLE trade_fills DROP COLUMN currency; ALTER TABLE trade_fills DROP COLUMN exchange; ALTER TABLE trade_fills DROP COLUMN raw_payload; ALTER TABLE trade_fills DROP COLUMN updated_at;

-- currency
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'trade_fills'
  AND COLUMN_NAME = 'currency';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE trade_fills ADD COLUMN currency VARCHAR(16) NULL',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- exchange
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'trade_fills'
  AND COLUMN_NAME = 'exchange';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE trade_fills ADD COLUMN exchange VARCHAR(32) NULL',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- raw_payload
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'trade_fills'
  AND COLUMN_NAME = 'raw_payload';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE trade_fills ADD COLUMN raw_payload JSON NULL',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- updated_at
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'trade_fills'
  AND COLUMN_NAME = 'updated_at';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE trade_fills ADD COLUMN updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
