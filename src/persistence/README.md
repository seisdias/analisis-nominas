# Canonical SQLite connection and migrations

Infrastructure only. This package does not import `Nomina`, historical
`DatabaseService`, parsers, UI or domain repositories. There is no default
database path or automatic ingestion. Documentary evidence and versioned economic
interpretations occupy separate tables.

## Opening

```python
from src.persistence import open_database

# Explicit initialization; creates directories/file only in this mode.
with open_database(path, mode="create", application_revision="release-or-build-id") as db:
    assert db.status.current_version == 6

# Existing file only; applies pending known migrations.
with open_database(path, mode="migrate", application_revision="release-or-build-id") as db:
    status = db.status

# Default: existing file, SQLite URI mode=ro, query_only=ON, no migration.
with open_database(path) as db:
    pending = db.status.pending_versions
```

`DatabaseSession.connection` is an infrastructure handle for subsequent adapters,
not a domain contract. A session always closes its connection. Verification holds
a read snapshot until exit. Connections do not implicitly commit caller work;
unfinished explicit transactions are rolled back. `:memory:` requires `create`.

`connect` is the lower-level connection-only API with `create`, `read_write` and
`read_only` modes; it does not verify a schema. Missing paths are rejected in both
noncreating modes. Paths are resolved to escaped file URIs, so `#`, `?`, spaces and
Unicode in filenames are not interpreted as URI parameters. Raw URI input is
rejected. Relative paths are relative to the caller; use absolute paths when the
database location must be independent of cwd. SQL resources never depend on cwd.

## Connection policy

Every connection explicitly sets and verifies:

- `foreign_keys=ON`;
- `busy_timeout=5000` ms by default (injectable positive integer);
- `synchronous=FULL`;
- `query_only=ON` for read-only connections.

Writable disk connections use `journal_mode=DELETE`; memory uses `MEMORY`.
An existing different writable mode (including WAL) is rejected, not silently
converted. Read-only verification does not change the stored journal mode.
WAL, checkpoint management and concurrent writers are not introduced here.
There is no row factory or dependency on team/global SQLite settings.

Python autocommit is explicitly enabled. The runner owns SQL `BEGIN IMMEDIATE`,
`COMMIT` and `ROLLBACK`; it does not rely on sqlite3's implicit transaction defaults.

## Catalog and bootstrap

`sql/0001_schema_migrations.sql` creates the control ledger:

```text
schema_migrations(version PK, checksum, applied_at, application_revision)
```

The file's exact UTF-8 bytes (including line endings) define its SHA256. Resources
are loaded using `importlib.resources`. Catalog versions are positive, unique,
contiguous integers from 1 and sorted numerically, independent of file enumeration.
Injected `Migration` catalogs allow isolated tests and future versions.

A database with no user schema objects is version 0. Migration 1 creates the
control table and inserts its own record **in the same transaction**. There is no
separate bootstrap write. An existing control table without its initial record,
or a nonempty database without the table, is an error. Historical SQLite files
are never adopted or migrated automatically.

Each migration is a separate transaction, including its record and post-checks.
If version 2 fails after version 1 committed, version 1 remains, version 2 is absent,
and a later run can resume. A failed first migration may leave an empty file and
created directories, but no partial schema or migration record. They are not deleted.

SQL is executed statement by statement using `sqlite3.complete_statement` for
boundaries, preserving quoted semicolons, comments and trigger bodies. The runner
does not use `executescript`, which can interfere with transaction ownership.
An authorizer rejects transaction control, savepoints, ATTACH/DETACH, PRAGMAs,
temporary-schema work and mutation of the runner-owned ledger. VACUUM cannot run
inside the transaction. Nontransactional migrations are unsupported; no unsafe
fallback is attempted. Migrations are trusted application resources, not a SQL sandbox.

Before each migration the history is rechecked under the writer lock. Applied
versions are never rerun. Identical reopens do not change timestamps or records.
The UTC timestamp is generated at application; `application_revision` is injected,
defaults to `development`, and never invokes Git.

