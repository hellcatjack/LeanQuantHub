-- Patch: 20260123_ib_connection_state_degraded_since
-- Description: Add degraded_since to ib_connection_state for IB health tracking.
-- Impact: ib_connection_state
-- Rollback: ALTER TABLE ib_connection_state DROP COLUMN degraded_since;
-- Notes: Idempotent DDL using IF NOT EXISTS.

SET @patch_version = '20260123_ib_connection_state_degraded_since';
SET @patch_desc = 'Add degraded_since to ib_connection_state';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

SET @col_exists = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'ib_connection_state'
    AND column_name = 'degraded_since'
);
SET @ddl = IF(
  @col_exists = 0,
  'ALTER TABLE ib_connection_state ADD COLUMN degraded_since DATETIME NULL',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
