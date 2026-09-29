-- Documentary provenance only. No active-version selection or economic facts.
CREATE TABLE logical_documents (
    document_id TEXT PRIMARY KEY NOT NULL
        CHECK(length(document_id)=80 AND substr(document_id,1,16)='document:sha256:'
              AND substr(document_id,17) NOT GLOB '*[^0-9a-f]*'),
    corpus_id TEXT NOT NULL REFERENCES corpora(corpus_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    employer_id TEXT NULL REFERENCES employers(employer_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    document_type TEXT NOT NULL CHECK(length(trim(document_type))>0),
    origin_key TEXT NOT NULL CHECK(length(trim(origin_key))>0),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(corpus_id, origin_key)
);
CREATE INDEX logical_documents_employer ON logical_documents(employer_id);

CREATE TABLE document_versions (
    version_id TEXT PRIMARY KEY NOT NULL
        CHECK(length(version_id)=79 AND substr(version_id,1,15)='version:sha256:'
              AND substr(version_id,16) NOT GLOB '*[^0-9a-f]*'),
    document_id TEXT NOT NULL REFERENCES logical_documents(document_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    file_id TEXT NOT NULL REFERENCES source_files(file_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    segment_key TEXT NOT NULL CHECK(length(trim(segment_key))>0),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(document_id, file_id, segment_key)
);
CREATE INDEX document_versions_file ON document_versions(file_id);

CREATE TABLE version_pages (
    version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    page_number INTEGER NOT NULL CHECK(typeof(page_number)='integer' AND page_number>0),
    ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal>=0),
    PRIMARY KEY(version_id, ordinal),
    UNIQUE(version_id, page_number)
);

CREATE TABLE extractions (
    extraction_id TEXT PRIMARY KEY NOT NULL
        CHECK(length(extraction_id)=82 AND substr(extraction_id,1,18)='extraction:sha256:'
              AND substr(extraction_id,19) NOT GLOB '*[^0-9a-f]*'),
    version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    extractor_name TEXT NOT NULL CHECK(length(trim(extractor_name))>0),
    extractor_revision TEXT NOT NULL CHECK(length(trim(extractor_revision))>0),
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64 AND config_hash NOT GLOB '*[^0-9a-f]*'),
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL CHECK(strftime('%s',created_at) IS NOT NULL
        AND (substr(created_at,-6)='+00:00' OR substr(created_at,-1)='Z')),
    UNIQUE(version_id, extractor_name, extractor_revision, config_hash)
);
