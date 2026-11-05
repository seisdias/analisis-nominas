# Contratos de reconstrucción B2b.2

## Frontera de confianza

`reconstruct(extraction, fixed=None, payment=None, annual=None)` consume exclusivamente
la proyección existente de `CanonicalInspector`. No hay nuevo lector, SQL, persistencia,
selección de versiones ni observaciones certificadas. B2a conserva la interpretación
funcional y B1 su catálogo único. B2b.1 conserva toda la conciliación y sus garantías.

La API de contratos es para **llamantes revisados**, no para entradas libres del usuario.
`ContractEvidence` vincula documento, versión, extracción, extractor, revisión y hash
persistido a una referencia revisada, un periodo documental y una versión de contrato.
El motor verifica identidad, hash de los hechos y periodo. El hash no prueba recurrencia:
la revisión de la referencia debe acreditar las garantías retributivas declaradas.
No se fabrica esta referencia desde igualdad numérica, patrón temporal o empresa.
El resultado conserva los contratos recibidos, incluso rechazados, para auditoría.

**Catálogo retributivo de producción: ninguno activado.** Los contratos de INECO y
Exceltic en B2b.1 acreditan determinadas tablas, no contratos laborales. Las claves
persistidas examinadas contienen conceptos, totales y contexto documental; no permiten
establecer automáticamente cobertura de fijo, recurrencia de complementos, número y
composición completa de extras ni mensualidad íntegra. Altran y ALTEN pueden mostrar
partidas sin que su conciliación global sea evaluable. Coritel e INSIS4 no obtienen
conceptos ausentes mediante restas. El contexto histórico del propietario permanece
contexto de investigación, no un corte por empresa o fecha.

## Garantías independientes

| Capa | Habilita | No acredita por sí sola |
|---|---|---|
| Clasificación de ocurrencias B2a | Lectura de cada partida identificada | Aditividad, recurrencia o salario completo |
| `FixedContract` | Suma de ocurrencias fijas expresamente acreditadas | Modalidad de extras ni equivalente anual |
| `PaymentContract` | Modalidad acreditada o declarada sin verificar | Importe anual ni composición de extras |
| `AnnualContract` | Equivalencia de la estructura vigente con términos explícitos | Ingresos efectivamente percibidos en el ejercicio |

`FixedContract` exige referencias a ocurrencias completas, unidad común y signos
acreditados. Sólo acepta candidatos explícitos B2a de salario base/complemento sin
atraso y con valor `present`, en un documento inequívocamente ordinario. No admite
bonus, compensaciones, prorratas, extras, valores desconocidos o residuos como fijo.
Su garantía de recurrencia/aditividad procede de la referencia revisada, no de B2a.
Puede ofrecer una suma **parcial** acreditada sin afirmar que sea el fijo total.
Para declararlo completo no pueden quedar candidatos sin justificar ni partidas de
función/sección desconocida. Esto es deliberadamente conservador. Las prorratas se
mantienen separadas del fijo ordinario y sólo intervienen en su equivalencia anual.

La falta de conciliación contable completa no bloquea por sí sola la lectura de
componentes, ni un contrato independiente de cobertura fija debidamente revisado.
La API no toma totales de otra versión ni importa automáticamente certificaciones.

## Fórmulas y temporalidad

- Fijo identificado: suma algebraica de las ocurrencias autorizadas por `FixedContract`.
- Estructura con extras separadas: doce repeticiones de cada componente fijo ordinario
  más las ocurrencias de extras incluidas de esta extracción, con multiplicidades
  explícitas acreditadas. No se supone que una extra iguale al fijo ordinario completo.
- Estructura prorrateada: doce repeticiones de cada componente fijo ordinario y de cada
  prorrata salarial autorizada. No admite extras separadas en la misma fórmula.
- Equivalente mensual: equivalente anual / 12, conservando el cociente exacto.

La anualización exige fijo completo, mensualidad íntegra acreditada, modalidad
verificada, composición completa de extras y un contrato vigente para el periodo
documental analizado. Los términos tienen ocurrencias únicas y multiplicidades enteras
positivas; se rechazan bonus, atrasos, unidades incompatibles y partidas no fiables.
`full_extra_composition` requiere revisión independiente: no se activa porque una
extra observada parezca completa. Tampoco se anualiza una extra parcial.

La vigencia del contrato puede ser menor que un año: la salida es una **equivalencia
de la estructura vigente**, no una imputación anual de cobros. Un cambio salarial
requiere evidencia nueva; no se extiende la estructura anterior fuera de su vigencia.
No se suma información de otros documentos ni se distribuyen bonus o atrasos.
El periodo del documento nunca se convierte en fecha de pago o periodo de devengo.

Limitación de esta versión: extras independientes se muestran como referencias;
no se enlazan con ordinarias de otros documentos para construir fórmulas anuales.
Una fórmula con extras sólo puede usar ocurrencias explícitas de la misma extracción
cuya composición y multiplicidad hayan sido acreditadas. No hay homologación entre
empresas ni política consolidada multiversión. Modalidades sin doce mensualidades
ordinarias no se anualizan en este motor acotado, aunque puedan describirse como otras.

## Identidad, unidades y aritmética

Cada `Part` conserva `ClassifiedConcept` y su `ConceptOccurrence`: documento, versión,
extracción, ocurrencia, atributos originales, hechos, claves, estados, moneda y páginas.
No se agrupa por etiqueta ni código. Cada ocurrencia participa una vez en un escenario;
las multiplicidades anuales son proyecciones contractuales, no nuevos pagos observados.
Las referencias escalares no se añaden a filas. El total de una extra independiente
se mantiene separado, incluso cuando también existe su desglose.

La conciliación reutilizada mantiene fórmula, participantes y diferencia exacta.
`functional_exhaustive` exige devengos conciliados y todas las partidas funcionalmente
resueltas; candidatos a fijo pendientes no bastan. No se usa una diferencia para crear
un componente. La **Diferencia no explicada** conserva el signo de B2a: suma de filas
menos total documental. No se atribuye a bonus, extra o salario.

Los cálculos usan coeficientes enteros y `Decimal` sin redondeo intermedio. `ExactAmount`
conserva numerador y divisor; `display()` utiliza dos decimales y `ROUND_HALF_UP` sólo
para lectura. No hay tolerancias. La unidad común local puede acreditarse sin código
ISO; no se rellena moneda ausente ni se transforma una convención visual en EUR
certificado. Cero explícito es un valor; ausencia no es cero.

## Uso en ficha y próximos incrementos

La ficha usa la API sin contratos retributivos automáticos. Muestra componentes,
candidatos a fijo, extras de referencia y motivos de indisponibilidad. Las fórmulas,
procedencia y restricciones se despliegan bajo demanda. No añade gráficas ni cambia
filtros, cobertura, totales, resolución ALTEN o restricciones de Coritel.

D.2.3-C verifica la resolución A.3 para representar los componentes de su extracción original. B2c podrá representar sólo
indicadores con contratos acreditados; no reconstruirá datos históricos ausentes.
D.2.5 abordará IRPF, cotizaciones y bases comparables. Acreditar garantías salariales
reales requiere evidencia adicional y revisión explícita antes de activar contratos.
