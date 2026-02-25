-- Patch: 20260220_add_ib_workstation_type
-- Description: Add workstation_type to ib_settings for TWS/Gateway selection.
-- Impact: Adds ib_settings.workstation_type and backfills common gateway ports.
-- Owner: codex
-- Rollback: ALTER TABLE ib_settings DROP COLUMN workstation_type;

SET @patch_version = '20260220_add_ib_workstation_type';
SET @patch_desc = 'Add workstation_type to ib_settings';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

SET @column_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'ib_settings'
    AND COLUMN_NAME = 'workstation_type'
);

SET @ddl = IF(
  @column_exists = 0,
  'ALTER TABLE ib_settings ADD COLUMN workstation_type VARCHAR(16) NOT NULL DEFAULT ''tws'' AFTER port',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Common IB Gateway defaults: 4001 (live) / 4002 (paper).
UPDATE ib_settings
SET workstation_type = 'gateway'
WHERE workstation_type = 'tws'
  AND port IN (4001, 4002);

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
