"""Synthetic, read-only analytical projection; no economic aggregation."""
from dataclasses import replace

import pytest

from src.analytic_dataset import DocumentCategory, load_analytic_dataset
from src.canonical.documents import DocumentVersion, version_id
from src.canonical.values import CurrencyCode, ExactDecimal
from src.persistence import open_database
from src.persistence.economics import EconomicRepository
from tests.integration.persistence import test_canonical_inspector as inspector_tests


@pytest.fixture
def dataset(tmp_path, request):
    return getattr(inspector_tests.dataset, '__wrapped__')(tmp_path, request)


def test_unknown_and_read_only(dataset):
    path = dataset[0]
    before = path.read_bytes()
    records = load_analytic_dataset(path)
    assert records == load_analytic_dataset(path)
    assert len(records) == 1
    row = records[0]
    assert row.category == DocumentCategory.UNCLASSIFIED
    assert row.gross is not None
    assert row.net is not None
    assert row.resolved_version_id is None
    assert row.eligibilities == ('evidence_only',)
    assert len(row.observations) == 3
    assert len({o.observation_id for o in row.observations}) == 3
    assert row.provenance[0].file_sha256 == 'a'*64
    assert row.observation_facts
    assert path.read_bytes() == before


@pytest.mark.parametrize(('kind', 'category'), [
    ('NOMINA_ORDINARIA', DocumentCategory.ORDINARY),
    ('PAGA_EXTRA', DocumentCategory.EXTRA),
    ('FINIQUITO', DocumentCategory.SETTLEMENT),
    ('VARIABLE_BONUS', DocumentCategory.OTHER),
    ('CERTIFICADO_RETENCIONES', DocumentCategory.OTHER),
    ('MANUAL_ESCANEADO', DocumentCategory.UNCLASSIFIED),
    ('benefits?', DocumentCategory.UNCLASSIFIED),
])
def test_explicit_type_only(dataset, kind, category):
    # Synthetic fixture change, never a production migration.
    import sqlite3
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('UPDATE logical_documents SET document_type=?', (kind,))
    row = load_analytic_dataset(dataset[0])[0]
    assert row.category == category
    assert row.original_document_type == kind
    assert row.classification_document_id == dataset[1].document_id


def test_multiple_versions_never_select_or_reuse_unique_observation(dataset):
    import sqlite3
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        original = repo.get_document_versions(dataset[1].document_id)[0]
        repo.register_version(DocumentVersion(
            version_id(original.document_id, original.file_id, 'alternative'),
            original.document_id, original.file_id, 'alternative'))
        conn.commit()
    row = load_analytic_dataset(dataset[0])[0]
    assert row.resolved_version_id is None
    assert row.gross is row.net is None
    assert 'multiple_versions' in row.diagnostics
    assert len(row.provenance) == 2


def test_empty_dataset(tmp_path):
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    assert load_analytic_dataset(path) == ()


def add_document(dataset, key, month, *, currencies=('EUR', 'EUR'), amounts=True, conflict=False):
    """Build explicit evidence using canonical APIs, never a private corpus."""
    import sqlite3

    from src.canonical.documents import Extraction, LogicalDocument, document_id, extraction_id
    from src.canonical.facts import DocumentaryFact, FactDraft
    from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
    from src.economic_mapping import evaluate_direct_totals

    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        original = repo.get_document_versions(dataset[1].document_id)[0]
        doc = LogicalDocument(document_id(dataset[1].corpus_id, key), dataset[1].corpus_id,
                              None, 'NOMINA_ORDINARIA', key)
        repo.register_document(doc)
        version = DocumentVersion(version_id(doc.document_id, original.file_id, key),
                                  doc.document_id, original.file_id, key)
        repo.register_version(version)
        ext = Extraction(extraction_id(version.version_id, 'synthetic', '1', 'b'*64),
                         version.version_id, 'synthetic', '1', 'b'*64, 'c'*64)
        repo.register_extraction(ext)
        values = {
            'empresa': CanonicalValue(state=ValueState.PRESENT, value='Synthetic employer'),
            'anio': CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(2025, 0)),
            'mes': CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(month, 0)),
            'tipo': CanonicalValue(state=ValueState.PRESENT,
                                  value='PAGA_EXTRA' if conflict else 'NOMINA_ORDINARIA'),
        }
        if amounts:
            for field, code in zip(('total_devengado', 'liquido_percibir'), currencies, strict=True):
                values[field] = CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 2),
                                               currency=CurrencyCode(code))
        facts = tuple(DocumentaryFact.from_draft(ext.extraction_id, FactDraft('nomina.' + k, v))
                      for k, v in values.items())
        for fact in facts:
            repo.register_fact(fact)
        interpretation = evaluate_direct_totals(doc.document_id, facts)
        repo.register_rule(interpretation.rule)
        repo.register_assessment(interpretation.assessment)
        for item in interpretation.observations:
            repo.register_observation(item.observation, item.fact_ids)
        conn.commit()
    return doc.document_id


def test_chronology_and_period_distinction(dataset):
    later = add_document(dataset, 'later', 12)
    earlier = add_document(dataset, 'earlier', 1)
    records = load_analytic_dataset(dataset[0])
    assert [r.document_id for r in records] == [earlier, later, dataset[1].document_id]
    assert records[0].documentary_period == (2025, 1)
    assert all(p.state == 'unknown' for p in records[0].economic_liquidation_periods)
    assert records[0].gross is not None
    assert isinstance(records[0].gross.value, ExactDecimal)
    assert records[0].gross.value.coefficient == 0
    assert records[0].currency == CurrencyCode('EUR')
    assert len(records[0].context_facts) == 4
    assert all(o.eligibility == 'evidence_only' for r in records for o in r.observations)


def test_currency_conflict_preserves_original_amount_currencies(dataset):
    identity = add_document(dataset, 'currency', 1, currencies=('EUR', 'USD'))
    row = next(r for r in load_analytic_dataset(dataset[0]) if r.document_id == identity)
    assert row.currency is None
    assert row.gross is not None and row.net is not None
    assert row.gross.currency == CurrencyCode('EUR')
    assert row.net.currency == CurrencyCode('USD')
    assert 'incompatible_currencies' in row.diagnostics


def test_missing_amount_and_conflicting_type(dataset):
    identity = add_document(dataset, 'missing', 1, amounts=False, conflict=True)
    row = next(r for r in load_analytic_dataset(dataset[0]) if r.document_id == identity)
    assert row.category == DocumentCategory.UNCLASSIFIED
    assert 'type_conflict' in row.diagnostics
    assert row.original_document_type == 'NOMINA_ORDINARIA'
    assert row.gross is row.net is None
    assert row.observations == ()
    assert row.eligibilities == ()


def test_duplicate_observation_is_ambiguous_not_summed(dataset):
    import sqlite3

    from src.canonical.economics import observation_id

    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        evidence = repo.get_observation(dataset[2].observation_id)
        assert evidence is not None
        old = evidence.observation
        repo.register_observation(replace(old, observation_key='alternative',
            observation_id=observation_id(old.assessment_id, 'alternative')), evidence.fact_ids)
        conn.commit()
    row = load_analytic_dataset(dataset[0])[0]
    assert 'ambiguous_observations' in row.diagnostics
    assert (row.gross if old.magnitude == 'documentary_gross' else row.net) is None
    assert len(row.observations) == 4
