-- change: create trade_settings for global trade risk defaults
-- impact: adds trade_settings table used by /api/trade/settings
-- rollback: drop table trade_settings if no data required

CREATE TABLE IF NOT EXISTS trade_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  risk_defaults JSON NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

