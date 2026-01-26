-- 变更说明: 为 pretrade_settings 增加 Lean Bridge 门禁 TTL 配置字段。
-- 影响范围: pretrade_settings
-- 回滚指引: ALTER TABLE pretrade_settings DROP COLUMN bridge_heartbeat_ttl_seconds; ALTER TABLE pretrade_settings DROP COLUMN bridge_account_ttl_seconds; ALTER TABLE pretrade_settings DROP COLUMN bridge_positions_ttl_seconds; ALTER TABLE pretrade_settings DROP COLUMN bridge_quotes_ttl_seconds;

SET @patch_version = '20260126_pretrade_bridge_gate';
SET @patch_desc = 'Add pretrade bridge gate ttl settings';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

-- bridge_heartbeat_ttl_seconds
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'pretrade_settings'
  AND COLUMN_NAME = 'bridge_heartbeat_ttl_seconds';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE pretrade_settings ADD COLUMN bridge_heartbeat_ttl_seconds INT NOT NULL DEFAULT 60',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- bridge_account_ttl_seconds
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'pretrade_settings'
  AND COLUMN_NAME = 'bridge_account_ttl_seconds';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE pretrade_settings ADD COLUMN bridge_account_ttl_seconds INT NOT NULL DEFAULT 300',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- bridge_positions_ttl_seconds
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'pretrade_settings'
  AND COLUMN_NAME = 'bridge_positions_ttl_seconds';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE pretrade_settings ADD COLUMN bridge_positions_ttl_seconds INT NOT NULL DEFAULT 300',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- bridge_quotes_ttl_seconds
SELECT COUNT(*) INTO @col_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'pretrade_settings'
  AND COLUMN_NAME = 'bridge_quotes_ttl_seconds';

SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE pretrade_settings ADD COLUMN bridge_quotes_ttl_seconds INT NOT NULL DEFAULT 60',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE pretrade_settings
  SET bridge_heartbeat_ttl_seconds = 60
  WHERE bridge_heartbeat_ttl_seconds IS NULL;

UPDATE pretrade_settings
  SET bridge_account_ttl_seconds = 300
  WHERE bridge_account_ttl_seconds IS NULL;

UPDATE pretrade_settings
  SET bridge_positions_ttl_seconds = 300
  WHERE bridge_positions_ttl_seconds IS NULL;

UPDATE pretrade_settings
  SET bridge_quotes_ttl_seconds = 60
  WHERE bridge_quotes_ttl_seconds IS NULL;

-- schema_migrations (if exists)
SELECT COUNT(*) INTO @schema_exists
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'schema_migrations';

SET @ddl = IF(
  @schema_exists = 1,
  'INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by) VALUES (\'20260126_pretrade_bridge_gate\', \'Add pretrade bridge gate ttl settings\', SHA2(\'20260126_pretrade_bridge_gate:Add pretrade bridge gate ttl settings\', 256), CURRENT_USER())',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

COMMIT;
