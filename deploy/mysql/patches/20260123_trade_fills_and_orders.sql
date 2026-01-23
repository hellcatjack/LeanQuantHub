-- 变更说明：新增 trade_fills 表，扩展 trade_orders 字段用于 IB 回报映射
-- 影响范围：trade_orders / trade_fills
-- 回滚指引：删除新增字段与 trade_fills 表

-- 1) trade_fills
CREATE TABLE IF NOT EXISTS trade_fills (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  exec_id VARCHAR(64) NOT NULL,
  filled_qty DOUBLE NOT NULL,
  price DOUBLE NOT NULL,
  commission DOUBLE NULL,
  trade_time DATETIME NULL,
  currency VARCHAR(8) NULL,
  exchange VARCHAR(32) NULL,
  raw_payload JSON NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_fills_exec_id (exec_id),
  KEY idx_trade_fills_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) trade_orders columns (check information_schema before ALTER)
-- ib_order_id
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'ib_order_id'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN ib_order_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ib_perm_id
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'ib_perm_id'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN ib_perm_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- last_status_ts
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'last_status_ts'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN last_status_ts DATETIME NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- rejected_reason
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'rejected_reason'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN rejected_reason TEXT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
