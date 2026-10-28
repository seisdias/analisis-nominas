"""Explicit component presentation contracts; synthetic values only."""
from dataclasses import replace

import pytest

from src.analytic_dataset import DocumentCategory as C
from src.analytic_dataset import VersionProvenance
from src.canonical.values import CurrencyCode, ValueState
from src.document_concepts import DocumentConcepts, project_extraction
from src.economic_components import component_rows, project_components
from tests.unit.test_document_concepts import DOC, EXT, VER, fact
from tests.unit.test_payroll_timeline import analytic


def example(*, parser='alten-legacy-evidence', code='9122', label='Bono',
            category='bono', column='devengos', arrears='false', amount=12345,
            state=ValueState.PRESENT, count=1):
    fs=[]
    for n in range(count):
        prefix=f'payload/conceptos/{n}/'
        fs += [fact(prefix+k,v) for k,v in [('codigo',code),('concepto',label),
               ('categoria',category),('columna',column),('atraso',arrears)]]
        if amount is not None:
            fs.append(fact(prefix+'importe',amount if state in (ValueState.PRESENT,ValueState.UNRELIABLE) else None,state=state))
    ext=project_extraction(DOC,VER,EXT,fs,pages={f.fact_id:(2,) for f in fs},
                           extractor_name=parser,extractor_revision='synthetic')
    source=DocumentConcepts(DOC,(VER,),(ext,))
    doc=replace(analytic(DOC,C.ORDINARY),original_document_type='NOMINA_ORDINARIA',
                provenance=(VersionProvenance(VER,'file','a'*64,(2,),(EXT,)),))
    return doc,source


def run(doc,source,blocked=None):
    return project_components((doc,),{doc.document_id:source},blocked or {})


@pytest.mark.parametrize('args,expected',[
    ({},'Bonus / variable'),
    ({'code':'9030','label':'Bono/Variable','category':'variable'},'Bonus / variable'),
    ({'parser':'InecoParser','code':'9032','label':'paga extra vera','category':'paga_extra_incluida'},'Extra de verano incluida'),
    ({'parser':'InecoParser','code':'9033','label':'paga extra navi','category':'paga_extra_incluida'},'Extra de Navidad incluida'),
    ({'parser':'ExcelticParser','code':'1','label':'P.P.EXTRA','category':'paga_extra_incluida'},'Prorratas de extras'),
    ({'parser':'AltranParser','code':'R1X','label':'Parte Proporcional Pagas Extras','category':'paga_extra_incluida'},'Prorratas de extras'),
    ({'code':'9016','label':'P.P. Extra Verano','category':'paga_extra_incluida'},'Prorratas de extras'),
    ({'code':'9017','label':'P.P. Extra Navidad','category':'paga_extra_incluida'},'Prorratas de extras'),
    ({'parser':'InecoParser','code':'9RPE','label':'r. pext dic 2012','category':'regularizaciones'},'Ajustes de extras'),
])
def test_explicit_contract_and_original_trace(args,expected):
    doc,source=example(**args)
    result=run(doc,source)
    assert len(result.points)==1 and result.points[0].component==expected
    point=result.points[0]
    assert point.occurrence is source.extractions[0].concepts[0]
    assert point.amount.pages==(2,)
    row=component_rows(result.points)[0]
    assert row['Periodo del documento']=='01/2025'  # label may mention another year
    assert row['Documento']==DOC and row['Versión']==VER and row['Extracción']==EXT
    assert row['Clave original'].endswith('/importe') and row['Importe exacto']=='123,45'
    assert row['Estado']=='Disponible' and row['Moneda canónica']=='No acreditada'
    assert doc.category==C.ORDINARY and doc.observations==()


@pytest.mark.parametrize('changes',[
    {'parser':'other'}, {'code':'x'}, {'label':'bonus probable'}, {'category':'other'},
    {'column':'deducciones'}, {'column':'cotizacion'}, {'arrears':'true'},
    {'amount':None}, {'state':ValueState.UNKNOWN}, {'state':ValueState.UNRELIABLE},
])
def test_no_heuristic_or_unreliable_amount(changes):
    doc,source=example(**changes)
    assert not run(doc,source).points


