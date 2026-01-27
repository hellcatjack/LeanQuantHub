-- 变更说明: 标记 trade_run 24 因 TWS 崩溃未送达订单为失败，并取消未送达订单。
-- 影响范围: trade_runs.id=24, trade_orders.run_id=24。
-- 回滚指引: 如需回滚，请根据审计记录恢复 trade_runs.status/message/ended_at，
--           并将 trade_orders.status 恢复为 NEW，清空 rejected_reason。

START TRANSACTION;

UPDATE trade_runs
SET
  status = 'failed',
  message = 'tws_crash_no_ib_orders',
  ended_at = UTC_TIMESTAMP(),
  updated_at = UTC_TIMESTAMP()
WHERE id = 24
  AND status = 'running'
  AND message = 'submitted_lean';

UPDATE trade_orders
SET
  status = 'canceled',
  rejected_reason = 'tws_crash_no_ib_orders',
  updated_at = UTC_TIMESTAMP()
WHERE run_id = 24
  AND status = 'NEW'
  AND (ib_order_id IS NULL OR ib_order_id = 0);

COMMIT;
