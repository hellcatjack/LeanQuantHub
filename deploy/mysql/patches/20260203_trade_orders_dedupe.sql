-- 变更说明: 合并 lean 执行回放产生的重复订单（oi_ 前缀但 run_id 错配），迁移填充记录并删除重复订单
-- 影响范围: trade_orders, trade_fills
-- 回滚指引: 使用 trade_orders_dupe_backup_20260203 / trade_fills_dupe_backup_20260203 恢复，或从备份还原数据库

START TRANSACTION;

DROP TEMPORARY TABLE IF EXISTS tmp_trade_order_merge;
CREATE TEMPORARY TABLE tmp_trade_order_merge (
  duplicate_id BIGINT NOT NULL,
  duplicate_run_id BIGINT NULL,
  duplicate_client_order_id VARCHAR(64) NULL,
  target_run_id BIGINT NOT NULL,
  canonical_id BIGINT NOT NULL,
  PRIMARY KEY (duplicate_id)
);

INSERT INTO tmp_trade_order_merge (duplicate_id, duplicate_run_id, duplicate_client_order_id, target_run_id, canonical_id)
SELECT
  d.id AS duplicate_id,
  d.run_id AS duplicate_run_id,
  d.client_order_id AS duplicate_client_order_id,
  target_map.target_run_id,
  target_map.canonical_id
FROM trade_orders d
JOIN (
  SELECT
    run_id AS target_run_id,
    symbol,
    side,
    quantity,
    MIN(id) AS canonical_id,
    COUNT(*) AS cnt
  FROM trade_orders
  GROUP BY run_id, symbol, side, quantity
  HAVING COUNT(*) = 1
) target_map
  ON target_map.target_run_id = CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(d.client_order_id, '_', 2), '_', -1) AS UNSIGNED)
  AND target_map.symbol = d.symbol
  AND target_map.side = d.side
  AND ABS(target_map.quantity - d.quantity) < 0.000001
WHERE d.client_order_id REGEXP '^oi_[0-9]+_'
  AND d.run_id IS NOT NULL
  AND CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(d.client_order_id, '_', 2), '_', -1) AS UNSIGNED) <> d.run_id;

CREATE TABLE IF NOT EXISTS trade_orders_dupe_backup_20260203 LIKE trade_orders;
CREATE TABLE IF NOT EXISTS trade_fills_dupe_backup_20260203 LIKE trade_fills;

INSERT IGNORE INTO trade_orders_dupe_backup_20260203
SELECT d.*
FROM trade_orders d
JOIN tmp_trade_order_merge m ON m.duplicate_id = d.id;

INSERT IGNORE INTO trade_fills_dupe_backup_20260203
SELECT f.*
FROM trade_fills f
JOIN tmp_trade_order_merge m ON m.duplicate_id = f.order_id;

UPDATE trade_fills f
JOIN tmp_trade_order_merge m ON m.duplicate_id = f.order_id
SET f.order_id = m.canonical_id;

UPDATE trade_orders c
JOIN tmp_trade_order_merge m ON m.canonical_id = c.id
JOIN trade_orders d ON d.id = m.duplicate_id
SET
  c.ib_order_id = COALESCE(c.ib_order_id, d.ib_order_id),
  c.ib_perm_id = COALESCE(c.ib_perm_id, d.ib_perm_id),
  c.filled_quantity = CASE
    WHEN d.filled_quantity IS NULL THEN c.filled_quantity
    WHEN c.filled_quantity IS NULL THEN d.filled_quantity
    WHEN d.filled_quantity > c.filled_quantity THEN d.filled_quantity
    ELSE c.filled_quantity
  END,
  c.avg_fill_price = CASE
    WHEN (c.avg_fill_price IS NULL OR c.avg_fill_price = 0) AND d.avg_fill_price IS NOT NULL THEN d.avg_fill_price
    ELSE c.avg_fill_price
  END,
  c.status = CASE
    WHEN c.status IN ('FILLED', 'PARTIAL') THEN c.status
    WHEN d.status IN ('FILLED', 'PARTIAL') THEN d.status
    WHEN c.status = 'SUBMITTED' THEN c.status
    WHEN d.status = 'SUBMITTED' THEN d.status
    ELSE c.status
  END,
  c.updated_at = UTC_TIMESTAMP();

DELETE d
FROM trade_orders d
JOIN tmp_trade_order_merge m ON m.duplicate_id = d.id;

SELECT COUNT(*) AS merged_rows FROM tmp_trade_order_merge;

COMMIT;

INSERT INTO schema_migrations (version, description, checksum, applied_at)
SELECT
  '20260203_trade_orders_dedupe',
  'merge duplicate trade_orders from lean execution events',
  SHA2('20260203_trade_orders_dedupe', 256),
  NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260203_trade_orders_dedupe'
);
