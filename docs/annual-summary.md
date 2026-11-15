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

## Suma documental exploratoria (C.4.4-A)

El detalle de empresa/ejercicio ofrece bruto y neto por separado como suma
aritmética de los documentos seleccionados. Este contrato de presentación no
modifica `evidence_only`, no acredita un total anual ni un salario fijo contractual.
No requiere doce meses, no imputa fechas de cobro o devengo y no añade componentes
ya incluidos en los totales. La fórmula y las observaciones participantes son
consultables junto a todas las exclusiones.

Solo admite un total individual certificado por documento, con soporte en una
versión única o autorizada por A.3 y moneda canónica conocida. Reutiliza las
restricciones C.3 del contexto completo. Las relaciones registradas distintas de
`complements` se bloquean conservadoramente en ambos extremos, incluso cuando uno
queda fuera del filtro: no selecciona un ganador ni resuelve sustituciones.
Una observación compartida por documentos distintos tampoco se suma.

Los resultados son `calculable`, `partial` (subconjunto con exclusiones), `blocked`
(sin subconjunto admisible) o `empty` (grupo sin documentos). Las monedas conocidas
incompatibles bloquean todos los candidatos de esa magnitud; no se elige una moneda.
Los importes sin moneda, ausentes o no fiables quedan excluidos, nunca convertidos
en cero. Ceros y negativos documentados son válidos. Se calcula con `Decimal`
sin redondeo implícito; la vista muestra la precisión disponible y el código de
moneda acreditado. No se producen comparaciones porcentuales entre ejercicios.

«Total anual no acreditado» permanece independiente. La ausencia de moneda exige
evidencia y tratamiento canónico acreditado fuera de este incremento; la convención
EUR de otras vistas no desbloquea estas sumas.

## Moneda documental localizada en PDF (C.4.4-B)

La suma exploratoria puede usar evidencia monetaria local sin cambiar `currency`
en SQLite. El contrato `insis-explicit-net-currency/c4.4b-v1` admite exclusivamente
el rótulo **LIQUIDO TOTAL A PERCIBIR (A-B) EUROS**, con su importe explícito, en el
formato revisado de `InsisParser`. No extiende EUR al bruto, a otras columnas ni al
documento entero. Una cabecera monetaria genérica requiere otro contrato de ámbito
revisado; este incremento no la interpreta. Tampoco utiliza cifras equivalentes
rotuladas PTA para deducir EUR del importe situado en otra columna.

La comprobación exige una sola versión y página, revisión conocida del extractor,
hecho neto presente y certificado, coincidencia decimal exacta entre ese hecho y la
cifra rotulada, referencias a su página y ausencia de menciones monetarias
contradictorias. Conserva documento, versión, extracción, observación, hecho,
página, SHA del PDF y SHA del texto revisado. Las versiones alternativas no se
seleccionan mediante esta vía. Los demás contratos multiversión se conservan.

Se reutiliza **en lectura** `data/private/canonical-build.json` para localizar las
fuentes del corpus. Sus rutas solo sirven para encontrar el archivo: su SHA debe
coincidir con el registrado en SQLite. No se crea manifiesto privado ni se modifica
configuración. Si falta el manifiesto, el PDF, la página o la evidencia aplicable,
no se añade moneda. Los ficheros se leen y verifican de nuevo, sin caché documental.
La prueba monetaria se adjunta en memoria a la suma; los valores canónicos y las
certificaciones siguen intactos. La procedencia se consulta en el desplegable del
resumen y no expone rutas privadas.

Diagnóstico del formato: `InsisParser` reconoce `EUROS`/`PTA` para localizar el
líquido, pero el modelo normalizado no conserva la moneda. La ingesta invoca
`adapt_nomina` sin el argumento monetario opcional. La interpretación posterior
copia el hecho sin moneda; no hay una pérdida adicional en la presentación.
Para ampliar el desbloqueo se necesita evidencia explícita aplicable a cada
magnitud y versión, no la nacionalidad, el año ni una declaración general de EUR.

## Símbolo gráfico junto al neto Exceltic (C.4.5)

`exceltic-graphic-net-currency/c4.5-v1` reconoce exclusivamente el símbolo € gráfico
revisado de 18 × 29 píxeles RGB, mediante SHA del contenido de imagen decodificado,
profundidad y espacio de color. Rechaza máscaras o transformaciones de decodificación
no revisadas. Exige que aparezca debajo del único rótulo «LIQUIDO TOTAL A PERCIBIR»,
a la derecha del único importe de ese recuadro, con coincidencia decimal exacta con
el neto certificado. Las tolerancias geométricas son distancias de maquetación PDF,
no tolerancias monetarias. Un icono en otro campo no acredita moneda del neto.

Reutiliza las comprobaciones de huella del PDF, revisión del extractor, versión
única, página y hecho de C.4.4-B. Conserva además SHA y coordenadas del símbolo en la
procedencia visible. No realiza OCR general ni cambia parsers. El bruto permanece
sin moneda acreditada: la etiqueta gráfica es local al neto, no al documento entero.

La revisión focalizada contrastó texto de las 260 versiones con 16 muestras visuales
por formato/variantes observadas, y verificó los siete candidatos Exceltic. El símbolo
es un objeto gráfico que no aparece en la extracción textual; aquí la carencia no
significa ausencia en el original. Se habilitan siete netos adicionales (Exceltic
2015), conservando los tres INSIS4 de 2009. No se localizaron evidencias aplicables
adicionales en Altran, INECO, ALTEN o Coritel; las muestras visuales no mostraron moneda
junto a los totales ni cabecera de ámbito monetario. Esta conclusión es de cobertura
de la investigación, no una certificación de ausencia visual de cada PDF.

Para ampliar los casos restantes hace falta un original o evidencia complementaria
que identifique expresamente moneda y ámbito de aplicación, vinculada al documento
y versión. Cambiar un parser no recupera un símbolo que no está en la fuente revisada.
No se autoriza una moneda por país, denominación empresarial, fechas o periodicidad.
