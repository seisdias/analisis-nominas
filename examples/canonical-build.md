# Canonical builder (developer tool)

```sh
python -m src.canonical_builder --config /path/build.json --output /path/new.sqlite
python -m src.canonical_inspector --db /path/new.sqlite summary
```

`canonical-build.sample.json` is a nonprivate configuration template, not a real
corpus plan. No new dependencies are required. Place real configuration under
already-ignored `data/private/` or outside the repository. Do not publish source
filenames or private directory paths.

Configuration version 1 requires:

- `application_revision`: explicit stable revision label stored in the schema
  ledger; use the same label for equivalent rebuilds.
- `person.seed`: explicit UUID passed to existing `person_id`; `alias` is local,
  not a legal name or identifier.
- `corpora`: nonempty list, each with a distinct UUID `seed` and distinct `name`.
  Seeds use existing `corpus_id`; list position never defines identity.
- `source`: directory, absolute or relative to the JSON file (not the working
  directory). Every corpus must contain at least one inventoried PDF.
- `manifest_contract`: explicit label for the input contract.
- `processor`: `{"kind":"ordinary","parser":"coritel"}` or
  `{"kind":"alten"}`. Ordinary selectors go to the existing ParserFactory.
  Corpus name is independent: e.g. name `insis4`, parser selector `insis`.
- Optional `exclusions`: exact relative POSIX paths and existing reason codes:
  `[{"path":"excluded.pdf","reason_code":"declared_out_of_scope"}]`.
  Each exclusion must match an inventoried PDF; no globs or filename inference.
  Explicit exclusions are supported for ordinary corpora only. For ALTEN, omit
  this field or use `[]`; even an explicit `annual_certificate` exclusion prevents
  publication.

The builder does not interpret private manifests. For ordinary corpora, reproduce
certified exclusions by explicitly listing the appropriate manifest entries in
private JSON; existing processor omissions remain supported.

ALTEN A.2 requires a complete inventory. The existing ALTEN processor may skip
recognized annual certificates (`annual_certificate`). Any other skipped source,
including a PDF without extractable text (`no_extractable_text`), prevents
publication, as does any failed source. The builder inventories the configured
ALTEN roots again after ingestion: added, removed or changed PDFs also prevent
publication. These restrictions ensure that a partial inventory cannot make a
multiversion document appear to have a single version.

## ALTEN A.2 projection

After the complete ingestion run succeeds, and before publication, the builder
runs `alten-economic-projection/v1`. It counts all stored versions of each logical
ALTEN document in the completed corpus. Only documents with exactly one version
are projected. Multiversion documents receive no projection extraction or economic
observations, even when their amounts agree; no version is selected or resolved.

For each supported single-version document, the phase adds:

- A separate projection extraction with new deterministic identifiers, bound to
  the source extraction, its facts and fingerprints, physical pages, ingestion
  run and projection implementation.
- Direct aliases from `payload/total_devengado` and `payload/liquido_percibir` to
  `nomina.total_devengado` and `nomina.liquido_percibir`, plus available documentary
  context (company, CIF, year, month, start/end dates and document type) and
  provenance facts. Exact values, states, currency and page references are
  retained. Original facts, identifiers, fingerprints and `UNRESOLVED` state are
  neither removed nor replaced. Concepts are not projected or summed.
- An assessment using the existing `documentary_mapping/direct_totals/1` rule,
  which is registered in the database if not already present. If both totals
  satisfy that rule, two observations are created: documentary gross and net,
  with `eligibility=evidence_only`. Missing or unusable totals yield an incomplete
  or pending assessment without observations; single-version status alone does
  not guarantee certification.

The existing economic certification contract evaluates these observations when
queried. Valid support permits documentary-value certification, without granting
aggregation eligibility or certifying unknown contextual data. No currency,
employer identity or economic period is inferred. Documentary company and period
remain available to the explorer through the projected context facts.

Source extraction, fingerprint and page-support validation failures abort the
build. The projection is a fresh-build finalization phase, not an incremental
ingestion operation. It leaves the certified parsers, original documentary
evidence and other companies' economic behavior unchanged.

## Reproducibility and publication

The certified private plan can be expressed by supplying its explicit person and
corpus UUID seeds, aliases/names, `manifest_contract`, processor selectors and
`application_revision`. Merely using the same PDFs with different IDs or metadata
does not reproduce its fingerprint. The builder does not verify private manifest
hashes or assert certification counts. Inspect/verify those separately.

Publication requires zero failed items, successful schema/integrity/FK
verification and, for ALTEN, successful completion of the inventory checks and
projection described above. A private staging directory on the output filesystem is discarded
on failure, including partial ingestion results. Only a closed successful v8
SQLite is hard-linked to the new output name. Existing files, directories and
symlinks are never overwritten, including a concurrently created destination.
No `--force` exists. Parent directory must already exist and support hard links;
there is no unsafe copy/overwrite fallback. Published file permissions are 0600.

The inspector only reads. The builder runs production inventory/ingestion and
the ALTEN finalization phase. It persists projection extractions, facts,
assessments, the existing direct-totals rule and any resulting observations; it
does not define a new certification rule. It never imports the inspector or T7
economic certification, promotes eligibility or applies manual decisions.
