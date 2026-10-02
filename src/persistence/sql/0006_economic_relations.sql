-- Explicit relations only; economic selection remains in Python.

CREATE TABLE document_relations (
    relation_id TEXT PRIMARY KEY NOT NULL CHECK(length(relation_id)=89
        AND substr(relation_id,1,25)='document_relation:sha256:'
        AND substr(relation_id,26) NOT GLOB '*[^0-9a-f]*'),
    source_document_id TEXT NOT NULL REFERENCES logical_documents(document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    target_document_id TEXT NOT NULL REFERENCES logical_documents(document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('duplicate_of','supersedes','complements','same_logical_unit_pending_reconciliation')),
    rule_id TEXT NULL REFERENCES rules(rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    reason_code TEXT NULL CHECK(length(reason_code)>0 AND substr(reason_code,1,1) GLOB '[a-z]'
        AND reason_code NOT GLOB '*[^a-z0-9_.]*' AND reason_code NOT GLOB '*.[^a-z]*'
        AND substr(reason_code,-1)<>'.'),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(source_document_id, target_document_id, relation_type),
    CHECK(source_document_id<>target_document_id),
    CHECK(relation_type NOT IN ('duplicate_of','complements','same_logical_unit_pending_reconciliation') OR source_document_id<target_document_id),
    CHECK(rule_id IS NOT NULL OR reason_code IS NOT NULL)
);
CREATE INDEX document_relations_target ON document_relations(target_document_id);
CREATE INDEX document_relations_rule ON document_relations(rule_id);

CREATE TABLE observation_relations (
    relation_id TEXT PRIMARY KEY NOT NULL CHECK(length(relation_id)=92
        AND substr(relation_id,1,28)='observation_relation:sha256:'
        AND substr(relation_id,29) NOT GLOB '*[^0-9a-f]*'),
    source_observation_id TEXT NOT NULL REFERENCES economic_observations(observation_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    target_observation_id TEXT NOT NULL REFERENCES economic_observations(observation_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('contained_in','adjusts','replaces','complements')),
    rule_id TEXT NULL REFERENCES rules(rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    reason_code TEXT NULL CHECK(length(reason_code)>0 AND substr(reason_code,1,1) GLOB '[a-z]'
        AND reason_code NOT GLOB '*[^a-z0-9_.]*' AND reason_code NOT GLOB '*.[^a-z]*'
        AND substr(reason_code,-1)<>'.'),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(source_observation_id, target_observation_id, relation_type),
    CHECK(source_observation_id<>target_observation_id),
    CHECK(relation_type NOT IN ('complements') OR source_observation_id<target_observation_id),
    CHECK(rule_id IS NOT NULL OR reason_code IS NOT NULL)
);
CREATE INDEX observation_relations_target ON observation_relations(target_observation_id);
CREATE INDEX observation_relations_rule ON observation_relations(rule_id);
