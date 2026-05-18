-- 变更说明: 将默认防御标的与防御篮子统一迁移为 SGOV。
-- 影响范围: project_versions, algorithm_versions。
-- 回滚指引: 如需回滚，请从数据库备份恢复；或执行新的数据修复脚本，将相关配置字段改回目标值并重新计算 project_versions.content_hash。

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
           '$.backtest_params.risk_off_symbols', 'SGOV',
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
   SET params = JSON_SET(params, '$.risk_off_symbols', 'SGOV')
   WHERE params IS NOT NULL
     AND JSON_CONTAINS_PATH(params, 'one', '$.risk_off_symbols')",
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
     AND JSON_CONTAINS_PATH(params, 'one', '$.risk_off_symbol')",
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
   SET params = JSON_SET(params, '$.defensive.symbols', JSON_ARRAY('SGOV'))
   WHERE params IS NOT NULL
     AND JSON_CONTAINS_PATH(params, 'one', '$.defensive')",
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260326_force_defensive_defaults_to_sgov',
  'force defensive defaults to SGOV',
  SHA2('20260326_force_defensive_defaults_to_sgov', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260326_force_defensive_defaults_to_sgov'
);
