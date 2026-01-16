-- Patch: 20260115_add_ib_settings
-- Description: Add IB settings and connection state tables.
-- Impact: Adds ib_settings and ib_connection_state tables.
-- Owner: devops
-- Rollback: DROP TABLE ib_connection_state; DROP TABLE ib_settings;
-- Notes: keep idempotent and record to schema_migrations.

SET @patch_version = '20260115_add_ib_settings';
SET @patch_desc = 'Add IB settings and connection state tables';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

CREATE TABLE IF NOT EXISTS ib_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  host VARCHAR(128) NOT NULL DEFAULT '127.0.0.1',
  port INT NOT NULL DEFAULT 7497,
  client_id INT NOT NULL DEFAULT 1,
  account_id VARCHAR(64) NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  market_data_type VARCHAR(16) NOT NULL DEFAULT 'realtime',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ib_connection_state (
  id INT AUTO_INCREMENT PRIMARY KEY,
  status VARCHAR(32) NOT NULL DEFAULT 'unknown',
  message TEXT NULL,
  last_heartbeat DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS schema_migrations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  version VARCHAR(64) NOT NULL,
  description VARCHAR(255) NOT NULL,
  checksum CHAR(64) NOT NULL,
  applied_by VARCHAR(96) NULL,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_schema_migrations_version (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
