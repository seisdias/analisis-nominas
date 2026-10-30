# Contratos de completitud B2b.1

La evaluación es de lectura, por **documento / versión / extracción / sección**.
`evaluate_completeness()` no suma; `diagnose_breakdown()` entrega sus garantías al
motor existente `salary_reconciliation.reconcile()`. Una igualdad aritmética no
certifica conceptos, no cambia elegibilidad y no autoriza series multiversión.

## Frontera de confianza

El catálogo fija nombre y hash de revisión del **pipeline**, no empresa ni revisión
calculada dinámicamente. `_revision()` en `ingestion_processors.py` incorpora parser,
modelo, extracción y adaptador. Las revisiones revisadas constan en `CONTRACTS`.
El lector obtiene `Extraction.content_hash` junto con todos sus hechos en la misma
instantánea. Se verifica ese hash con la serialización original; luego se reconstruye
la lista contra esos hechos. El hash detecta recortes/cambios de proyección, no es
una firma del PDF ni una garantía de OCR perfecto.

Se exige `es_procesable=true`, todos los atributos proyectados por `adapt_nomina`,
posiciones de origen únicas y consecutivas, columnas conocidas y procedencia de la
misma extracción. No se admite una revisión nueva sin revisión explícita del contrato.
Una ausencia de estas pruebas significa **no acreditado**, no que el PDF esté mal.

## Formatos

| Contrato / versión | Justificación técnica y documental | Alcance |
|---|---|---|
| `ineco-closed-table/1` | `InecoParser._conceptos` delimita la tabla entre su cabecera y «cotización seg»; consume cada fila o falla. `_insurance_columns` exige bloques ordenados y seguros reflejados en ambas columnas, sin eliminar ocurrencias. `_totals` lee los totales del propio documento. | Devengos y deducciones de las columnas, con signo original; relación bruto − deducciones = líquido. |
| `exceltic-closed-table/1` | `ExcelticParser.parse/_concepts` delimita tabla y resumen, rechaza fila/etiqueta no reconocida, valida la columna por etiqueta y flag y exige ayudas reflejadas. Sólo omite «PAGO POR TRANSFERENCIA», texto sin importe. | Ambas columnas monetarias y relación bruto/neto. |
| `altran-closed-table/1` | `parse_extracted` acredita cobertura mediante límites y coincidencia texto/layout; cada fila tiene una celda monetaria localizada por `concept_column`. **Eso no acredita la participación de especie/compensaciones en los totales impresos.** | Registrado, **no habilitado**: `contract.total_scope_unverified`. No se eliminan partidas para obtener igualdad. |

Pruebas técnicas existentes: `tests/synthetic/parsers/test_ineco_conceptos.py`
(repetidos, seguros, contribuciones y rechazo de filas inválidas) y
`test_exceltic_parser.py` (ayudas reflejadas, sección empresarial excluida, rechazo
explícito de conceptos desconocidos). La proyección `nomina-facts/v1` conserva todas
las filas y sus posiciones, sin clasificación salarial adicional.

**ALTEN:** `alten-legacy-evidence/v1` identifica el puente de importación, no la
revisión del parser original. El payload y su lista no bastan para acreditar aquel
contrato. La proyección económica v2 sólo copia totales/contexto, sin desglose.
Ambas permanecen no aplicables; no se mezclan ni se seleccionan versiones.
**Coritel/INSIS4:** sin desglose estructurado, no se reconstruye por diferencias.

## Requisitos por sección

- Todos sus importes y el total deben ser decimales `present`; cero explícito sí,
  cero heredado `unreliable` no. Un fallo de valores en deducciones no invalida
  automáticamente los devengos, pero impide la relación bruto/neto.
- `importe_texto` debe reproducir exactamente el decimal normalizado, con separadores
  españoles y un signo inicial o final. No se repara la variante INECO con punto
  decimal: se conserva como rechazo local. No se recupera precisión inexistente.
- La unidad es monetaria **local a la tabla y sus totales**; no se inventa EUR.
  Anotaciones de moneda contradictorias o parcialmente incompatibles bloquean.
- Se suma `importe` de la columna acreditada, conservando signos. No se multiplican
  unidades/precios ni se toman bases/porcentajes. `bases` e `informacion` quedan
  excluidas explícitamente; los escalares, incluida prorrata de cotización, nunca
  se añaden. Las filas de la otra sección se conservan pero no participan.
- Código repetido no significa fila duplicada. Ocurrencias repetidas, posiciones
  repetidas, proyección mixta o totales alternativos provocan rechazo; no deduplicación.
- La función salarial puede permanecer desconocida. Bonus, extra y atraso participan
  si son filas de la columna acreditada; no se infiere fijo/variable ni periodicidad.
- Sólo se usa el total presente de la misma extracción. Nunca un total certificado
  a nivel lógico prestado desde otra versión. Un conjunto vacío no vale cero.

## Aritmética y límites

El motor utiliza coeficientes enteros y `Decimal` exacto. No hay tolerancia ni regla
de redondeo autorizada. Una diferencia exacta queda **sin explicar**, con fórmula,
participantes y total de referencia. No se crean hechos, observaciones ni importes
ficticios. Bruto/neto requiere ambas secciones acreditadas y su contrato adicional;
no se inventa un total de deducciones por diferencia.

No se habilitan gráficos multiversión, resolución ALTEN, fijo comparable ni
normalización entre 12/14 pagas. Las restricciones locales de representación y B1
siguen funcionando independientemente de este diagnóstico de ficha.
