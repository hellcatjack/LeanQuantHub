CREATE TABLE IF NOT EXISTS decision_snapshots (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  pipeline_id INT NULL,
  train_job_id INT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  snapshot_date VARCHAR(16) NULL,
  params JSON NULL,
  summary JSON NULL,
  artifact_dir VARCHAR(255) NULL,
  summary_path VARCHAR(255) NULL,
  items_path VARCHAR(255) NULL,
  filters_path VARCHAR(255) NULL,
  log_path VARCHAR(255) NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  CONSTRAINT fk_decision_snapshots_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_decision_snapshots_pipeline FOREIGN KEY (pipeline_id)
    REFERENCES ml_pipeline_runs(id) ON DELETE SET NULL,
  CONSTRAINT fk_decision_snapshots_train_job FOREIGN KEY (train_job_id)
    REFERENCES ml_train_jobs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE pretrade_settings
  ADD COLUMN auto_decision_snapshot TINYINT(1) NOT NULL DEFAULT 1;

UPDATE pretrade_settings
  SET auto_decision_snapshot = 1
  WHERE auto_decision_snapshot IS NULL;

CREATE INDEX idx_decision_snapshots_project ON decision_snapshots(project_id);
CREATE INDEX idx_decision_snapshots_pipeline ON decision_snapshots(pipeline_id);
CREATE INDEX idx_decision_snapshots_train_job ON decision_snapshots(train_job_id);