## Verification and errors

`verify_schema` checks FK activation, control-table columns, contiguous history,
known versions, exact checksums and audit metadata, then runs `integrity_check`
and `foreign_key_check`. Pending versions are returned, not applied in verification.
An empty existing file returns version 0/pending 1, 2, 3, 4, 5 and 6 without bootstrap or writes.

Specific errors distinguish configuration, invalid definitions/history, unknown
future versions, checksum changes, execution failures and integrity failures.
SQLite exceptions arising inside these operations retain their cause and context.
Errors from a caller's own SQL remain the caller's responsibility.

**Engine limit:** SQLite 3.50.4 does not retain CHECK expressions when loading a
natively read-only database. Its read-only `integrity_check` therefore does not
evaluate those constraints, although FK and history checks still run. Verification
does not claim a stronger guarantee than the engine provides. Post-migration checks
use the writable connection and evaluate CHECKs. A caller needing that additional
check on an existing database can call `verify_schema` within `connect(...,
mode="read_write")`, without executing writes or migrations. Tests cover this
distinction rather than replacing read-only access with an implicit writable open.
See SQLite's [schema loading implementation](https://github.com/sqlite/sqlite/blob/version-3.50.4/src/build.c#L1799-L1827).

No backups, downgrades, schema repair, legacy adoption or economic migrations are
implemented. Subsequent migrations must preserve the migration-ledger contract.


## Identity and physical evidence (schema 2)

`sql/0002_identity_and_evidence.sql` adds exactly `persons`, `employers`,
`corpora`, `source_files`, `file_locations`, `ingest_runs`, and `ingest_items`.
It adds no document interpretation or economic tables. All foreign keys use
RESTRICT for both deletion and updates; child lookup indexes accompany them.
Version 1 bytes and checksums remain unchanged. Old infrastructure tests explicitly
inject the v1 catalog; identity/evidence tests inject v2, document tests inject v3, and fact tests inject
v4, and interpretation tests inject v5. Relation tests exercise the current
packaged catalog and upgrade from v5.

Pure frozen records and ID constructors live in `src.canonical.evidence`.
`src.persistence.evidence.EvidenceRepository` takes the infrastructure connection
but its operations accept/return those records (or `None`), never rows/cursors.
Registration returns `WriteOutcome.CREATED` or `IDENTICAL`; divergent immutable
content raises `ReproducibilityConflict`. FK/CHECK violations remain SQLite
integrity errors at this adapter boundary. No persistence is coupled to `Nomina`.

Person/corpus IDs use a UUID seed (generated when omitted); callers retain the ID
or seed for subsequent registrations. Employer identity uses the supplied uppercase
country and exact, unpadded tax ID; no name matching, case folding or punctuation
removal guesses legal equivalence. Without tax ID an employer uses a UUID seed.
A file ID depends solely on its lowercase SHA256. Copies share a file and may have
multiple locations. Different files can occupy the same relative path. Paths are
normalized relative POSIX paths; original filenames must be basenames.
No file bytes or real corpus are read by this adapter.

Timestamps are explicit UTC ISO 8601 strings with UTC defaults on new records.
Identical registrations ignore newly supplied operational timestamps and preserve
the first persisted value. Contradictory metadata, including availability, is not
silently updated. Future availability decisions are outside this increment.

Ingestion plans have contract version 1 and use the existing canonical serialization
version 1. Plans accept null, booleans, integers, text, lists and string-keyed maps;
floats and economic typed values are outside this plan contract. JSON envelope,
type tags, canonical spelling/order, SHA256 and run identity are all validated.
`IngestRun.from_plan` builds them without exposing SQL. A plan hash identifies one
inventory run, not every process attempt; retries/attempt orchestration is deferred.

