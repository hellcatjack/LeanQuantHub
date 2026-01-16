-- Patch: 20260115_add_ib_contract_cache
-- Description: Add IB contract cache table for conId lookup.
-- Impact: Adds ib_contract_cache table for symbol->conId mapping.
-- Owner: devops
-- Rollback: DROP TABLE ib_contract_cache;
-- Notes: keep idempotent and record to schema_migrations.

SET @patch_version = '20260115_add_ib_contract_cache';
SET @patch_desc = 'Add IB contract cache table';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

CREATE TABLE IF NOT EXISTS ib_contract_cache (
  id INT AUTO_INCREMENT PRIMARY KEY,
  symbol VARCHAR(32) NOT NULL,
  sec_type VARCHAR(16) NOT NULL DEFAULT 'STK',
  exchange VARCHAR(32) NOT NULL DEFAULT 'SMART',
  primary_exchange VARCHAR(32) NULL,
  currency VARCHAR(8) NOT NULL DEFAULT 'USD',
  con_id INT NOT NULL,
  local_symbol VARCHAR(32) NULL,
  multiplier VARCHAR(16) NULL,
  detail JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ib_contract_cache (symbol, sec_type, exchange, currency)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
