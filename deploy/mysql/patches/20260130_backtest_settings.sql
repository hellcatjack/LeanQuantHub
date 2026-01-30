-- 变更说明：新增 backtest_settings 用于保存回测默认初始资金与手续费
-- 影响范围：新增表，不影响现有数据
-- 回滚指引：DROP TABLE IF EXISTS backtest_settings;

CREATE TABLE IF NOT EXISTS backtest_settings (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  default_initial_cash DOUBLE NOT NULL DEFAULT 30000,
  default_fee_bps DOUBLE NOT NULL DEFAULT 10.0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
