"""Annual inventory consumes the actual A.3 selection, not amount equality."""

import pytest

from src.annual_summary import annual_summary
from src.canonical_inspection import CanonicalInspector
from src.component_view import component_restrictions
from src.documentary_coverage import Availability, CoverageDocument
from src.payroll_timeline import classified_timeline
from tests.integration import test_version_analysis as fixtures
from tests.integration.test_version_analysis import setup

snapshot = fixtures.snapshot


@pytest.mark.parametrize("resolve", [False, True])
def test_annual_authorized_bonus_occurrences_once(snapshot, resolve):
    d, s, choice = setup(snapshot, resolve=resolve)
    inspector = CanonicalInspector(snapshot[1])
    timeline = classified_timeline(inspector.timeline_records(), (d,), years=(1, 9999))
    y, m = d.documentary_period
    record = CoverageDocument(
        d, d.company_text, y, m, Availability.CERTIFIED, Availability.CERTIFIED
    )
    r = annual_summary(
        (record,),
        {d.document_id: s},
        component_restrictions(timeline.table),
        timeline.points,
        years=(y, y),
    )
    item = r.groups[0].documents[0]
    assert len(r.groups[0].documents) == 1 and r.groups[0].aggregate is None
    if resolve:
        assert item.version_id == choice.version_id
        assert len(item.components) == 3
        assert len({p.amount.fact.fact_id for p in item.components}) == 3
    else:
        assert item.version_id is None and not item.components
