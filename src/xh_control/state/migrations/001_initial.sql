CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    report_type TEXT,
    project_id TEXT NOT NULL,
    workspace_uri TEXT NOT NULL,
    user_request TEXT NOT NULL,

    cost_mode TEXT NOT NULL,
    master_preference TEXT NOT NULL,
    permission_level TEXT NOT NULL,

    api_soft_usd REAL NOT NULL,
    api_hard_usd REAL NOT NULL,

    status TEXT NOT NULL,

    assigned_worker_id TEXT,
    resolved_channel_id TEXT,
    current_attempt_id TEXT,
    latest_checkpoint_uri TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE execution_attempts (
    attempt_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,

    worker_id TEXT NOT NULL,
    channel_id TEXT,

    status TEXT NOT NULL,
    failure_type TEXT,
    failure_message TEXT,

    started_at TEXT,
    ended_at TEXT,

    generation INTEGER NOT NULL DEFAULT 1,

    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE TABLE task_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    attempt_id TEXT,

    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,

    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id),
    FOREIGN KEY(attempt_id) REFERENCES execution_attempts(attempt_id)
);

CREATE TABLE cost_events (
    cost_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    attempt_id TEXT,

    channel_id TEXT NOT NULL,
    billing_mode TEXT NOT NULL,

    input_tokens INTEGER,
    output_tokens INTEGER,

    estimated_usd REAL NOT NULL DEFAULT 0,

    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id),
    FOREIGN KEY(attempt_id) REFERENCES execution_attempts(attempt_id)
);

CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,

    action TEXT NOT NULL,
    reason TEXT NOT NULL,

    payload_json TEXT NOT NULL,

    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT,

    artifact_type TEXT NOT NULL,
    uri TEXT NOT NULL,
    sha256 TEXT,

    size_bytes INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id),
    FOREIGN KEY(attempt_id) REFERENCES execution_attempts(attempt_id)
);

CREATE TABLE channel_health (
    channel_id TEXT PRIMARY KEY,
    health TEXT NOT NULL,

    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_failure_at TEXT,
    cooldown_until TEXT,

    metadata_json TEXT NOT NULL
);

CREATE TABLE global_learning_events (
    learning_event_id TEXT PRIMARY KEY,

    task_id TEXT,
    plugin_id TEXT,
    channel_id TEXT,
    capability TEXT,

    success INTEGER NOT NULL,
    latency_seconds REAL,
    estimated_cost_usd REAL,
    estimated_context_tokens INTEGER,
    retries INTEGER,

    quality_score REAL,

    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE TRIGGER task_events_no_update BEFORE UPDATE ON task_events BEGIN SELECT RAISE(ABORT, 'task_events are append-only'); END;

CREATE TRIGGER task_events_no_delete BEFORE DELETE ON task_events BEGIN SELECT RAISE(ABORT, 'task_events are append-only'); END;
