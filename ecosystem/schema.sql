-- Research, Knowledge & Development Ecosystem: Logbook schema v1
-- SQLite >= 3.35 with FTS5. Append-only history: records are never deleted.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- One row per knowledge record (finding, hypothesis, project, experiment, lesson, ...).
CREATE TABLE IF NOT EXISTS records (
  rowid            INTEGER PRIMARY KEY,
  id               TEXT NOT NULL UNIQUE,          -- e.g. KR-000001
  kind             TEXT NOT NULL CHECK (kind IN
                     ('finding','hypothesis','observation','project','experiment',
                      'tool','lesson','failed_approach','decision','report')),
  title            TEXT NOT NULL,
  description      TEXT NOT NULL,
  category         TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN
                     ('unverified','hypothesis','under_investigation',
                      'historically_supported','validated','rejected','n/a')),
  confidence       REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  methodology      TEXT,
  sample_size      INTEGER,
  time_period      TEXT,
  evidence         TEXT,                          -- summary of supporting evidence
  limitations      TEXT,
  tags             TEXT,                          -- space-separated
  created_by       TEXT NOT NULL,
  discovered_at    TEXT NOT NULL,
  last_verified_at TEXT,
  updated_at       TEXT NOT NULL,
  version          INTEGER NOT NULL DEFAULT 1,
  content_hash     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_category ON records(category);
CREATE INDEX IF NOT EXISTS idx_records_status   ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_hash     ON records(content_hash);

-- Full snapshot of every prior version, written before each update.
CREATE TABLE IF NOT EXISTS record_versions (
  record_id   TEXT NOT NULL REFERENCES records(id),
  version     INTEGER NOT NULL,
  snapshot    TEXT NOT NULL,                      -- JSON of the row as it was
  changed_by  TEXT NOT NULL,
  change_note TEXT,
  changed_at  TEXT NOT NULL,
  PRIMARY KEY (record_id, version)
);

-- Original source references and raw evidence pointers.
CREATE TABLE IF NOT EXISTS sources (
  id           INTEGER PRIMARY KEY,
  record_id    TEXT NOT NULL REFERENCES records(id),
  kind         TEXT NOT NULL,                     -- url, tx, wallet, dataset, file, api
  ref          TEXT NOT NULL,
  note         TEXT,
  retrieved_at TEXT,
  UNIQUE (record_id, kind, ref)
);

-- Typed relations between records.
CREATE TABLE IF NOT EXISTS links (
  src        TEXT NOT NULL REFERENCES records(id),
  dst        TEXT NOT NULL REFERENCES records(id),
  relation   TEXT NOT NULL CHECK (relation IN
               ('related','supports','contradicts','supersedes','derived_from','implements','tests')),
  note       TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (src, dst, relation)
);

-- Append-only: every note a link had before it was changed, with who changed it and when.
CREATE TABLE IF NOT EXISTS link_note_history (
  src        TEXT NOT NULL,
  dst        TEXT NOT NULL,
  relation   TEXT NOT NULL,
  old_note   TEXT,
  new_note   TEXT,
  changed_by TEXT NOT NULL,
  changed_at TEXT NOT NULL
);

-- Full-text index over records (external content, kept in sync by triggers).
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
  title, description, evidence, methodology, limitations, category, tags,
  content='records', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
  INSERT INTO records_fts(rowid,title,description,evidence,methodology,limitations,category,tags)
  VALUES (new.rowid,new.title,new.description,new.evidence,new.methodology,new.limitations,new.category,new.tags);
END;
CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
  INSERT INTO records_fts(records_fts,rowid,title,description,evidence,methodology,limitations,category,tags)
  VALUES ('delete',old.rowid,old.title,old.description,old.evidence,old.methodology,old.limitations,old.category,old.tags);
  INSERT INTO records_fts(rowid,title,description,evidence,methodology,limitations,category,tags)
  VALUES (new.rowid,new.title,new.description,new.evidence,new.methodology,new.limitations,new.category,new.tags);
END;
CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records BEGIN
  SELECT RAISE(ABORT, 'records are append-only; set status=rejected instead');
END;

-- Task queue with explicit objective, completion condition and budget.
CREATE TABLE IF NOT EXISTS tasks (
  id             TEXT PRIMARY KEY,                -- T-000001
  agent          TEXT NOT NULL,                   -- researcher, logbook, builder
  objective      TEXT NOT NULL,
  done_condition TEXT NOT NULL,
  budget         TEXT NOT NULL,                   -- JSON: model_requests, max_minutes, max_pages, max_retries
  used           TEXT NOT NULL DEFAULT '{}',      -- JSON counters
  progress       TEXT NOT NULL DEFAULT '{}',      -- JSON checkpoint for resume
  status         TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
                   ('queued','running','paused','done','failed','cancelled')),
  priority       INTEGER NOT NULL DEFAULT 5,
  error          TEXT,
  created_by     TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks(agent, status, priority);

-- Every protocol message between agents, persisted.
CREATE TABLE IF NOT EXISTS messages (
  id         TEXT PRIMARY KEY,
  from_agent TEXT NOT NULL,
  to_agent   TEXT NOT NULL,
  type       TEXT NOT NULL,
  reply_to   TEXT,
  payload    TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','handled','error')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_inbox ON messages(to_agent, status);

-- Per-provider daily request counter for free-tier budgets.
CREATE TABLE IF NOT EXISTS api_usage (
  provider TEXT NOT NULL,
  day      TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  paused_until TEXT,
  PRIMARY KEY (provider, day)
);
