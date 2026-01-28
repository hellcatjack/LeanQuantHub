-- 变更说明：新增 trade_order_client_id_seq 用于生成唯一 client_order_id suffix
-- 影响范围：新增表，不影响现有数据
-- 回滚指引：DROP TABLE IF EXISTS trade_order_client_id_seq;

CREATE TABLE IF NOT EXISTS trade_order_client_id_seq (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
