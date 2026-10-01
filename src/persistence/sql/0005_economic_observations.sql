-- Versioned interpretation infrastructure only. No aggregation or selection.
CREATE TABLE rules (
    rule_id TEXT PRIMARY KEY NOT NULL CHECK(length(rule_id)=76 AND substr(rule_id,1,12)='rule:sha256:' AND substr(rule_id,13) NOT GLOB '*[^0-9a-f]*'),
    family TEXT NOT NULL CHECK(length(trim(family))>0),
    name TEXT NOT NULL CHECK(length(trim(name))>0),
    version TEXT NOT NULL CHECK(length(trim(version))>0),
    implementation_hash TEXT NOT NULL CHECK(length(implementation_hash)=64 AND implementation_hash NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(family, name, version, implementation_hash)
);

CREATE TABLE assessments (
    assessment_id TEXT PRIMARY KEY NOT NULL CHECK(length(assessment_id)=82 AND substr(assessment_id,1,18)='assessment:sha256:' AND substr(assessment_id,19) NOT GLOB '*[^0-9a-f]*'),
    document_id TEXT NOT NULL REFERENCES logical_documents(document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    rule_id TEXT NOT NULL REFERENCES rules(rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    input_signature TEXT NOT NULL CHECK(length(input_signature)=64 AND input_signature NOT GLOB '*[^0-9a-f]*'),
    inputs_json TEXT NOT NULL CHECK(json_valid(inputs_json) AND json_type(inputs_json)='array'),
    status TEXT NOT NULL CHECK(status IN ('usable','pending','ambiguous','excluded','incomplete')),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(document_id, rule_id, input_signature)
);

CREATE INDEX assessments_rule ON assessments(rule_id);

CREATE TABLE economic_observations (
    observation_id TEXT PRIMARY KEY NOT NULL CHECK(length(observation_id)=83 AND substr(observation_id,1,19)='observation:sha256:' AND substr(observation_id,20) NOT GLOB '*[^0-9a-f]*'),
    assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    observation_key TEXT NOT NULL CHECK(length(trim(observation_key))>0),
    magnitude TEXT NOT NULL CHECK(length(trim(magnitude))>0),
    scope TEXT NOT NULL CHECK(scope IN ('total','component','base','auxiliary')),
    nature TEXT NOT NULL CHECK(length(trim(nature))>0),
    pay_behavior TEXT NOT NULL CHECK(pay_behavior IN ('fixed','variable','unknown')),
    temporal_character TEXT NOT NULL CHECK(temporal_character IN ('current','arrears','adjustment','unknown')),
    payment_form TEXT NOT NULL CHECK(payment_form IN ('cash','in_kind','mixed','unknown')),
    settlement_context TEXT NOT NULL CHECK(length(trim(settlement_context))>0),
    liquidation_period TEXT NULL,
    liquidation_state TEXT NOT NULL CHECK(liquidation_state IN ('present','technical_null','not_extracted','not_present','not_applicable','unknown','unreliable')),
    liquidation_reason TEXT NULL,
    accrual_start TEXT NULL,
    accrual_end TEXT NULL,
    accrual_state TEXT NOT NULL CHECK(accrual_state IN ('present','technical_null','not_extracted','not_present','not_applicable','unknown','unreliable')),
    accrual_reason TEXT NULL,
    payment_date TEXT NULL,
    payment_state TEXT NOT NULL CHECK(payment_state IN ('present','technical_null','not_extracted','not_present','not_applicable','unknown','unreliable')),
    payment_reason TEXT NULL,
    economic_status TEXT NOT NULL CHECK(economic_status IN ('usable','pending','ambiguous','excluded','incomplete')),
    eligibility TEXT NOT NULL CHECK(eligibility IN ('candidate','evidence_only','excluded')),
    confidence TEXT NOT NULL CHECK(confidence IN ('explicit','mapped','reconstructed','inferred')),
    value_state TEXT NOT NULL CHECK(value_state IN ('present','technical_null','not_extracted','not_present','not_applicable','unknown','unreliable')),
    coefficient INTEGER NULL,
    scale INTEGER NULL,
    currency TEXT NULL CHECK(length(currency)=3 AND currency NOT GLOB '*[^A-Z]*'),
    reason_code TEXT NULL,
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(assessment_id, observation_key),
    CHECK((coefficient IS NULL AND scale IS NULL) OR (typeof(coefficient)='integer' AND typeof(scale)='integer' AND scale BETWEEN 0 AND 9 AND (scale=0 OR (coefficient<>0 AND coefficient%10<>0)))),
    CHECK((value_state='present' AND coefficient IS NOT NULL) OR value_state='unreliable' OR (value_state NOT IN ('present','unreliable') AND coefficient IS NULL)),
    CHECK(value_state NOT IN ('not_applicable','unreliable') OR reason_code IS NOT NULL),
    CHECK(economic_status<>'usable' OR value_state='present'),
    CHECK(eligibility<>'candidate' OR (economic_status='usable' AND value_state='present')),
    CHECK(economic_status<>'excluded' OR eligibility='excluded'),
    CHECK((liquidation_state='present' AND liquidation_period IS NOT NULL) OR liquidation_state='unreliable' OR (liquidation_state NOT IN ('present','unreliable') AND liquidation_period IS NULL)),
    CHECK(liquidation_state NOT IN ('not_applicable','unreliable') OR liquidation_reason IS NOT NULL),
    CHECK((accrual_state='present' AND accrual_start IS NOT NULL) OR accrual_state='unreliable' OR (accrual_state NOT IN ('present','unreliable') AND accrual_start IS NULL)),
    CHECK(accrual_state NOT IN ('not_applicable','unreliable') OR accrual_reason IS NOT NULL),
    CHECK((payment_state='present' AND payment_date IS NOT NULL) OR payment_state='unreliable' OR (payment_state NOT IN ('present','unreliable') AND payment_date IS NULL)),
    CHECK(payment_state NOT IN ('not_applicable','unreliable') OR payment_reason IS NOT NULL),
    CHECK((accrual_start IS NULL)=(accrual_end IS NULL)),
    CHECK(accrual_start<=accrual_end),
    CHECK(reason_code IS NULL OR (length(reason_code)>0 AND substr(reason_code,1,1) GLOB '[a-z]' AND reason_code NOT GLOB '*[^a-z0-9_.]*' AND reason_code NOT GLOB '*.[^a-z]*' AND substr(reason_code,-1)<>'.')),
    CHECK(liquidation_reason IS NULL OR (length(liquidation_reason)>0 AND substr(liquidation_reason,1,1) GLOB '[a-z]' AND liquidation_reason NOT GLOB '*[^a-z0-9_.]*' AND liquidation_reason NOT GLOB '*.[^a-z]*' AND substr(liquidation_reason,-1)<>'.')),
    CHECK(accrual_reason IS NULL OR (length(accrual_reason)>0 AND substr(accrual_reason,1,1) GLOB '[a-z]' AND accrual_reason NOT GLOB '*[^a-z0-9_.]*' AND accrual_reason NOT GLOB '*.[^a-z]*' AND substr(accrual_reason,-1)<>'.')),
    CHECK(payment_reason IS NULL OR (length(payment_reason)>0 AND substr(payment_reason,1,1) GLOB '[a-z]' AND payment_reason NOT GLOB '*[^a-z0-9_.]*' AND payment_reason NOT GLOB '*.[^a-z]*' AND substr(payment_reason,-1)<>'.'))
);

CREATE TABLE observation_facts (
    observation_id TEXT NOT NULL REFERENCES economic_observations(observation_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    fact_id TEXT NOT NULL REFERENCES documentary_facts(fact_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    PRIMARY KEY(observation_id, fact_id)
);

CREATE INDEX observation_facts_fact ON observation_facts(fact_id);
