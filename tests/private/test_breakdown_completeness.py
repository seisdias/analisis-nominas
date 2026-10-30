"""Opt-in prepared corpus diagnostic: read-only, no rebuild and no salary output."""

import os
import sqlite3
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

import pytest

from src.analytic_dataset import read_analytic_dataset
from src.breakdown_completeness import diagnose_breakdown
from src.canonical_inspection import open_inspector
from src.cli_config import load_config
from src.component_view import component_restrictions
from src.document_concepts import read_document_concepts
from src.economic_components import project_components
from src.payroll_timeline import classified_timeline
from src.salary_reconciliation import Status


def test_prepared_breakdown_diagnosis_is_read_only():
    supplied = os.environ.get("CANONICAL_RECONCILIATION_TEST_DB")
    if not supplied:
        pytest.skip("Set CANONICAL_RECONCILIATION_TEST_DB to the prepared baseline")
    path = Path(supplied).resolve()
    config = load_config(database=path)
    before = sha256(path.read_bytes()).digest()
    siblings = set(path.parent.iterdir())
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, count in (
            ("logical_documents", 233),
            ("document_versions", 260),
            ("documentary_facts", 38091),
            ("economic_observations", 466),
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (count,)
        assert connection.execute(
            "SELECT DISTINCT eligibility FROM economic_observations"
        ).fetchall() == [("evidence_only",)]
    finally:
        connection.close()
    counts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    with open_inspector(path) as inspector:
        docs = inspector.documents()
        dataset = read_analytic_dataset(inspector)
        sources = {
            d["document_id"]: read_document_concepts(inspector, d["document_id"]) for d in docs
        }
        assert (
            sum(
                d["gross"]["status"] == "certified" and d["net"]["status"] == "certified"
                for d in docs
            )
            == 233
        )
        timeline = classified_timeline(
            inspector.timeline_records(),
            dataset,
            years=(1900, 2100),
            withheld_document_ids=frozenset(config.withheld_document_ids),
        )
        points = project_components(dataset, sources, component_restrictions(timeline.table))
        assert len(points.points) == 113
        assert len(config.withheld_document_ids) == 2
        assert all(
            p.occurrence.document_id not in config.withheld_document_ids for p in points.points
        )
        for identity, document in sources.items():
            for e in document.extractions:
                name = "ALTEN" if e.extractor_name.startswith("alten-") else e.extractor_name
                counts[name]["documents"].add(identity)
                counts[name]["versions"].add(e.version_id)
                counts[name]["extractions"].add(e.extraction_id)
                report = diagnose_breakdown(e)
                for c, d in zip(report.completeness, report.diagnostics):
                    reasons[name].update(c.reasons)
                    if d.calculated is not None:
                        counts[name][c.section.value + ":evaluable"].add(identity)
                        counts[name][c.section.value + ":extractions"].add(e.extraction_id)
                    if d.status == Status.RECONCILED:
                        assert d.difference == 0
                        counts[name][c.section.value + ":reconciled"].add(identity)
                    if d.status == Status.DIFFERENCE:
                        assert d.difference != 0
                        counts[name][c.section.value + ":difference"].add(identity)
        for name, items in sorted(counts.items()):
            no_section = items["documents"] - (
                items["devengos:evaluable"] | items["deducciones:evaluable"]
            )
            print(
                name,
                {k: len(v) for k, v in sorted(items.items())},
                "no_evaluable_section",
                len(no_section),
                "rejections",
                dict(reasons[name]),
            )
    assert sha256(path.read_bytes()).digest() == before
    assert set(path.parent.iterdir()) == siblings
