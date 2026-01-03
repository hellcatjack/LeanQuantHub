ALTER TABLE algorithm_versions
ADD COLUMN params JSON NULL AFTER content;
