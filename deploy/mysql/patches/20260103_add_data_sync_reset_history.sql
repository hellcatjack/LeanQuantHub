ALTER TABLE data_sync_jobs
ADD COLUMN reset_history BOOLEAN NOT NULL DEFAULT 0 AFTER date_column;
