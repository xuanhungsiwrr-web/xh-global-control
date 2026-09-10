CREATE UNIQUE INDEX execution_attempts_task_attempt_no
ON execution_attempts(task_id, attempt_no);

CREATE UNIQUE INDEX execution_attempts_task_generation
ON execution_attempts(task_id, generation);

CREATE INDEX task_events_task_event
ON task_events(task_id, event_id);

CREATE INDEX artifacts_task_created
ON artifacts(task_id, created_at);

CREATE TRIGGER execution_attempts_positive_insert
BEFORE INSERT ON execution_attempts
WHEN NEW.attempt_no < 1 OR NEW.generation < 1
BEGIN
    SELECT RAISE(ABORT, 'attempt_no and generation must be positive');
END;

CREATE TRIGGER execution_attempts_positive_update
BEFORE UPDATE OF attempt_no, generation ON execution_attempts
WHEN NEW.attempt_no < 1 OR NEW.generation < 1
BEGIN
    SELECT RAISE(ABORT, 'attempt_no and generation must be positive');
END;
