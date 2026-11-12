# Resumen económico por ejercicio C.4.3

## Agrupación y cobertura

La unidad es **denominación empresarial documental exacta + año documental**.
No se homologa ALTEN ni se convierte esa denominación en identidad canónica de empleador.
El año no se interpreta como fecha de cobro, periodo de devengo ni ejercicio fiscal.
Bonus y atrasos permanecen en el periodo del documento; no se trasladan por su etiqueta.

El panel mantiene Empresa, Periodo y Documento. «Detalle de empresa y ejercicio» es
un acceso al grupo ya filtrado, no un segundo sistema de filtros. Un intervalo de meses
limita la ventana inclusiva; los meses externos no se presentan como ausentes. El modelo
reutiliza `build_context` y `summarize_coverage`, conserva el contexto desconocido y no
amplía una intersección vacía. Los años sin documentos dentro del intervalo solicitado
pueden compararse mediante recuentos, nunca mediante un importe cero.

Doce meses documentados no acreditan mensualidades completas, todas las extras ni
un año salarial íntegro. Las restricciones no eliminan documentos del inventario.
Una repetición del mismo registro lógico se cuenta una vez; registros contradictorios
con la misma identidad se rechazan. Documentos diferentes del mismo mes permanecen separados.

## Resultado de la revisión de aditividad

No existe actualmente un contrato de aditividad **entre documentos por ejercicio**.

| Capacidad existente | Alcance real | No autoriza |
|---|---|---|
| Certificación canónica | Valor bruto/neto de un documento y su soporte | Suma anual |
| `evidence_only`, `candidate`, `excluded` | Elegibilidad individual | Aditividad entre observaciones |
| C.3 multipago | Representación documental conservadora | Independencia económica ni suma de pagos |
| A.3 / D.2.3-C | Versión y extracción original autorizadas | Aditividad temporal ni nueva certificación |
| B2b.1 | Conciliación de una sección y extracción con contrato | Sumar nóminas o versiones |
| B2b.2 | Equivalencia de una estructura salarial bajo contrato | Total efectivamente cobrado en el ejercicio |

Por eso todos los grupos muestran **Total anual no acreditado**. `AnnualGroup.aggregate`
solo admite ausencia, no un cero ni una cifra exploratoria. No se implementa una vía
para autorizar sumas mediante un booleano, una casilla, doce meses completos o el estado
`candidate`. Las pruebas de contratos anuales autorizados no pueden simular una autoridad
que no existe en el producto: se comprueba expresamente que ninguna elegibilidad individual
la reemplaza. No hay nuevas fórmulas monetarias ni nuevos redondeos económicos.

La falta de acreditación no prueba que dos documentos sean no aditivos o duplicados.
**No aditivo con el bruto** describe los componentes ya incluidos en él: no deben añadirse
otra vez al total. **Aditivo acreditado** requeriría un contrato revisado con independencia,
magnitud, temporalidad, universo, unidad, exclusiones y procedencia compatibles. No hay
productor de ese estado anual en C.4.3. No se infiere independencia por importes distintos
ni duplicidad por importes iguales.

## Composición y procedencia

`annual_summary` consume `CoverageDocument`, las fuentes originales de `CanonicalInspector`
y las restricciones C.3 del contexto completo. Reutiliza `project_income`,
`component_extraction`, `project_components` y la reconstrucción existente.
No consulta SQL ni crea persistencia, reglas de clasificación o selección alternativas.

Cada documento conserva cobertura, observaciones, hechos de soporte de bruto/neto,
versiones originales, extracción elegible, restricciones y componentes. Los importes
individuales se presentan con la disponibilidad del inspector. La unidad canónica
permanece accesible; el símbolo EUR de presentación no acredita una moneda económica.
No se suman magnitudes de moneda desconocida o incompatible.

Las filas incluyen ordinario parcial identificado, extras integradas, prorratas salariales,
bonus, ajustes y funciones pendientes. Los escalares informativos no se añaden a las filas.
La prorrata de cotización no es otro ingreso. La suma parcial B2b.3 se etiqueta como referencia
que no debe añadirse a sus participantes. Las extras independientes se muestran como
documentos, no se vuelven a incorporar como un componente adicional del total ordinario.

Puede haber componentes individuales B1 aunque no exista un desglose vinculado al bruto.
Se conservan como tales, sin afirmar que explican íntegramente el total. Los recuentos
por familia cuentan **documentos con evidencia representable**, no sumas monetarias.
Cero componentes identificados no demuestra ausencia de pagos: el estado del desglose
y las restricciones se muestran separadamente. Los documentos sin listas siguen disponibles.

Las resoluciones A.3 conservan una única versión autorizada. Los códigos repetidos
mantienen su identidad de ocurrencia. Una selección manual para inspección no autoriza
la incorporación a las series. Los bloqueos de Coritel y C.3 siguen aplicándose antes
de cualquier selección visual. La ficha permite investigar las versiones alternativas.

## Interfaz y comparación

La tabla principal es compacta; el desplegable de comparación añade meses ausentes,
categorías, componentes, multiversión, incidencias y aditividad. El detalle muestra
brutos/netos individuales, partidas, límites de composición y trazabilidad. El botón
«Abrir ficha documental» usa el identificador íntegro y mantiene empresa/periodo al volver.
Los documentos con restricción conservan su fila y acceso a inspección, pero no se
promueven a importes representables del resumen.

La comparación interanual se limita a cobertura, tipos y presencia de componentes.
No hay diferencias monetarias ni porcentajes salariales entre ejercicios. Los años
parciales y completos se distinguen sin convertir cobertura en equivalencia económica.
Los controles de categorías, B2c y B2d permanecen independientes del inventario anual.

## Validación y siguiente límite

Las pruebas sintéticas cubren agrupación, incertidumbre, ventanas, identidad, navegación,
restricciones, valores no fiables, selección A.3 real, ocurrencias repetidas y ausencia de
agregación. El corpus se valida exclusivamente en lectura, sin importes privados en tests
ni documentación. La matriz privada por empresa/ejercicio se obtiene con `summary_rows`
sobre `annual_summary`; los conteos reales nunca son constantes del producto.

El siguiente paso necesario para sumar exige un contrato de aditividad interdocumental,
separado del salario fijo contractual. Antes de activarlo deben revisarse independencia,
solapamientos, sustituciones, temporalidad, unidad y universo autorizado. C.4.3 no realiza
esa autorización ni modifica el esquema, las resoluciones o las certificaciones.

## Aditividad no acreditada frente a rechazada

El resumen distingue explícitamente las tres situaciones solicitadas. El estado
**acreditado** continúa sin productor anual, pues no existe contrato que lo autorice.
**No acreditada** significa que faltan garantías, no que se haya demostrado duplicidad.
**Rechazada para este conjunto** identifica un impedimento verificable en el universo
original de bruto/neto: una observación canónica `excluded`, la misma observación
atribuida a documentos lógicos distintos o monedas explícitas incompatibles dentro
de una misma magnitud. No se comparan bruto y neto como si fueran una sola magnitud.

Estos controles negativos no conceden aditividad al superarlos. No se eliminan
observaciones conflictivas para fabricar un subconjunto sumable. La moneda ausente,
los valores iguales de observaciones distintas y una restricción de representación
no se convierten en rechazo económico por sí solos. Ningún diagnóstico modifica la
certificación, elegibilidad o resolución canónica. La tabla principal y el detalle
muestran el estado y el motivo; el agregado permanece ausente en ambos casos.
