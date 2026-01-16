-- Patch: 20260116_add_ib_api_mode
-- Description: Add api_mode column to ib_settings for IB/mock adapter selection.
-- Impact: Adds ib_settings.api_mode with default 'ib'.
-- Rollback: ALTER TABLE ib_settings DROP COLUMN api_mode;

SET @patch_version = '20260116_add_ib_api_mode';
SET @patch_desc = 'Add api_mode to ib_settings';
SET @patch_checksum = SHA2('20260116_add_ib_api_mode', 256);

SET @column_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'ib_settings'
    AND COLUMN_NAME = 'api_mode'
);

SET @ddl = IF(
  @column_exists = 0,
  'ALTER TABLE ib_settings ADD COLUMN api_mode VARCHAR(16) NOT NULL DEFAULT ''ib'' AFTER market_data_type',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS schema_migrations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  version VARCHAR(64) NOT NULL,
  description VARCHAR(255) NOT NULL,
  checksum VARCHAR(128) NOT NULL,
  applied_by VARCHAR(64) NOT NULL,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_schema_migrations_version (version)
);

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, 'codex');