`register_item` records inventory. `update_item` explicitly updates a pending item
while its run is running; immutable identity fields cannot change. Terminal items
cannot be overwritten, but repeating identical updates is allowed. Processed items
require a physical file; when an expected hash exists it must match the linked file.
Skipped/failed items require a machine reason code. All free-form error detail is
replaced with `Details omitted; see reason_code.`: redacting only paths would not
reliably remove personal data. No raw exception or traceback is persisted.
`finish_run` records complete/partial with a UTC completion time. Complete cannot
contain pending/failed items; terminal runs cannot gain items or change status.
A repeated same-status finish preserves its original timestamp.

Every write uses a savepoint; `repository.transaction()` groups writes atomically,
including rollback on conflicts. Nested units compose with caller-owned transactions.
Inventory does not execute parsers or ingest a real corpus. It does not resolve
versions, interpret ALTEN or calculate KPIs.


## Documents and extractions (schema 3)

`sql/0003_documents_and_extractions.sql` adds only `logical_documents`,
`document_versions`, `version_pages` and `extractions`. Earlier migration bytes
remain unchanged. The same FK RESTRICT and immutable-registration policies apply.

Pure frozen records and helpers are in `src.canonical.documents`; the existing
`EvidenceRepository` registers/queries them and reuses its transactional writes.
No new connection, hashing or serialization infrastructure is introduced.

- `document_id(corpus_id, origin_key)` identifies a source-established logical unit.
  Origin keys are nonempty, stable, opaque keys within their corpus, not inferred
  from employer/month, filename or economic values. Type and optional employer
  are metadata; incompatible repetitions conflict rather than silently updating.
- `version_id(document_id, file_id, segment_key)` identifies a logical unit's
  physical source and scope. The segment key is supplied explicitly, even for a
  whole-file scope. One PDF can back different documents and segments. No version
  is selected as active, latest or preferred.
- `VersionPage` associates known one-based physical pages with nonnegative order
  positions. `(version_id, ordinal)` is the primary key; `(version_id, page_number)`
  is unique. Retrieval orders by ordinal, not page number. Missing page evidence
  is represented by no association, never a fabricated page 1. Ordinal gaps are
  allowed; absence of rows does not claim an empty PDF. Known `page_count` bounds
  are checked by the repository; unknown counts do not fabricate bounds. The same
  physical page may support multiple versions.
- `extraction_id(version_id, extractor_name, extractor_revision, config_hash)`
  identifies a reproducible extraction invocation. `content_hash` is its asserted
  output digest, deliberately outside identity: a different output under the same
  inputs raises `ReproducibilityConflict`. No output payload or facts are stored.

ID helpers normalize referenced canonical IDs to their string representation before
hashing, so typed IDs and strings read back from storage give identical identities.
All three timestamped registrations retain the first `created_at` on repetition.
Page associations also reject incompatible reuse of an ordinal or physical page.
Group chain registration in `repository.transaction()` for all-or-nothing writes.
Methods return frozen contracts, ordered tuples, or write outcomes, never SQL rows.
This increment neither imports corpus documents nor adapts `Nomina`.


## Documentary facts (schema 4)

`0004_documentary_facts.sql` adds only `documentary_facts` and `fact_pages`.
`src.canonical.facts` defines immutable `FactDraft`, `DocumentaryFact` and `FactPage`.
A draft is one stable field key and one existing `CanonicalValue`; binding it to an
extraction produces `fact_id(extraction_id, fact_key)`. The value is deliberately
excluded from identity. Different content under that identity is a reproducibility
conflict; no classification, observation or derived amount is introduced.

Values use a nullable kind (`decimal`/`text`), signed INTEGER coefficient, INTEGER
scale and TEXT value. No REAL is used. SQL checks mirror value/state combinations,
normalized decimals, currency format and required reasons. All seven existing
states round-trip, including unreliable candidates or no candidate. Currency NULL
means unknown currency and never defaults to EUR. Created timestamps survive
identical registrations. Fact queries order by key, independently of insertion.

