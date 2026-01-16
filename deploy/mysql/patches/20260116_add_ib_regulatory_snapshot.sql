-- Patch: 20260116_add_ib_regulatory_snapshot
-- Description: Add use_regulatory_snapshot flag to ib_settings.
-- Impact: Adds ib_settings.use_regulatory_snapshot for regulatory snapshot toggle.
-- Rollback: ALTER TABLE ib_settings DROP COLUMN use_regulatory_snapshot;

SET @patch_version = '20260116_add_ib_regulatory_snapshot';
SET @patch_desc = 'Add regulatory snapshot toggle to ib_settings';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

SET @column_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'ib_settings'
    AND COLUMN_NAME = 'use_regulatory_snapshot'
);

SET @ddl = IF(
  @column_exists = 0,
  'ALTER TABLE ib_settings ADD COLUMN use_regulatory_snapshot TINYINT(1) NOT NULL DEFAULT 0 AFTER api_mode',
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
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);
