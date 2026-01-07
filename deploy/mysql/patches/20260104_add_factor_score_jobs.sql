CREATE TABLE IF NOT EXISTS factor_score_jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  params JSON NULL,
  output_dir VARCHAR(255) NULL,
  log_path VARCHAR(255) NULL,
  scores_path VARCHAR(255) NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  CONSTRAINT fk_factor_score_jobs_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_factor_score_jobs_project ON factor_score_jobs(project_id);
