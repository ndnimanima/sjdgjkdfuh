-- Optional Cloudflare D1 schema for privacy-minimal edge request diagnostics.
-- This database is NOT Rozaneh's application database. SQLite under DATA_DIR
-- on the persistent Python origin remains the source of truth.
CREATE TABLE IF NOT EXISTS edge_access_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id  TEXT NOT NULL,
  method      TEXT NOT NULL,
  path        TEXT NOT NULL,
  status      INTEGER NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edge_access_created_at
  ON edge_access_log (created_at);

CREATE INDEX IF NOT EXISTS idx_edge_access_status
  ON edge_access_log (status);
