-- Patch: 20260128_ib_client_id_pool
-- Description: Add ib_client_id_pool table for client id leases.
-- Impact: Adds ib_client_id_pool table used by direct order execution.
-- Owner: devops
-- Rollback: DROP TABLE ib_client_id_pool;
-- Notes: keep idempotent and record to schema_migrations.

SET @patch_version = '20260128_ib_client_id_pool';
SET @patch_desc = 'Add ib_client_id_pool table for client id leases';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

CREATE TABLE IF NOT EXISTS ib_client_id_pool (
  client_id INT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'free',
  order_id INT NULL,
  pid INT NULL,
  output_dir VARCHAR(255) NULL,
  lease_token VARCHAR(64) NULL,
  acquired_at DATETIME NULL,
  last_heartbeat DATETIME NULL,
  released_at DATETIME NULL,
  release_reason VARCHAR(255) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
