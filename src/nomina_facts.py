"""One-way legacy Nomina projection, without persistence or economic interpretation.

Keys/float projection policy constitute adapter revision nomina-facts/v1. Record
that revision in extraction metadata when binding the returned drafts. Values are
observed in the normalized model; this does not assert they were printed in a PDF.
"""

from decimal import Decimal

from src.canonical.facts import FactDraft
from src.canonical.serialization import canonical_sha256
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina

ADAPTER_REVISION = 'nomina-facts/v1'

# Explicit stored fields only: never inspect calculated properties or to_dict().
NOMINA_FIELDS = (
    'id', 'anio', 'mes', 'periodo', 'empresa', 'cif', 'tipo', 'es_procesable', 'observaciones',
    'categoria', 'grupo_cotizacion', 'salario_base', 'plus_convenio', 'complementos',
    'prorrata_pagas_extra', 'total_devengado', 'descuento_seguridad_social',
    'irpf_porcentaje', 'irpf_importe', 'otras_deducciones', 'total_deducir',
    'liquido_percibir', 'base_ss_comunes', 'base_irpf', 'fecha_inicio', 'fecha_fin',
    'base_at_ep', 'pror_otros', 'base_irpf_pie', 'base_sujeta_retencion_irpf',
    'base_irpf_especie', 'fecha_alta', 'categoria_convenio',
)
# Unit annotations from the existing fields, not rules about economic aggregation.
NOMINA_AMOUNTS = frozenset({
    'salario_base', 'plus_convenio', 'complementos', 'prorrata_pagas_extra',
    'total_devengado', 'descuento_seguridad_social', 'irpf_importe', 'otras_deducciones',
    'total_deducir', 'liquido_percibir', 'base_ss_comunes', 'base_irpf', 'base_at_ep',
    'pror_otros', 'base_irpf_pie', 'base_sujeta_retencion_irpf', 'base_irpf_especie',
})
CONCEPT_FIELDS = ('codigo', 'concepto', 'categoria', 'columna', 'importe', 'importe_texto',
                  'atraso', 'porcentaje', 'unidades', 'precio', 'base')
CONCEPT_AMOUNTS = frozenset({'importe', 'precio', 'base'})


def _value(raw: object, currency: CurrencyCode | None, *, decimal_field: bool) -> CanonicalValue:
    if raw is None:
        return CanonicalValue(state=ValueState.UNKNOWN, currency=currency,
                              reason_code='legacy.absence_unspecified')
    if isinstance(raw, TipoDocumento):
        raw = raw.value
    if type(raw) is bool:
        value: ExactDecimal | str = 'true' if raw else 'false'
    elif type(raw) is str:
        value = raw
    elif type(raw) is int:
        value = ExactDecimal(raw, 0)
    elif type(raw) is float:
        # Shortest round-trip decimal spelling of the normalized float. This does
        # not recover the printed notation or pretend binary floats were Decimals.
        # Excess precision/non-finite values fail; no quantization or rounding.
        value = ExactDecimal.from_decimal(Decimal(str(raw)))
    else:
        raise TypeError('Unsupported legacy field type')
    if decimal_field and isinstance(value, ExactDecimal) and value.coefficient == 0:
        return CanonicalValue(state=ValueState.UNRELIABLE, value=value, currency=currency,
                              reason_code='legacy.zero_origin_unknown')
    return CanonicalValue(state=ValueState.PRESENT, value=value, currency=currency,
                          reason_code='legacy.normalized_value')


def adapt_nomina(model: Nomina, *, currency: CurrencyCode | None = None) -> tuple[FactDraft, ...]:
    """Copy stored fields into stable drafts; no extraction ID, timestamp or pages.

    Currency is unknown unless explicitly supplied from documentary evidence.
    Within each (code, column) group, occurrence order is the only available tie
    breaker. No code is treated as a globally meaningful economic category.
    """
    if not isinstance(model, Nomina):
        raise TypeError('Expected normalized Nomina')
    if currency is not None and type(currency) is not CurrencyCode:
        raise TypeError('Explicit CurrencyCode required')
    result = [FactDraft(f'nomina.{name}', _value(
        getattr(model, name), currency if name in NOMINA_AMOUNTS else None,
        decimal_field=name in NOMINA_AMOUNTS or name == 'irpf_porcentaje',
    )) for name in NOMINA_FIELDS]
    occurrences: dict[str, int] = {}
    for position, concept in enumerate(model.conceptos):
        group = canonical_sha256({'codigo': concept.codigo, 'columna': concept.columna})
        occurrence = occurrences.get(group, 0)
        occurrences[group] = occurrence + 1
        prefix = f'nomina.conceptos.{group}.{occurrence}'
        # Source order is preserved as metadata; it is not an identity component.
        result.append(FactDraft(f'{prefix}.source_position', _value(position, None, decimal_field=False)))
        for name in CONCEPT_FIELDS:
            result.append(FactDraft(f'{prefix}.{name}', _value(
                getattr(concept, name), currency if name in CONCEPT_AMOUNTS else None,
                decimal_field=name in CONCEPT_AMOUNTS or name in ('porcentaje', 'unidades'),
            )))
    return tuple(sorted(result, key=lambda fact: fact.fact_key))
