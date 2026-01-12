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
