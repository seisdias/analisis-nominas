-- Atomic facts only. No economic classification, derived totals or model payload.
CREATE TABLE documentary_facts (
    fact_id TEXT PRIMARY KEY NOT NULL
        CHECK(length(fact_id)=76 AND substr(fact_id,1,12)='fact:sha256:'
              AND substr(fact_id,13) NOT GLOB '*[^0-9a-f]*'),
    extraction_id TEXT NOT NULL REFERENCES extractions(extraction_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    fact_key TEXT NOT NULL CHECK(length(trim(fact_key))>0),
    value_state TEXT NOT NULL CHECK(value_state IN
        ('present','technical_null','not_extracted','not_present','not_applicable','unknown','unreliable')),
    value_kind TEXT NULL CHECK(value_kind IN ('decimal','text')),
    coefficient INTEGER NULL,
    scale INTEGER NULL,
    text_value TEXT NULL,
    currency TEXT NULL CHECK(length(currency)=3 AND currency NOT GLOB '*[^A-Z]*'),
    reason_code TEXT NULL CHECK(length(reason_code)>0 AND substr(reason_code,1,1) GLOB '[a-z]'
        AND reason_code NOT GLOB '*[^a-z0-9_.]*' AND reason_code NOT GLOB '*.[^a-z]*'
        AND substr(reason_code,-1)<>'.'),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(extraction_id, fact_key),
    CHECK(CASE value_kind
        WHEN 'decimal' THEN typeof(coefficient)='integer' AND typeof(scale)='integer'
            AND scale BETWEEN 0 AND 9 AND text_value IS NULL
            AND (scale=0 OR (coefficient<>0 AND coefficient%10<>0))
        WHEN 'text' THEN typeof(text_value)='text' AND coefficient IS NULL AND scale IS NULL
        ELSE value_kind IS NULL AND coefficient IS NULL AND scale IS NULL AND text_value IS NULL
    END),
    CHECK(value_kind IS NULL OR value_kind<>'text' OR currency IS NULL),
    CHECK((value_state='present' AND value_kind IS NOT NULL)
        OR value_state='unreliable'
        OR (value_state NOT IN ('present','unreliable') AND value_kind IS NULL)),
    CHECK(value_state NOT IN ('not_applicable','unreliable') OR reason_code IS NOT NULL)
);

CREATE TABLE fact_pages (
    fact_id TEXT NOT NULL REFERENCES documentary_facts(fact_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    version_id TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK(typeof(page_number)='integer' AND page_number>0),
    PRIMARY KEY(fact_id, page_number),
    FOREIGN KEY(version_id, page_number) REFERENCES version_pages(version_id, page_number)
        ON DELETE RESTRICT ON UPDATE RESTRICT
);
CREATE INDEX fact_pages_version_page ON fact_pages(version_id, page_number);
