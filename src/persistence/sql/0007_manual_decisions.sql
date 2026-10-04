-- No polymorphic FK: the target and preconditions are checked in Python.
CREATE TABLE manual_decisions (
    decision_id TEXT PRIMARY KEY NOT NULL CHECK(length(decision_id)=87
        AND substr(decision_id,1,23)='manual_decision:sha256:'
        AND substr(decision_id,24) NOT GLOB '*[^0-9a-f]*'),
    decision_type TEXT NOT NULL CHECK(decision_type='acknowledge_documentary_fact'),
    target_type TEXT NOT NULL CHECK(target_type='documentary_fact'),
    target_id TEXT NOT NULL CHECK(length(trim(target_id))>0),
    payload_json TEXT NOT NULL CHECK(CASE WHEN json_valid(payload_json)
        THEN json_type(payload_json)='object' ELSE 0 END),
    precondition_hash TEXT NOT NULL CHECK(length(precondition_hash)=64
        AND precondition_hash NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    created_by TEXT NOT NULL CHECK(length(trim(created_by))>0)
);
CREATE INDEX manual_decisions_target ON manual_decisions(target_type,target_id);
-- Integrity guards only; no economic or resolution logic in triggers.
CREATE TRIGGER manual_decisions_no_update BEFORE UPDATE ON manual_decisions
BEGIN SELECT RAISE(ABORT, 'manual decisions are append-only'); END;
CREATE TRIGGER manual_decisions_no_delete BEFORE DELETE ON manual_decisions
BEGIN SELECT RAISE(ABORT, 'manual decisions are append-only'); END;
