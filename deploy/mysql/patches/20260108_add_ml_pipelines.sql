CREATE TABLE IF NOT EXISTS ml_pipeline_runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  name VARCHAR(120) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'created',
  params JSON NULL,
  notes TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  CONSTRAINT fk_ml_pipeline_runs_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE backtest_runs
  ADD COLUMN pipeline_id INT NULL;

ALTER TABLE backtest_runs
  ADD CONSTRAINT fk_backtest_runs_pipeline FOREIGN KEY (pipeline_id)
    REFERENCES ml_pipeline_runs(id) ON DELETE SET NULL;

ALTER TABLE ml_train_jobs
  ADD COLUMN pipeline_id INT NULL;

ALTER TABLE ml_train_jobs
  ADD CONSTRAINT fk_ml_train_jobs_pipeline FOREIGN KEY (pipeline_id)
    REFERENCES ml_pipeline_runs(id) ON DELETE SET NULL;

CREATE INDEX idx_ml_pipeline_runs_project ON ml_pipeline_runs(project_id);
CREATE INDEX idx_backtest_runs_pipeline ON backtest_runs(pipeline_id);
CREATE INDEX idx_ml_train_jobs_pipeline ON ml_train_jobs(pipeline_id);
