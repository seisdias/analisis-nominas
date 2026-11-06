# Acreditación salarial focalizada B2d

## Resultado y frontera de evidencia

La revisión de los formatos INECO y Exceltic no habilita ningún contrato retributivo
automático. Se contrastaron las nóminas originales disponibles, sus hechos persistidos,
las reglas de clasificación y los contratos de tablas completas. No se encontró una
cláusula salarial suficiente para convertir la composición repetida en fijo completo
ni para acreditar la estructura anual. Esto limita la conclusión al corpus disponible,
no demuestra que el trabajador careciera de salario fijo o de un acuerdo de pagas.

La interfaz conserva los importes ordinarios parciales y añade una matriz de requisitos
por documento, con evidencia y documentación pendiente. Las series B2c no cambian.
No se habilitan variaciones de salario fijo: no hay dos indicadores completos comparables.
Una diferencia entre sumas parciales sigue siendo una diferencia documental.

## Matriz por formato

| Requisito | INECO | Exceltic |
|---|---|---|
| Mes civil documental | Fechas explícitas; algunos intervalos no cubren el mes civil | Fechas explícitas; la incorporación comprende un intervalo parcial |
| Participación contable | Tabla cerrada B2b.1; se conserva el rechazo de la notación original no conciliable | Tabla cerrada B2b.1, incluidas ayudas reflejadas en ambas columnas |
| Componentes ordinarios | `9001` salario base, `9002` plus convenio, `9003` antigüedad, `9004` complemento salarial, sin atraso | `1` SALARIO BASE, PLUS CONVENIO y MEJORA VOLUNTARIA; el código no es identidad única |
| Naturaleza fija/cobertura | La denominación y repetición no acreditan recurrencia de complementos ni cobertura del fijo | MEJORA VOLUNTARIA no se convierte automáticamente en complemento fijo recurrente |
| Extras | `9032/9033` son extras incluidas; no detallan los componentes ni acreditan multiplicidades anuales | P.P.EXTRA en devengos es prorrata salarial; no acredita por sí sola un acuerdo anual completo |
| Prorrata informativa | La sección «Cotización Seg.»/«Prorratas pagas» es referencia de bases | «PROR.PAG.EX.»/«Importe prorrata pagas extraordinarias» en resumen de bases no se suma a P.P.EXTRA |
| Incertidumbres adicionales | Seguro de vida, prestaciones/complementos IT y liquidación de vacaciones permanecen sin función suficiente | Ayudas comida/guardería permanecen separadas del candidato a fijo |
| Periodicidad anual | No acreditada | No acreditada |

La cabecera INECO que contiene «Fecha Contrato» no es una cláusula de remuneración.
En Exceltic, «Importe remuneración mensual» pertenece al resumen de contingencias
comunes: no se promueve a fijo contractual ni se añade como otra partida salarial.
Las unidades/precios no se interpretan automáticamente como días de jornada íntegra.
Los beneficios INECO `9025` con atributo de atraso conservan esa naturaleza.

Referencias técnicas revisadas: `InecoParser._period/_conceptos/_proration/_totals`,
`ExcelticParser._period/_concepts/parse`, `economic_classification`,
`identified_ordinary` y los [contratos de completitud](breakdown-contracts.md).
No se modifican esos contratos ni los parsers.

## Requisitos independientes y documentos que faltan

1. **Mes civil documental**. Dos fechas presentes, coherentes con el periodo y la
   huella de la extracción. No acredita jornada ni mensualidad salarial íntegra.
2. **Devengos conciliados**. Resultado original de B2b.1. La igualdad no prueba recurrencia.
3. **Naturaleza fija**. Requiere acuerdo salarial o cláusula revisada que identifique
   los componentes fijos, su recurrencia y vigencia. No se infiere de su frecuencia.
4. **Cobertura del fijo**. Composición íntegra aplicable al periodo, incluyendo el
   tratamiento de complementos. Partidas desconocidas se conservan explícitamente.
5. **Mensualidad salarial íntegra**. Evidencia de jornada, altas/bajas e incidencias.
   Un periodo impreso de principio a fin de mes no resuelve por sí solo este requisito.
6. **Modalidad de pagas**. Para INECO, contrato/convenio aplicable y acuerdo salarial
   que definan composición y devengo de cada extra. Para Exceltic, además, acuerdo
   de prorrateo con las pagas cubiertas, mensualidades y vigencia.
