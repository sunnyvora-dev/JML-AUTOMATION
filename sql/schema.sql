-- Database Initialization Schema for JML Automation

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_username TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'jml-automation',
    details JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_target_username ON audit_log(target_username);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
