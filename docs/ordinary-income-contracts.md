# Ordinario identificado y evolución B2b.3

## Regla `ordinary-subset/b2b3-v1`

`salary_reconstruction.identified_ordinary()` reutiliza `reconstruct()` y sus partidas
B2a. La regla se aplica sólo a INECO y Exceltic, no a un nombre empresarial. Exige:

1. Tipo `NOMINA_ORDINARIA` inequívoco en los hechos de la extracción.
2. Revisión exacta del pipeline admitida por B2b.1, hash completo y estructura válida.
3. Devengos `RECONCILED` bajo su contrato de completitud, signos y unidad monetaria local.
4. Filas de devengos clasificadas por las correspondencias exactas B2a como salario
   base/complemento, con `atraso=false` e importe `present`.

El resultado suma **esas ocurrencias**, conservando signos, sin usar un residuo del bruto.
La fórmula no incluye extras, prorratas, bonus, ayudas, desconocidos, atrasos ni bases.
Su cobertura siempre es **parcial**: no existe evidencia suficiente para declarar fijo
completo o recurrente. No se anualiza y no se asigna modalidad 12/14 por empresa o fecha.
Un rechazo conserva las partidas en la ficha y el bruto en su representación original.

## Justificación por formato

| Formato | Ordinario identificado | Referencia documental/técnica |
|---|---|---|
| INECO | `9001 salario base`, `9002 plus convenio`, `9003 antiguedad`, `9004 comp.salarial` / `comp. salarial`, sin atraso | `InecoParser._CONCEPTS`, `_conceptos` y `_ordinary_total`; códigos/etiquetas exactos B2a, columna devengos y atributo de atraso. `_ordinary_total` excluye atrasos al generar escalares, que no se vuelven a sumar. |
| Exceltic | `1 SALARIO BASE`, `1 PLUS CONVENIO`, `1 MEJORA VOLUNTARIA` | `ExcelticParser._LABELS`, `_concepts` y `_category_total`; etiqueta exacta y columna revisada. `1` no identifica una ocurrencia única. |

La regla no vuelve a enumerar estos catálogos: usa las clasificaciones B2a y las
revisiones de completitud existentes. Una etiqueta parecida no habilita el concepto.
Los complementos son **ordinarios identificados documentalmente**, no contractualmente
fijos. No se homologa su significado entre formatos ni se infiere recurrencia por frecuencia.

INECO `9032/9033` conserva extras incluidas; `9RPE` y `90RG` son ajustes explícitos.
`9025` con denominación de beneficio y atributo de atraso sigue siendo atraso, no bonus.
Prestaciones, vacaciones y seguros sin correspondencia funcional suficiente no se
absorben en el ordinario. La notación original que bloquea un devengo no se repara.

Exceltic `P.P.EXTRA` en devengos es prorrata salarial; `PROR.PAG.EX.` y los escalares
de bases son referencias de cotización y no pagos adicionales. Las ayudas reflejadas
en ambas columnas no se suman al ordinario ni se eliminan del bruto.

## Mensualidad, periodicidad y modalidad

`fecha_inicio/fecha_fin` pueden documentar un intervalo que coincide con un mes civil.
Eso no acredita jornada íntegra, ausencia de incidencias, recurrencia de complementos
ni composición de extras. No se utilizan unidades como días sin un contrato adicional.
Las extras incluidas de INECO y las prorratas de Exceltic acreditan esas partidas; no
prueban por sí solas la estructura anual completa ni que todas las extras sean iguales.
Los contratos de fijo y equivalencia B2b.2 permanecen sin activación automática.

## Proyección y gráfica

`income_evolution.project_income()` consume documentos, fuentes leídas por las APIs
existentes, restricciones del contexto completo y puntos certificados del timeline.
Reutiliza el selector de extracción B1 (`component_extraction`), `ComponentPoint`,
`component_rows` y las correspondencias B1. Los atrasos explícitos adicionales proceden
de las partidas B2a, deduplicados por hecho de origen respecto a los componentes B1.
No se modifica el catálogo ni la proyección B1 original.

Antes de representar una suma ordinaria se verifica que el hecho total de su extracción
pertenezca al soporte de la observación bruta representada. Igualdad de importes no sirve
para emparejar. Varias extracciones con conceptos o versiones alternativas se excluyen
sin selección, aunque un total resuelto anterior siga siendo representable. Las
restricciones multipago/locales se calculan antes de cualquier selector visual.

