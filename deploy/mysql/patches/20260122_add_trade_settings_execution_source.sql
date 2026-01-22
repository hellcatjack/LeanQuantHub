-- Change: add execution_data_source to trade_settings
-- Impact: records live execution data source (locked to IB)
-- Rollback: DROP COLUMN execution_data_source from trade_settings (manual)

ALTER TABLE trade_settings
    ADD COLUMN IF NOT EXISTS execution_data_source VARCHAR(16) NOT NULL DEFAULT 'ib';

UPDATE trade_settings
SET execution_data_source = 'ib'
WHERE execution_data_source IS NULL OR execution_data_source = '';

INSERT INTO schema_migrations (version)
SELECT '20260122_add_trade_settings_execution_source'
WHERE EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
    SELECT 1 FROM schema_migrations WHERE version = '20260122_add_trade_settings_execution_source'
);