`EvidenceRepository` adds register/get/query facts and associate/query fact pages,
using the same savepoint transaction infrastructure. Page association is explicit:
it requires a known page in the fact's extraction version. The repository obtains
the version from the existing chain, not caller guesses. `fact_pages` stores that
version for a restrictive composite FK to `version_pages`; its fact FK is also
restrictive. Therefore referenced page evidence cannot be deleted or reassigned.
The repository enforces that the stored version belongs to the fact's extraction;
FKs independently enforce both endpoints. Raw SQL is not a substitute for this
cross-chain repository check. Empty associations mean no exact supporting page is
recorded, even when the encompassing document has known pages. No page assignment
is performed by the adapter. Query results are ordered by physical page number.

## Legacy Nomina adapter (nomina-facts/v1)

`src.nomina_facts.adapt_nomina` is outside parsers and pure canonical contracts.
It returns deterministic drafts, without a connection, extraction ID, timestamp or
page assignment. Callers bind drafts to an extraction and persist separately; the
adapter revision must identify this projection in extraction metadata. It accepts
only `Nomina`, not standalone `Finiquito` or `CertificadoRetenciones` instances.

Keys `nomina.<field>` cover all 33 scalar stored fields (including the nine inherited
fields). They preserve identifiers, employer/CIF, year/month/period, type, processable
flag, notes, categories, intervals/dates, components, printed totals and bases.
`total_deducciones` is a calculated property and is deliberately never accessed.
All 11 fields of each `ConceptoNomina` are copied, including code, label, parser
category, column, amount, original amount text, atraso flag, percentage, units,
price and base. The adapter neither interprets these labels nor reconciles totals.

Concept keys are `nomina.conceptos.<group-hash>.<occurrence>.<field>`, with the group
hash over the exact code and column. Occurrence is zero-based within that group;
it never depends on amount and is unaffected by insertion in unrelated groups.
There is no individual concept ID or location in the legacy model. Reordering
entries with the same code/column can change their correspondence: the adapter
cannot infer stable identities across that change. `source_position` preserves the
original list position as metadata, not identity. Empty concept lists yield no
concept facts and do not prove that the PDF contains no concepts.

Legacy uncertainty is preserved explicitly:

- `None` becomes UNKNOWN with `legacy.absence_unspecified`, never NOT_PRESENT.
- Zero in a decimal field remains an exact zero candidate, marked UNRELIABLE with
  `legacy.zero_origin_unknown`: a supplied zero cannot be distinguished from the
  model's zero default. It is never converted into absence.
- Other stored values are PRESENT with `legacy.normalized_value`. PRESENT asserts
  observation in the normalized model, not independent evidence of printed text.
- Text, including empty text, is copied; enum values and boolean flags use their
  explicit textual representations. Year/month and source position are exact integers.
- Currency is unknown unless supplied explicitly from documentary evidence. Such a
  supplied currency applies only to fields with monetary units, not percentages,
  unit counts, dates or labels; this is not an aggregation classification.

The legacy model stores floats. Conversion uses `Decimal(str(float))`, the shortest
round-trip decimal spelling, then the certified exact-decimal constructor, without
quantization or rounding. This cannot recover pre-float precision or original PDF
spelling. Non-finite numbers, excessive scale or coefficient overflow fail explicitly.
Original `importe_texto` is independently retained; disagreement with `importe`
is not repaired. The adapter computes no payroll sums, differences or economic
classification, and never selects or deduplicates documents/versions.


## Versioned interpretation (schema 5)

`0005_economic_observations.sql` adds exactly `rules`, `assessments`,
`economic_observations` and `observation_facts`. All foreign keys use RESTRICT on
update/delete. No new economic triggers, aggregation, duplicate resolution or
corpus ingestion is introduced. `src.canonical.economics` contains pure contracts;
`src.persistence.economics.EconomicRepository` extends the existing repository to
reuse connections, documentary lookups and savepoint transactions.

A rule ID depends on family, name, declared version and implementation SHA256.
Changed implementation bytes therefore produce a distinct rule even if a caller
retains the declared version. The direct mapping rule fingerprints the exact
packaged `src/economic_mapping.py` resource, independently of cwd; synthetic rules
can provide an explicit implementation hash. The hash identifies that module, not
a snapshot of the entire Python environment. Rule execution is separate from SQL.

