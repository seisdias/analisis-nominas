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

The builder does not interpret private manifests. To reproduce certified
exclusions, explicitly list the appropriate manifest entries in private JSON.
Existing processor omissions (such as nonextractable documents) remain unchanged.
There is no new company-specific exclusion logic.

The certified private plan can be expressed by supplying its explicit person and
corpus UUID seeds, aliases/names, `manifest_contract`, processor selectors and
`application_revision`. Merely using the same PDFs with different IDs or metadata
does not reproduce its fingerprint. The builder does not verify private manifest
hashes or assert certification counts. Inspect/verify those separately.

Publication requires zero failed items and successful schema/integrity/FK
verification. A private staging directory on the output filesystem is discarded
on failure, including partial ingestion results. Only a closed successful v8
SQLite is hard-linked to the new output name. Existing files, directories and
symlinks are never overwritten, including a concurrently created destination.
No `--force` exists. Parent directory must already exist and support hard links;
there is no unsafe copy/overwrite fallback. Published file permissions are 0600.

The inspector only reads. The builder never imports the inspector or T7 economic
certification, changes eligibility, applies manual decisions, or adds economic
rules. It invokes only the existing production inventory/ingestion pipeline.
