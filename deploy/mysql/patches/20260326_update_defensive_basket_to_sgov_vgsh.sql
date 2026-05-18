-- 变更说明: 将默认防御篮子从 SGOV 调整为 SGOV,VGSH，并保持主防御标的为 SGOV。
-- 影响范围: project_versions, algorithm_versions。
-- 回滚指引: 如需回滚，请执行新的修复脚本，将 risk_off_symbols 改回目标值并重新计算 project_versions.content_hash；或从数据库备份恢复。

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'project_versions'
);
SET @sql := IF(
  @table_exists > 0,
  "UPDATE project_versions
   SET content = JSON_PRETTY(
         JSON_SET(
           content,
           '$.backtest_params.risk_off_symbols', 'SGOV,VGSH',
           '$.backtest_params.risk_off_symbol', 'SGOV'
         )
       )
   WHERE description = 'project_config'
     AND content IS NOT NULL
     AND JSON_VALID(content)",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'project_versions'
);
SET @sql := IF(
  @table_exists > 0,
  "UPDATE project_versions
   SET content_hash = SHA2(content, 256)
   WHERE description = 'project_config'
     AND content IS NOT NULL
     AND JSON_VALID(content)",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'algorithm_versions'
);
SET @sql := IF(
  @table_exists > 0,
  "UPDATE algorithm_versions
   SET params = JSON_SET(params, '$.risk_off_symbols', 'SGOV,VGSH')
   WHERE params IS NOT NULL
     AND JSON_CONTAINS_PATH(params, 'one', '$.risk_off_symbols', '$.risk_off_symbol', '$.defensive')",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'algorithm_versions'
);
SET @sql := IF(
  @table_exists > 0,
  "UPDATE algorithm_versions
   SET params = JSON_SET(params, '$.risk_off_symbol', 'SGOV')
   WHERE params IS NOT NULL
     AND JSON_CONTAINS_PATH(params, 'one', '$.risk_off_symbols', '$.risk_off_symbol', '$.defensive')",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @table_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = 'algorithm_versions'
);
SET @sql := IF(
  @table_exists > 0,
  "UPDATE algorithm_versions
   SET params = JSON_SET(params, '$.defensive.symbols', JSON_ARRAY('SGOV', 'VGSH'))
   WHERE params IS NOT NULL
     AND JSON_CONTAINS_PATH(params, 'one', '$.defensive')",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260326_update_defensive_basket_to_sgov_vgsh',
  'update defensive basket to SGOV,VGSH',
  SHA2('20260326_update_defensive_basket_to_sgov_vgsh', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260326_update_defensive_basket_to_sgov_vgsh'
);