Los componentes van como puntos aislados con periodo documental. El bruto se copia del
timeline, nunca se recalcula ni suaviza. Las extras independientes conservan su total
documental separado. Un componente incluido no es un pago adicional al bruto.
Los selectores no recalculan diagnósticos ni autorizan continuidad. Los huecos permanecen.
La empresa y evidencia de moneda se separan en facetas; moneda ausente no se convierte en
EUR canónico y una divisa explícita incompatible provoca aviso y exclusión de componentes.

La nueva vista se integra en el panel contextual; la pantalla histórica anterior y B1
mantienen sus contratos. Cuando sólo existe un mes se usa una tabla. Sin componentes
representables no se duplica otra gráfica de sólo totales. La ficha permite ver la suma
ordinaria parcial por extracción; esa inspección no autoriza series multiversión.

## Explicación de picos y límites

La investigación privada selecciona máximos estrictos respecto a los dos documentos
vecinos disponibles para inspeccionar sus hechos. Esa selección no clasifica ninguna
partida ni presupone continuidad donde faltan meses. No se publica información salarial.

La UI etiqueta el **desglose**, no la causa contractual de una variación:

- Completamente explicado: devengos conciliados y todas las partidas tienen función
  identificada e importe disponible. Incluye ordinario parcial documentado; no fijo total.
- Parcialmente explicado: existe alguna partida identificada, pero quedan desconocidos,
  importes no fiables o falta conciliación. Se conserva la razón.
- Sin explicación suficiente: no hay desglose identificado utilizable o la procedencia
  está bloqueada. El bruto no se borra por esa insuficiencia.

No se atribuyen diferencias a categorías inventadas. Una extra o atraso positivo puede
contribuir al pico, sin demostrar una subida del fijo. Para salario completo comparable
siguen faltando garantías de cobertura salarial, periodicidad y modalidad anual.

## Validación portable

Las pruebas usan sólo fixtures sintéticos: cálculo exacto y estados, exclusión de
extra/prorrata/atraso, desconocidos, versiones/extracciones, vínculo del total, filtros,
huecos, visibilidad, navegación y lectura inalterada de SQLite. Hay una prueba integral
que crea una base sintética, pasa por el inspector y abre el panel con Streamlit AppTest.
Las pruebas anteriores de contratos 12/14 y equivalencia B2b.2 permanecen intactas.

## Composición interactiva y periodos B2c

El punto seleccionado lleva el identificador lógico íntegro. El control alternativo
de nómina usa la misma identidad dentro del contexto visible. Las magnitudes y
partidas se obtienen desde la proyección anterior al filtrado visual. Así puede
ocultarse una extra para comparar dos series y seguir viéndola al abrir el bruto.

El detalle reutiliza las ocurrencias de devengos de la reconstrucción. Los escalares
y bases de cotización quedan fuera de la lista. La vinculación al bruto exige su
hecho de soporte o la proyección A.3 verificada por D.2.3-C. Si falta ese vínculo,
las partidas visibles conservan su carácter individual. Una diferencia aritmética
conserva el signo de la conciliación B2a. La clasificación funcional incompleta
puede coexistir con una suma contable conciliada.

La gráfica presenta el ordinario parcial y reserva series separadas para el
ordinario completo y el equivalente mensual con importe y cobertura completa
del motor B2b.2. El cociente económico conserva numerador y divisor. La conversión
para dibujar ocurre al producir la coordenada visual. El corpus actual proporciona
sólo cobertura parcial de ordinario.

Para consultar periodos con **la misma composición documental**, la tabla exige
una única mensualidad por empresa y mes, intervalo impreso del primer al último
día del mes civil, devengos conciliados y suma parcial vinculada al bruto. Sólo
agrupa meses consecutivos con el mismo extractor, revisión, estado de moneda y
multiconjunto de códigos y denominaciones de las partidas participantes. Excluye
multipagos. La comparación describe las partidas disponibles. Cuando la moneda
es desconocida se indica en la tabla. Todos los puntos permanecen individuales.
La comparación entre modalidades de 12 y 14 pagas requiere además cobertura
contractual de las extras, periodicidad y equivalencia anual.
