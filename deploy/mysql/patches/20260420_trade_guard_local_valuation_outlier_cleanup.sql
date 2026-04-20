-- 变更说明: 清理 trade_guard_state 中由 local 估值回退写入的异常大权益峰值，避免历史 drawdown 基线被污染。
-- 影响范围: trade_guard_state。
-- 回滚指引: 如需回滚，请从数据库备份恢复；本脚本为幂等修复，只会收敛 valuation_source=local:* 且明显超出 day_start_equity 3 倍的记录。

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'trade_guard_state'
);

SET @sql := IF(
  @table_exists > 0,
  "UPDATE trade_guard_state
   SET
     equity_peak = CASE
       WHEN valuation_source LIKE 'local:%'
        AND day_start_equity IS NOT NULL
        AND day_start_equity > 0
        AND equity_peak IS NOT NULL
        AND equity_peak > day_start_equity * 3
       THEN day_start_equity
       ELSE equity_peak
     END,
     last_equity = CASE
       WHEN valuation_source LIKE 'local:%'
        AND day_start_equity IS NOT NULL
        AND day_start_equity > 0
        AND last_equity IS NOT NULL
        AND last_equity > day_start_equity * 3
       THEN day_start_equity
       ELSE last_equity
     END,
     updated_at = NOW()
   WHERE valuation_source LIKE 'local:%'
     AND day_start_equity IS NOT NULL
     AND day_start_equity > 0
     AND (
       (equity_peak IS NOT NULL AND equity_peak > day_start_equity * 3)
       OR (last_equity IS NOT NULL AND last_equity > day_start_equity * 3)
     )",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260420_trade_guard_local_valuation_outlier_cleanup',
  'cleanup local valuation outlier peaks in trade guard state',
  SHA2('20260420_trade_guard_local_valuation_outlier_cleanup', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260420_trade_guard_local_valuation_outlier_cleanup'
);