An assessment ID depends on logical document, rule and input signature. A sorted,
unique JSON manifest stores every input fact ID and its content fingerprint. That
fingerprint includes extraction ID, field key and full canonical value, including
state, currency and reason, but excludes operational timestamps. The signature
uses the existing versioned canonical serialization, so input order is irrelevant.
The repository verifies recorded fact content and membership in the assessed
logical document before accepting assessments or observations. Manifest entries
are JSON rather than a fifth table; their existence/content checks are repository
invariants. Normal repository APIs cannot edit/delete input facts; raw SQL must not
be treated as an equivalent interface for preserving these invariants.

Assessment states are usable, pending, ambiguous, excluded and incomplete.
Assessment status is immutable for one identity. A later different interpretation
requires distinct inputs or rule identity, not overwriting the earlier evaluation.
An empty input set can be pending/incomplete, but cannot be usable.

Each observation identifies one magnitude with a stable key within its assessment.
It stores independent scope, nature, pay behavior, temporal character, payment
form, settlement context, status, eligibility and confidence. Open text nature and
magnitude labels do not establish a complete cross-company taxonomy. Numeric
values use the existing CanonicalValue and INTEGER coefficient/scale, never REAL;
all absence states and unreliable decimal candidates remain distinguishable.
Usable requires a present value. Candidate additionally requires a usable parent
assessment; excluded assessments cannot yield eligible observations. Candidate
is not permission to include anything in a KPI: there is no aggregation here.

Liquidation month, accrual interval and payment date each have separate states
and reasons. PRESENT requires valid ISO values; UNKNOWN does not carry invented
dates, NOT_APPLICABLE requires a reason, and UNRELIABLE can retain a candidate.
An accrual candidate requires both ordered ISO endpoints. Partially known dates
remain documentary evidence until a rule can provide an interval; payroll month
is never expanded into a worked-month interval. Unknown currency remains unknown.

`register_observation(observation, fact_ids)` atomically creates both the row and
a nonempty, immutable N:M support set. Supporting facts must be assessment inputs.
Repeating an equivalent registration preserves its timestamp and returns identical;
a different value, dimension or support set conflicts. There is no bare-observation
write API and no later append-link operation that could silently change meaning.
Reads return typed observations with their sorted fact IDs. SQL foreign keys protect
both endpoints of every link; nonempty support and cross-document consistency are
repository invariants, not complex triggers. Explicit `repository.transaction()`
can group rule, assessment, observations and links into a single atomic operation.

### First rule: documentary_mapping / direct_totals / 1

`evaluate_direct_totals(document_id, facts)` uses only caller-supplied facts; it
does not scan documents or select versions. It requires both real field keys:

- `nomina.total_devengado` -> `documentary_gross`;
- `nomina.liquido_percibir` -> `documentary_net`.

With PRESENT decimal values from one extraction, it copies those values unchanged
into two total-scope observations with confidence mapped and eligibility
evidence_only. Nature, pay behavior, temporal character, payment form, settlement
context and every time axis stay unknown. These are documentary gross/net amounts,
not annual salaries, employer costs or amounts approved for aggregation.

Multiple input extractions produce ambiguous with no observations, even if their
amounts agree. Repeated fact identities are rejected, not deduplicated. Missing
keys or nonnumeric target values produce incomplete; target absence/uncertainty
produces pending. In particular, a legacy UNRELIABLE zero never becomes a reliable
zero. A documentary PRESENT zero remains present. The pair requirement is a
conservative completeness condition for this first rule, not a claim that an
isolated total can never be interpretable by a future separate rule.

No sums, annualization, extra-pay inclusion, tax/SS interpretations, fixed/variable
classification, settlements, duplicate resolution, version preference, ALTEN,
KPI calculation or updates to documentary facts are implemented.


## Explicit relations and candidate selection (schema 6)

