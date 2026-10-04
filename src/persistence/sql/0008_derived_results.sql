-- Reconstructible cache only. No economic formula or source-of-truth update.
CREATE TABLE derived_results (
    result_id TEXT PRIMARY KEY NOT NULL CHECK(length(result_id)=79
        AND substr(result_id,1,15)='derived:sha256:' AND substr(result_id,16) NOT GLOB '*[^0-9a-f]*'),
    rule_id TEXT NOT NULL REFERENCES rules(rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    parameters_json TEXT NOT NULL CHECK(CASE WHEN json_valid(parameters_json)
        THEN json_type(parameters_json)='object' ELSE 0 END),
    dataset_revision TEXT NOT NULL CHECK(length(dataset_revision)=64 AND dataset_revision NOT GLOB '*[^0-9a-f]*'),
    output_key TEXT NOT NULL CHECK(length(trim(output_key))>0),
    result_type TEXT NOT NULL CHECK(length(trim(result_type))>0),
    value_state TEXT NOT NULL CHECK(value_state IN
        ('present','technical_null','not_extracted','not_present','not_applicable','unknown','unreliable')),
    coefficient INTEGER NULL,
    scale INTEGER NULL,
    currency TEXT NULL CHECK(length(currency)=3 AND currency NOT GLOB '*[^A-Z]*'),
    reason_code TEXT NULL CHECK(length(reason_code)>0 AND substr(reason_code,1,1) GLOB '[a-z]'
        AND reason_code NOT GLOB '*[^a-z0-9_.]*' AND reason_code NOT GLOB '*.[^a-z]*'
        AND substr(reason_code,-1)<>'.'),
    status TEXT NOT NULL CHECK(status IN ('ready','invalid')),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    CHECK((coefficient IS NULL AND scale IS NULL) OR
        (typeof(coefficient)='integer' AND typeof(scale)='integer' AND scale BETWEEN 0 AND 9
        AND (scale=0 OR (coefficient<>0 AND coefficient%10<>0)))),
    CHECK((value_state='present' AND coefficient IS NOT NULL) OR value_state='unreliable'
        OR (value_state NOT IN ('present','unreliable') AND coefficient IS NULL)),
    CHECK(value_state NOT IN ('not_applicable','unreliable') OR reason_code IS NOT NULL),
    CHECK(status<>'ready' OR value_state='present')
);
CREATE INDEX derived_results_revision ON derived_results(dataset_revision);
CREATE INDEX derived_results_rule ON derived_results(rule_id);
CREATE TABLE derived_inputs (
    result_id TEXT NOT NULL REFERENCES derived_results(result_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    input_id TEXT NOT NULL,
    observation_id TEXT NULL REFERENCES economic_observations(observation_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    fact_id TEXT NULL REFERENCES documentary_facts(fact_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    PRIMARY KEY(result_id,input_id),
    CHECK((observation_id IS NOT NULL AND fact_id IS NULL) OR (observation_id IS NULL AND fact_id IS NOT NULL)),
    CHECK(input_id=coalesce(observation_id,fact_id))
);
CREATE INDEX derived_inputs_observation ON derived_inputs(observation_id);
CREATE INDEX derived_inputs_fact ON derived_inputs(fact_id);