def test_repeated_codes_negative_amounts_and_determinism_no_aggregation():
    doc,source=example(count=2,amount=-12345)
    result=run(doc,source)
    assert len(result.points)==2
    assert len({p.occurrence.occurrence for p in result.points})==2
    assert {r['Importe exacto'] for r in component_rows(result.points)}=={'-123,45'}
    reverse=replace(source,extractions=(replace(source.extractions[0],concepts=tuple(reversed(source.extractions[0].concepts))),))
    assert run(doc,reverse)==result


@pytest.mark.parametrize('change', ['multi','extractions','missing','period','company','type','identity','hold','currency','provenance'])
def test_document_guards(change):
    doc,source=example()
    blocked={}
    if change=='multi':
        doc=replace(doc,provenance=doc.provenance+(replace(doc.provenance[0],version_id='v2'),))
    elif change=='extractions':
        source=replace(source,extractions=source.extractions+source.extractions)
    elif change=='missing':
        source=replace(source,extractions=())
    elif change=='period':
        doc=replace(doc,documentary_period=None)
    elif change=='company':
        doc=replace(doc,company_text=None)
    elif change=='type':
        doc=replace(doc,category=C.UNCLASSIFIED)
    elif change=='identity':
        doc=replace(doc,classification_document_id='other')
    elif change=='hold':
        blocked={DOC:'Restricción local'}
    elif change=='currency':
        c=source.extractions[0].concepts[0]
        attrs=tuple((k,replace(e,fact=replace(e.fact,value=replace(e.fact.value,currency=CurrencyCode('USD'))))) if k=='importe' else (k,e) for k,e in c.attributes)
        source=replace(source,extractions=(replace(source.extractions[0],concepts=(replace(c,attributes=attrs),)),))
    else:
        source=replace(source,version_ids=('other',))
    result=run(doc,source,blocked)
    assert not result.points and result.omitted


def test_scalar_prorrata_is_never_a_component():
    doc,source=example()
    ext=project_extraction(DOC,VER,EXT,[fact('payload/prorrata_pagas_extra',12345)],extractor_name='alten-legacy-evidence')
    assert not run(doc,replace(source,extractions=(ext,))).points


def test_empty_and_duplicate_document_identity():
    doc,source=example()
    assert project_components((),{},{}).points==()
    assert not project_components((doc,doc),{DOC:source},{}).points


def test_multipayment_restrictions_cannot_be_removed_by_filtering_or_selection():
    from src.component_view import component_restrictions
    from src.payroll_timeline import classified_timeline, visible_timeline
    from tests.unit.test_payroll_timeline import record
    doc,source=example()
    rival=replace(doc,document_id='rival',classification_document_id='rival')
    totals=classified_timeline([record(doc=DOC),record(doc='rival')],(doc,rival),years=(2025,2025))
    assert not totals.points
    assert not run(doc,source,component_restrictions(totals.table)).points
    hidden=visible_timeline(totals,())
    assert not hidden.points  # presentation does not change the original guards
    assert not run(doc,source,component_restrictions(totals.table)).points


def test_separate_companies_and_no_continuity_or_interpolation():
    from src.component_view import component_chart
    doc,source=example()
    p=run(doc,source).points[0]
    rows=component_rows((p,replace(p,company='Otra',period=(2025,3))))
    spec=component_chart(rows).to_dict()
    assert spec['spec']['mark']['type']=='point' and spec['facet']['row']['field']=='Empresa'
    assert {r['Fecha'] for r in rows}=={'2025-01-01','2025-03-01'}


def test_unknown_metadata_and_mixed_vocabularies_fail_closed():
    doc,source=example()
    ext=source.extractions[0]
    c=ext.concepts[0]
    altered=replace(c,attributes=tuple((k,e) for k,e in c.attributes if k!='codigo'))
    assert not run(doc,replace(source,extractions=(replace(ext,concepts=(altered,)),))).points
    alias=replace(c,occurrence='nomina.conceptos.'+'a'*64+'.0')
    assert not run(doc,replace(source,extractions=(replace(ext,concepts=(c,alias)),))).points
