-- Identity and physical evidence only. No documentary/economic interpretation.

CREATE TABLE persons (
    person_id TEXT PRIMARY KEY NOT NULL CHECK(length(person_id) = 78 AND substr(person_id, 1, 14) = 'person:sha256:' AND substr(person_id, 15) NOT GLOB '*[^0-9a-f]*'),
    local_alias TEXT NOT NULL CHECK(length(trim(local_alias)) > 0),
    created_at TEXT NOT NULL CHECK(strftime('%s', created_at) IS NOT NULL AND (substr(created_at, -6) = '+00:00' OR substr(created_at, -1) = 'Z'))
);
CREATE TABLE employers (
    employer_id TEXT PRIMARY KEY NOT NULL CHECK(length(employer_id) = 80 AND substr(employer_id, 1, 16) = 'employer:sha256:' AND substr(employer_id, 17) NOT GLOB '*[^0-9a-f]*'),
    country TEXT NOT NULL CHECK(length(country)=2 AND country NOT GLOB '*[^A-Z]*'),
    tax_id TEXT NULL CHECK(length(trim(tax_id))>0 AND tax_id=trim(tax_id)),
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
    created_at TEXT NOT NULL CHECK(strftime('%s', created_at) IS NOT NULL AND (substr(created_at, -6) = '+00:00' OR substr(created_at, -1) = 'Z'))
);
CREATE UNIQUE INDEX employers_tax_identity ON employers(country, tax_id) WHERE tax_id IS NOT NULL;
CREATE TABLE corpora (
    corpus_id TEXT PRIMARY KEY NOT NULL CHECK(length(corpus_id) = 78 AND substr(corpus_id, 1, 14) = 'corpus:sha256:' AND substr(corpus_id, 15) NOT GLOB '*[^0-9a-f]*'),
    person_id TEXT NOT NULL CHECK(length(person_id) = 78 AND substr(person_id, 1, 14) = 'person:sha256:' AND substr(person_id, 15) NOT GLOB '*[^0-9a-f]*'),
    label TEXT NOT NULL CHECK(length(trim(label)) > 0),
    manifest_contract TEXT NOT NULL CHECK(length(trim(manifest_contract)) > 0),
    created_at TEXT NOT NULL CHECK(strftime('%s', created_at) IS NOT NULL AND (substr(created_at, -6) = '+00:00' OR substr(created_at, -1) = 'Z')),
    FOREIGN KEY (person_id) REFERENCES persons(person_id) ON DELETE RESTRICT ON UPDATE RESTRICT
);
CREATE INDEX corpora_person ON corpora(person_id);
CREATE TABLE source_files (
    file_id TEXT PRIMARY KEY NOT NULL CHECK(length(file_id) = 76 AND substr(file_id, 1, 12) = 'file:sha256:' AND substr(file_id, 13) NOT GLOB '*[^0-9a-f]*'),
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    byte_size INTEGER NOT NULL CHECK(typeof(byte_size)='integer' AND byte_size>=0),
    media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
    page_count INTEGER NULL CHECK(page_count IS NULL OR (typeof(page_count)='integer' AND page_count>0)),
    availability TEXT NOT NULL CHECK(availability IN ('available','not_located','withdrawn')),
    created_at TEXT NOT NULL CHECK(strftime('%s', created_at) IS NOT NULL AND (substr(created_at, -6) = '+00:00' OR substr(created_at, -1) = 'Z')),
    UNIQUE (sha256)
);
CREATE TABLE file_locations (
    corpus_id TEXT NOT NULL CHECK(length(corpus_id) = 78 AND substr(corpus_id, 1, 14) = 'corpus:sha256:' AND substr(corpus_id, 15) NOT GLOB '*[^0-9a-f]*'),
    relative_path TEXT NOT NULL CHECK(length(relative_path)>0 AND substr(relative_path,1,1)<>'/' AND instr(relative_path, char(92))=0 AND instr(relative_path, ':')=0 AND instr('/'||relative_path||'/', '/../')=0 AND instr('/'||relative_path||'/', '/./')=0 AND instr(relative_path, '//')=0 AND substr(relative_path,-1)<>'/'),
    file_id TEXT NOT NULL CHECK(length(file_id) = 76 AND substr(file_id, 1, 12) = 'file:sha256:' AND substr(file_id, 13) NOT GLOB '*[^0-9a-f]*'),
    original_filename TEXT NOT NULL CHECK(length(trim(original_filename)) > 0) CHECK(instr(original_filename,'/')=0 AND instr(original_filename,char(92))=0),
    first_seen_at TEXT NOT NULL CHECK(strftime('%s', first_seen_at) IS NOT NULL AND (substr(first_seen_at, -6) = '+00:00' OR substr(first_seen_at, -1) = 'Z')),
    PRIMARY KEY (corpus_id, relative_path, file_id),
    FOREIGN KEY (corpus_id) REFERENCES corpora(corpus_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (file_id) REFERENCES source_files(file_id) ON DELETE RESTRICT ON UPDATE RESTRICT
);
CREATE INDEX file_locations_file ON file_locations(file_id);
CREATE TABLE ingest_runs (
    run_id TEXT PRIMARY KEY NOT NULL CHECK(length(run_id) = 82 AND substr(run_id, 1, 18) = 'ingest_run:sha256:' AND substr(run_id, 19) NOT GLOB '*[^0-9a-f]*'),
    plan_hash TEXT NOT NULL CHECK(length(plan_hash) = 64 AND plan_hash NOT GLOB '*[^0-9a-f]*'),
    contract_version INTEGER NOT NULL CHECK(contract_version=1),
    plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
    status TEXT NOT NULL CHECK(status IN ('running','complete','partial')),
    started_at TEXT NOT NULL CHECK(strftime('%s', started_at) IS NOT NULL AND (substr(started_at, -6) = '+00:00' OR substr(started_at, -1) = 'Z')),
    finished_at TEXT NULL CHECK(finished_at IS NULL OR (strftime('%s',finished_at) IS NOT NULL AND (substr(finished_at,-6)='+00:00' OR substr(finished_at,-1)='Z'))),
    CHECK((status='running' AND finished_at IS NULL) OR (status IN ('complete','partial') AND finished_at IS NOT NULL AND julianday(finished_at)>=julianday(started_at))),
    UNIQUE (plan_hash)
);
CREATE TABLE ingest_items (
    run_id TEXT NOT NULL CHECK(length(run_id) = 82 AND substr(run_id, 1, 18) = 'ingest_run:sha256:' AND substr(run_id, 19) NOT GLOB '*[^0-9a-f]*'),
    item_key TEXT NOT NULL CHECK(length(trim(item_key)) > 0),
    corpus_id TEXT NOT NULL CHECK(length(corpus_id) = 78 AND substr(corpus_id, 1, 14) = 'corpus:sha256:' AND substr(corpus_id, 15) NOT GLOB '*[^0-9a-f]*'),
    relative_path TEXT NOT NULL CHECK(length(relative_path)>0 AND substr(relative_path,1,1)<>'/' AND instr(relative_path, char(92))=0 AND instr(relative_path, ':')=0 AND instr('/'||relative_path||'/', '/../')=0 AND instr('/'||relative_path||'/', '/./')=0 AND instr(relative_path, '//')=0 AND substr(relative_path,-1)<>'/'),
    expected_sha256 TEXT NULL CHECK(length(expected_sha256) = 64 AND expected_sha256 NOT GLOB '*[^0-9a-f]*'),
    file_id TEXT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','processed','skipped','failed')),
    reason_code TEXT NULL CHECK(length(reason_code) BETWEEN 1 AND 64 AND substr(reason_code,1,1) GLOB '[a-z]' AND reason_code NOT GLOB '*[^a-z0-9_]*'),
    error_detail TEXT NULL CHECK(error_detail IS NULL OR (status='failed' AND error_detail='Details omitted; see reason_code.')),
    CHECK(status<>'processed' OR file_id IS NOT NULL),
    CHECK(status NOT IN ('skipped','failed') OR reason_code IS NOT NULL),
    PRIMARY KEY (run_id, item_key),
    FOREIGN KEY (run_id) REFERENCES ingest_runs(run_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (corpus_id) REFERENCES corpora(corpus_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (file_id) REFERENCES source_files(file_id) ON DELETE RESTRICT ON UPDATE RESTRICT
);
CREATE INDEX ingest_items_corpus ON ingest_items(corpus_id);
CREATE INDEX ingest_items_file ON ingest_items(file_id);
