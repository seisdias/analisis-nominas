"""Opt-in, read-only certification against the prepared C.4.1 baseline; no rebuild."""
import os
from hashlib import sha256
from pathlib import Path

import pytest

from src.cli_config import load_config
from src.documentary_coverage import load_coverage, summarize_coverage


def test_prepared_coverage_baseline_is_read_only():
    supplied = os.environ.get('CANONICAL_COVERAGE_TEST_DB')
    if not supplied:
        pytest.skip('Set CANONICAL_COVERAGE_TEST_DB to an explicitly prepared baseline')
    path = Path(supplied).resolve()
    config = load_config(database=path)
    before = sha256(path.read_bytes()).digest()
    siblings = set(path.parent.iterdir())
    records = load_coverage(path, withheld_document_ids=config.withheld_document_ids)
    years = [d.year for d in records if d.year is not None]
    report = summarize_coverage(records, years=(min(years), max(years)))
    assert len(report.document_ids) == len(set(report.document_ids)) == 233
    assert sum(len(d.document.provenance) for d in records) == 260
    assert sum(len(d.document.observations) for d in records) == 466
    assert len(report.certified_both) == 233
    assert len(report.analytic_gross) == len(report.analytic_net) == 208
    assert len(report.multiversion_ids) == 25
    assert len(report.restricted_ids) == 2
    assert set(report.restricted_ids) <= set(report.certified_both)
    assert {e for d in records for e in d.document.eligibilities} == {'evidence_only'}
    assert sum(len(g.document_ids) for g in report.groups) == 233
    assert sha256(path.read_bytes()).digest() == before
    assert set(path.parent.iterdir()) == siblings
