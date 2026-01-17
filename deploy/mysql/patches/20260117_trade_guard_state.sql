-- 变更说明: 新增盘中风控状态表 trade_guard_state
-- 影响范围: 实盘/模拟盘盘中风控
-- 回滚指引: DROP TABLE trade_guard_state;
CREATE TABLE IF NOT EXISTS trade_guard_state (
  id INT PRIMARY KEY AUTO_INCREMENT,
  project_id INT NOT NULL,
  trade_date DATE NOT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  halt_reason JSON NULL,
  risk_triggers INT NOT NULL DEFAULT 0,
  order_failures INT NOT NULL DEFAULT 0,
  market_data_errors INT NOT NULL DEFAULT 0,
  day_start_equity DOUBLE NULL,
  equity_peak DOUBLE NULL,
  last_equity DOUBLE NULL,
  last_valuation_ts DATETIME NULL,
  valuation_source VARCHAR(32) NULL,
  cooldown_until DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_guard_state (project_id, trade_date, mode)
);
