CREATE DATABASE IF NOT EXISTS stocklean
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE stocklean;

CREATE TABLE IF NOT EXISTS projects (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  description TEXT NULL,
  is_archived TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

CREATE INDEX idx_ml_pipeline_runs_project ON ml_pipeline_runs(project_id);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  pipeline_id INT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  params JSON NULL,
  metrics JSON NULL,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_backtest_runs_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_backtest_runs_pipeline FOREIGN KEY (pipeline_id)
    REFERENCES ml_pipeline_runs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_backtest_runs_project ON backtest_runs(project_id);
CREATE INDEX idx_backtest_runs_pipeline ON backtest_runs(pipeline_id);

CREATE TABLE IF NOT EXISTS reports (
  id INT AUTO_INCREMENT PRIMARY KEY,
  run_id INT NOT NULL,
  report_type VARCHAR(40) NOT NULL DEFAULT 'summary',
  path VARCHAR(255) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_reports_run FOREIGN KEY (run_id)
    REFERENCES backtest_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_reports_run ON reports(run_id);

CREATE TABLE IF NOT EXISTS ml_train_jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  pipeline_id INT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  config JSON NULL,
  metrics JSON NULL,
  output_dir VARCHAR(255) NULL,
  model_path VARCHAR(255) NULL,
  payload_path VARCHAR(255) NULL,
  scores_path VARCHAR(255) NULL,
  log_path VARCHAR(255) NULL,
  message TEXT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  CONSTRAINT fk_ml_train_jobs_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_ml_train_jobs_pipeline FOREIGN KEY (pipeline_id)
    REFERENCES ml_pipeline_runs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_ml_train_jobs_project ON ml_train_jobs(project_id);
CREATE INDEX idx_ml_train_jobs_pipeline ON ml_train_jobs(pipeline_id);

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

CREATE TABLE IF NOT EXISTS datasets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  vendor VARCHAR(64) NULL,
  asset_class VARCHAR(32) NULL,
  region VARCHAR(32) NULL,
  frequency VARCHAR(16) NULL,
  coverage_start VARCHAR(16) NULL,
  coverage_end VARCHAR(16) NULL,
  source_path VARCHAR(255) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_datasets_name ON datasets(name);

CREATE TABLE IF NOT EXISTS project_versions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  version VARCHAR(32) NULL,
  description TEXT NULL,
  content TEXT NULL,
  content_hash VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_project_versions_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_project_versions_project ON project_versions(project_id);

CREATE TABLE IF NOT EXISTS algorithms (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  description TEXT NULL,
  language VARCHAR(16) NOT NULL DEFAULT 'Python',
  file_path VARCHAR(255) NULL,
  type_name VARCHAR(120) NULL,
  version VARCHAR(32) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS algorithm_versions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  algorithm_id INT NOT NULL,
  version VARCHAR(32) NULL,
  description TEXT NULL,
  language VARCHAR(16) NOT NULL DEFAULT 'Python',
  file_path VARCHAR(255) NULL,
  type_name VARCHAR(120) NULL,
  content_hash VARCHAR(64) NULL,
  content TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_algorithm_versions_algorithm FOREIGN KEY (algorithm_id)
    REFERENCES algorithms(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_algorithm_versions_algorithm ON algorithm_versions(algorithm_id);

CREATE TABLE IF NOT EXISTS project_algorithm_bindings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL UNIQUE,
  algorithm_id INT NOT NULL,
  algorithm_version_id INT NOT NULL,
  is_locked TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_project_algorithm_bindings_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_project_algorithm_bindings_algorithm FOREIGN KEY (algorithm_id)
    REFERENCES algorithms(id),
  CONSTRAINT fk_project_algorithm_bindings_version FOREIGN KEY (algorithm_version_id)
    REFERENCES algorithm_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_project_algorithm_bindings_algorithm ON project_algorithm_bindings(algorithm_id);
CREATE INDEX idx_project_algorithm_bindings_version ON project_algorithm_bindings(algorithm_version_id);

CREATE TABLE IF NOT EXISTS data_sync_jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  dataset_id INT NOT NULL,
  source_path VARCHAR(255) NOT NULL,
  date_column VARCHAR(64) NOT NULL DEFAULT 'date',
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  rows_scanned INT NULL,
  coverage_start VARCHAR(16) NULL,
  coverage_end VARCHAR(16) NULL,
  normalized_path VARCHAR(255) NULL,
  output_path VARCHAR(255) NULL,
  snapshot_path VARCHAR(255) NULL,
  lean_path VARCHAR(255) NULL,
  adjusted_path VARCHAR(255) NULL,
  lean_adjusted_path VARCHAR(255) NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  CONSTRAINT fk_data_sync_jobs_dataset FOREIGN KEY (dataset_id)
    REFERENCES datasets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_data_sync_jobs_dataset ON data_sync_jobs(dataset_id);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  actor VARCHAR(64) NOT NULL DEFAULT 'system',
  action VARCHAR(64) NOT NULL,
  resource_type VARCHAR(64) NOT NULL,
  resource_id INT NULL,
  detail JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);

CREATE TABLE IF NOT EXISTS pretrade_templates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NULL,
  name VARCHAR(120) NOT NULL,
  params JSON NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_pretrade_templates_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_pretrade_templates_project ON pretrade_templates(project_id);

CREATE TABLE IF NOT EXISTS pretrade_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  current_template_id INT NULL,
  telegram_bot_token VARCHAR(255) NULL,
  telegram_chat_id VARCHAR(255) NULL,
  max_retries INT NOT NULL DEFAULT 0,
  retry_base_delay_seconds INT NOT NULL DEFAULT 60,
  retry_max_delay_seconds INT NOT NULL DEFAULT 1800,
  deadline_time VARCHAR(16) NULL,
  deadline_timezone VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pretrade_runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  template_id INT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  window_start DATETIME NULL,
  window_end DATETIME NULL,
  deadline_at DATETIME NULL,
  params JSON NULL,
  message TEXT NULL,
  fallback_used TINYINT(1) NOT NULL DEFAULT 0,
  fallback_run_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_pretrade_runs_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_pretrade_runs_project ON pretrade_runs(project_id);
CREATE INDEX idx_pretrade_runs_status ON pretrade_runs(status);

CREATE TABLE IF NOT EXISTS pretrade_steps (
  id INT AUTO_INCREMENT PRIMARY KEY,
  run_id INT NOT NULL,
  step_key VARCHAR(64) NOT NULL,
  step_order INT NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  progress FLOAT NULL,
  retry_count INT NOT NULL DEFAULT 0,
  next_retry_at DATETIME NULL,
  message TEXT NULL,
  log_path VARCHAR(255) NULL,
  params JSON NULL,
  artifacts JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_pretrade_steps_run FOREIGN KEY (run_id)
    REFERENCES pretrade_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_pretrade_steps_run ON pretrade_steps(run_id);
CREATE INDEX idx_pretrade_steps_status ON pretrade_steps(status);
