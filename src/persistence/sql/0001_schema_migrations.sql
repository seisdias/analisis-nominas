CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY NOT NULL CHECK (version > 0),
    checksum TEXT NOT NULL CHECK (
        length(checksum) = 64 AND checksum NOT GLOB '*[^0-9a-f]*'
    ),
    applied_at TEXT NOT NULL CHECK (length(trim(applied_at)) > 0),
    application_revision TEXT NOT NULL CHECK (length(trim(application_revision)) > 0)
);
