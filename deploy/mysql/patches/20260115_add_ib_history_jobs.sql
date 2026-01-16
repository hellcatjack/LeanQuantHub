-- Patch: 20260115_add_ib_history_jobs
-- Description: Add IB history job table for batch historical fetch.
-- Impact: Adds ib_history_jobs table to track IB historical data jobs.
-- Owner: devops
-- Rollback: DROP TABLE ib_history_jobs;
-- Notes: keep idempotent and record to schema_migrations.

SET @patch_version = '20260115_add_ib_history_jobs';
SET @patch_desc = 'Add IB history job table';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

CREATE TABLE IF NOT EXISTS ib_history_jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  params JSON NULL,
  total_symbols INT NULL,
  processed_symbols INT NULL,
  success_symbols INT NULL,
  failed_symbols INT NULL,
  log_path VARCHAR(255) NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
