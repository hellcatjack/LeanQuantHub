-- trade_execution_tables
-- 变更说明：补齐实盘交易相关表 + trade_settings.execution_data_source
-- 影响范围：trade_runs / trade_orders / trade_fills / trade_settings
-- 回滚指引：删除新增表/列（仅在确认无数据时执行）

-- trade_runs
CREATE TABLE IF NOT EXISTS trade_runs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  project_id BIGINT NOT NULL,
  decision_snapshot_id BIGINT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  params JSON NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_trade_runs_project_id (project_id),
  INDEX idx_trade_runs_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- trade_orders
CREATE TABLE IF NOT EXISTS trade_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id BIGINT NULL,
  client_order_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  side VARCHAR(8) NOT NULL,
  quantity DOUBLE NOT NULL,
  order_type VARCHAR(16) NOT NULL DEFAULT 'MKT',
  limit_price DOUBLE NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'NEW',
  filled_quantity DOUBLE NOT NULL DEFAULT 0,
  avg_fill_price DOUBLE NULL,
  ib_order_id BIGINT NULL,
  ib_perm_id BIGINT NULL,
  last_status_ts DATETIME NULL,
  rejected_reason TEXT NULL,
  params JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_order_client_id (client_order_id),
  INDEX idx_trade_orders_run_id (run_id),
  INDEX idx_trade_orders_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- trade_fills
CREATE TABLE IF NOT EXISTS trade_fills (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_id BIGINT NOT NULL,
  fill_quantity DOUBLE NOT NULL,
  fill_price DOUBLE NOT NULL,
  commission DOUBLE NULL,
  fill_time DATETIME NULL,
  exec_id VARCHAR(64) NULL,
  currency VARCHAR(16) NULL,
  exchange VARCHAR(32) NULL,
  raw_payload JSON NULL,
  params JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_trade_fills_order_id (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- trade_settings.execution_data_source
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_settings'
    AND COLUMN_NAME = 'execution_data_source'
);
SET @sql := IF(@exists = 0,
  'ALTER TABLE trade_settings ADD COLUMN execution_data_source VARCHAR(16) NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