`0006_economic_relations.sql` adds only `document_relations` and
`observation_relations`. Their immutable contracts live in `src.canonical.relations`;
`RelationRepository` extends existing transactional repositories. Both tables store
source, target, type, optional rule FK, optional reason code and created timestamp.
At least rule or reason is mandatory; all FKs are restrictive. Self-relations are
rejected by both Python and SQL. There is no generic graph or human-decision table.

Relation identity is determined by endpoints and type, with separate namespaces
for documents and observations. Rule/reason are content, not identity: incompatible
assertions for the same relation conflict rather than creating an unnoticed second
assertion. Identical repetition retains the original timestamp.

Directions are explicit:

| Entity | Type | Meaning of source -> target |
|---|---|---|
| Document | supersedes | replacement document -> superseded document |
| Document | duplicate_of | symmetric assertion of duplication, no preferred representative |
| Document | complements | symmetric complementary documents, no addition instruction |
| Document | same_logical_unit_pending_reconciliation | symmetric unresolved pairing |
| Observation | replaces | replacement observation -> replaced observation |
| Observation | contained_in | component/contained observation -> containing observation |
| Observation | adjusts | adjustment -> adjusted observation |
| Observation | complements | symmetric complementary observations |

Symmetric endpoints are sorted as canonical ID strings in the contract and checked
in SQL. Reversing such an assertion produces the same ID and stored row; ordering
is only storage normalization, never selection of a preferred document. Directed
relations retain both direction and distinct IDs when reversed.

`src.candidate_selection.select_candidates` reads the complete stored set under
one snapshot using a typed protocol. It returns typed evidence plus a per-observation
selection status/reason. It does not persist these outcomes or change economic
statuses, eligibility, assessments, facts or relations. It works on read-only SQLite.

Basic admissibility requires a usable assessment, usable economic status, explicit
candidate eligibility, a PRESENT exact decimal, nonempty support included in the
assessment manifest, verified fact fingerprints and matching logical-document
provenance. More than one source version within an assessment remains ambiguous.
No exact page is invented or required when only documentary scope is known.
Currency and confidence remain as recorded; candidate selection is not approval
for adding amounts, mixing currencies or accepting inference in any future KPI.

V5 has no active-assessment pointer. Remaining candidate-producing assessments for
one logical document compete: if more than one remains, their observations are
ambiguous. Dates, IDs, equal amounts and insertion order never establish an active
assessment. Sorting returned results by ID is solely deterministic presentation.

Only explicit exclusion/substitution effects are applied:

- `supersedes` disqualifies observations of the target document. The source must
  independently pass admissibility; recording the relation does not promote it.
- `replaces` disqualifies the target observation. An inadmissible replacement does
  not reactivate the old one. Each explicitly replaced target stays out, including
  cycles; there is no general cycle repair or graph resolution.
- Multiple admissible successors/replacements for a single target remain ambiguous.
  All overlapping disputes are collected before applying their deferrals; iteration
  order must not leave an arbitrary surviving source.
- A symmetric duplicate assertion with neither document explicitly superseded leaves
  both sides ambiguous. A pending-reconciliation pairing leaves them pending. A
  document already explicitly superseded stays excluded, without using the symmetric
  edge to designate a winner. Conflicting unresolved document evidence can therefore
  still block an observation-level replacement from becoming a candidate.
- `contained_in`, `adjusts` and either kind of `complements` do not remove a side or
  change amounts. Both sides can remain candidates; that does not mean both may be
  aggregated. Containment/additivity policy is deliberately unimplemented.

Excluded/evidence-only observations are never promoted. Pending, ambiguous and
incomplete assessments remain deferred. Input fingerprint failures become pending;
malformed stored records or missing support fail the read closed rather than return
partially trusted candidates. All of these are selection diagnostics, not human
resolution decisions. There is no duplicate inference, version-by-date selection,
extra-pay policy, annual total, aggregation, KPI, ALTEN logic or real-corpus ingestion.
