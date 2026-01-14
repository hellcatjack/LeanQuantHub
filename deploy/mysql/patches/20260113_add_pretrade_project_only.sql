ALTER TABLE pretrade_settings
  ADD COLUMN update_project_only TINYINT(1) NOT NULL DEFAULT 1;

UPDATE pretrade_settings
  SET update_project_only = 1
  WHERE update_project_only IS NULL;
