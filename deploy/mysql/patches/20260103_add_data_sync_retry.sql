ALTER TABLE data_sync_jobs
ADD COLUMN retry_count INT NOT NULL DEFAULT 0 AFTER reset_history,
ADD COLUMN next_retry_at DATETIME NULL AFTER retry_count;
