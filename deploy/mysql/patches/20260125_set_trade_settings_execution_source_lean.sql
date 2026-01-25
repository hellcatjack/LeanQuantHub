-- Change: set trade_settings.execution_data_source to 'lean' for Lean-based execution
-- Impact: trade_settings (data update only)
-- Rollback: set execution_data_source back to 'ib'

UPDATE trade_settings
SET execution_data_source = 'lean',
    updated_at = UTC_TIMESTAMP()
WHERE execution_data_source <> 'lean' OR execution_data_source IS NULL;

-- Rollback:
-- UPDATE trade_settings
-- SET execution_data_source = 'ib',
--     updated_at = UTC_TIMESTAMP()
-- WHERE execution_data_source <> 'ib' OR execution_data_source IS NULL;
