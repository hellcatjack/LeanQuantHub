-- 变更说明：新增 lean_executor_pool 与 lean_executor_events，用于记录常驻执行器池与事件
-- 影响范围：新增表，不影响现有数据
-- 回滚指引：DROP TABLE IF EXISTS lean_executor_events; DROP TABLE IF EXISTS lean_executor_pool;

CREATE TABLE IF NOT EXISTS lean_executor_pool (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  role VARCHAR(16) NOT NULL DEFAULT 'worker',
  client_id INT NOT NULL,
  pid INT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'unknown',
  last_heartbeat TIMESTAMP NULL,
  last_order_at TIMESTAMP NULL,
  output_dir VARCHAR(255) NULL,
  last_error TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_lean_executor_pool_mode_client (mode, client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS lean_executor_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_type VARCHAR(32) NOT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  client_id INT NULL,
  detail JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_lean_executor_events_mode_time (mode, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