7. **Equivalencia mensual/anual**. Cobertura fija, mensualidad íntegra y composición
   anual completas. No exige un año entero de nóminas si existe contrato suficiente.

Una nómina adicional con los mismos importes no reemplaza esos documentos. El contexto
12/14 declarado por el propietario orienta la revisión, pero no se persiste como prueba
ni activa contratos. El motor existente puede recibir referencias revisadas; la UI no
permite autorizar garantías mediante casillas o texto libre.

## Implementación

`salary_evidence.describe_salary()` explica una reconstrucción existente de la misma
extracción. `assess_salary()` delega el cálculo en B2b.2 y sirve para evaluación focalizada.
Los modelos son inmutables. No hay SQL, catálogo alternativo, nuevas sumas ni selección
de versiones. Cada requisito conserva los hechos de origen y su alcance.

Los requisitos satisfechos no se combinan en una certificación única. Un contrato de
fijo parcial puede acreditar la naturaleza de sus participantes sin acreditar cobertura
completa. Un contrato de modalidad puede estar acreditado sin autorizar una equivalencia.
Los contratos completos siguen utilizando las fórmulas exactas de B2b.2:

- Fijo identificado: suma de ocurrencias autorizadas.
- Anual equivalente: términos y multiplicidades acreditados, sin duplicar prorratas.
- Mensual equivalente: numerador anual / 12, sin redondeo económico intermedio.

No se activa ninguna de estas fórmulas por coincidencia de números, meses o empresas.
La equivalencia representa la estructura vigente, no los ingresos cobrados en un año.

## Interfaz y trazabilidad

El panel ofrece «Qué falta para acreditar el fijo en este contexto», antes del filtrado
visual de series. Al abrir la composición o la ficha, «Qué falta para acreditar el fijo»
muestra motivos concretos y documentos necesarios. Los hechos, claves, páginas y estados
siguen disponibles en un desplegable. Los documentos con la misma composición conservan
la tabla de tramos B2c; no se renombran como tramos salariales acreditados.

El panel aplica la política D.2.3-C y el vínculo al bruto antes de exponer este diagnóstico.
La ficha conserva el escenario de inspección por extracción. Ninguna selección de
inspección autoriza una serie ni cambia la SQLite. No se modifican restricciones Coritel,
resoluciones A.3, certificaciones, componentes B1, conciliaciones ni formatos económicos.

Siguiente paso útil: revisar evidencia salarial adicional de los dos formatos y vincularla
a contratos existentes con vigencia explícita. No ampliar gráficos ni multiplicadores
hasta disponer de esa evidencia.

## Resultado de la validación focalizada

Cifras de documentos, no de nóminas sumables ni de contratos laborales:

| Formato | Documentos revisados | Mes civil completo | Devengos conciliados / ordinario parcial | Fijo completo | Equivalente anual |
|---|---:|---:|---:|---:|---:|
| INECO | 60 | 57 | 59 | 0 | 0 |
| Exceltic | 7 | 6 | 7 | 0 | 0 |

Los cinco tramos de composición INECO abarcan 53 documentos; el tramo Exceltic, seis.
Todos esos documentos satisfacen mes civil y conciliación, pero ninguno acredita las
restantes garantías salariales. Fuera de los tramos se mantienen los documentos y sus
limitaciones individuales. Los totales completos no determinables se solapan con los
parciales disponibles; no son categorías excluyentes de documentos.

INECO conserva diez documentos con extras incluidas, diecinueve con atrasos/ajustes y
diez con alguna función pendiente. Exceltic conserva siete prorratas salariales y cinco
documentos con ayudas separadas del candidato a fijo. Modalidades anuales acreditadas y
variaciones acreditadas de fijo: ninguna. Se revisaron los 67 PDF en lectura, sin
incorporar nombres de archivo, importes o datos personales a esta documentación.

Para reproducir el diagnóstico, abrir `open_inspector(load_config().database)`, obtener
`read_analytic_dataset` y `read_document_concepts`, y evaluar las extracciones de los dos
formatos con `assess_salary`. Para tramos y elegibilidad gráfica, reutilizar
`classified_timeline`, `component_restrictions`, `project_income` y `matching_periods`.
No sustituir el inventario completo por una selección heurística de archivos o importes.
