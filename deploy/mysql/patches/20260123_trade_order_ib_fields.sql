-- Patch: 20260123_trade_order_ib_fields
-- Description: Add IB execution fields to trade_orders/trade_fills for real execution tracking.
-- Impact: trade_orders, trade_fills
-- Rollback: ALTER TABLE drop new columns (ib_order_id, ib_perm_id, last_status_ts, rejected_reason, exec_id, currency, exchange, raw_payload, updated_at).
-- Notes: Idempotent DDL using IF NOT EXISTS.

SET @patch_version = '20260123_trade_order_ib_fields';
SET @patch_desc = 'Add IB execution fields to trade_orders/trade_fills';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

ALTER TABLE trade_orders
  ADD COLUMN IF NOT EXISTS ib_order_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS ib_perm_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS last_status_ts DATETIME NULL,
  ADD COLUMN IF NOT EXISTS rejected_reason TEXT NULL;

ALTER TABLE trade_fills
  ADD COLUMN IF NOT EXISTS exec_id VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS currency VARCHAR(16) NULL,
  ADD COLUMN IF NOT EXISTS exchange VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS raw_payload JSON NULL,
  ADD COLUMN IF NOT EXISTS updated_at DATETIME NULL;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
