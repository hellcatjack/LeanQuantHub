-- Patch: 20260115_add_trade_orders
-- Description: Add trade run/order/fill tables for IB execution.
-- Impact: Adds trade_runs, trade_orders, trade_fills tables.
-- Owner: devops
-- Rollback: DROP TABLE trade_fills; DROP TABLE trade_orders; DROP TABLE trade_runs;
-- Notes: keep idempotent and record to schema_migrations.

SET @patch_version = '20260115_add_trade_orders';
SET @patch_desc = 'Add trade run/order/fill tables';
SET @patch_checksum = SHA2(CONCAT(@patch_version, ':', @patch_desc), 256);
SET @patch_user = CURRENT_USER();

START TRANSACTION;

CREATE TABLE IF NOT EXISTS trade_runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  decision_snapshot_id INT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  params JSON NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_trade_runs_project_id (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS trade_orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  run_id INT NULL,
  client_order_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  side VARCHAR(8) NOT NULL,
  quantity DOUBLE NOT NULL,
  order_type VARCHAR(16) NOT NULL DEFAULT 'MKT',
  limit_price DOUBLE NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'NEW',
  filled_quantity DOUBLE NOT NULL DEFAULT 0,
  avg_fill_price DOUBLE NULL,
  params JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_order_client_id (client_order_id),
  INDEX idx_trade_orders_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS trade_fills (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  fill_quantity DOUBLE NOT NULL,
  fill_price DOUBLE NOT NULL,
  commission DOUBLE NULL,
  fill_time DATETIME NULL,
  params JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_trade_fills_order_id (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, @patch_checksum, @patch_user);

COMMIT;
