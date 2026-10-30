# Análisis de Nóminas

Proyecto para extraer documentos laborales y conservar evidencia normalizada y
trazable. Los seis parsers (Coritel, INSIS4, INECO, Exceltic, Altran y ALTEN) están
certificados y congelados. No incluye OCR.

La infraestructura canónica T6 está certificada y congelada: usa una única SQLite, esquema v8, SQL explícito y
migraciones 0001–0008. Separa evidencia, interpretación, decisiones humanas y caché
derivada reconstruible.

En ALTEN A.2, el constructor canónico completa la ingesta y comprueba el inventario
antes de proyectar los hechos de documentos lógicos con una única versión al
vocabulario económico existente. La proyección añade extracciones, hechos trazables
y evaluaciones; si los totales satisfacen la regla existente, crea observaciones de
bruto y neto `evidence_only`, certificables como valores documentales por el contrato
actual. No son candidatas agregables. Los documentos multiversión quedan sin
proyección ni observaciones económicas; no se elige ninguna versión. Los hechos
originales y su estado `UNRESOLVED` se conservan.

Los corpus ALTEN no admiten exclusiones explícitas. Solo pueden omitirse los
certificados anuales reconocidos por el procesador existente: PDFs sin texto
extraíble, otras omisiones, fallos o cambios del inventario impiden publicar la
base. Esta fase requiere una reconstrucción completa en una base nueva, no una
ingesta incremental. Véanse las condiciones del [constructor canónico](examples/canonical-build.md).

La interfaz consulta la base canónica en solo lectura. Los comandos históricos de
ingesta usan la persistencia legacy; no crean la BD canónica definitiva. Véase el [contrato canónico](src/persistence/README.md)
para reconstrucción, revisiones y certificación. No hay KPIs salariales nuevos.

## Instalación (Python 3.14.0)

```bash
python3.14 -m venv venv
source venv/bin/activate
python -m pip install -r requirements-dev.txt
cp config.example.toml config.toml
# Edita paths.database para apuntar a tu SQLite canónica existente.
venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

La interfaz requiere una base canónica existente (esquema v8, journal DELETE),
preparada mediante el [constructor canónico](examples/canonical-build.md). Abre
[http://localhost:8501](http://localhost:8501). No crea ni migra bases. CLI y GUI comparten `config.toml`; `ANALISIS_NOMINAS_CANONICAL_DB` sigue disponible
y tiene prioridad. No se usa la base legacy como alternativa. La sección
«Configuración y diagnóstico» muestra la ruta efectiva, su procedencia, el
directorio documental y el resultado de la apertura en solo lectura. Las rutas
se muestran únicamente en ese diagnóstico y no se registran en logs.

La pantalla permite seleccionar empresa documental exacta, año y mes. «Todas las empresas» incluye documentos con empresa
ausente o ambigua. Bruto y neto conservan su certificación independiente: los
importes no certificados, sin observación o ambiguos no muestran un candidato.
La aplicación trabaja exclusivamente en EUR por decisión del propietario. La
interfaz presenta los valores certificados en formato español y con símbolo €
también cuando la moneda canónica es `None`, sin modificar la evidencia documental.
Una divisa explícita distinta de EUR muestra una inconsistencia, sin conversión ni
etiquetado en euros. Se conservan los decimales exactos (mínimo dos). No hay sumas, KPIs, gráficos, ingesta ni borrado desde esta pantalla.
La navegación lateral abre el Explorador. Los filtros se aplican automáticamente
al cambiar su valor (el año al confirmar o salir del campo), sin botón de actualización.
Dos contadores muestran documentos lógicos únicos y documentos con bruto y neto
certificados en los resultados filtrados; no son indicadores salariales. La tabla
muestra periodo, empresa, bruto y neto, con importes alineados a la derecha. Ordena
periodos completos de más reciente a más antiguo, después los incompletos, con
desempate por identificador. Seleccionar una fila muestra su identificador completo
y la certificación de cada valor. Documentos distintos del mismo periodo permanecen
separados. La ayuda está en «Cómo interpretar los documentos».
No se almacenan resultados en caché.
La consulta recorre el conjunto documental, sin paginación de servidor; está
pensada para corpus locales.

### Panel de análisis contextual (D.1–D.2)

Abre «Panel de análisis» en la navegación lateral o `/render_panel`. Las pantallas
anteriores siguen disponibles. No hay selector de modo de análisis: empresa,
periodo y documento determinan automáticamente el contenido.

- **Empresa:** denominación documental exacta; por defecto, todas.
- **Periodo:** vacío para histórico completo, `2015` para enero–diciembre,
  `09/2022` para un mes, `2015–2016` para años completos o
  `03/2015 – 09/2015` / `01/2015 – 06/2016` para intervalos mensuales inclusivos.
  Confirma con Intro o al salir del campo. Un periodo inválido muestra un aviso,
  nunca una consulta más amplia.
- **Documento:** solo ofrece documentos compatibles, con empresa, periodo,
  categoría e identificador abreviado. No selecciona el primero automáticamente.
  Al cambiar los filtros solo se limpia una selección documental incompatible.
- **Información incompleta:** filtro explícito de empresa o periodo desconocido.
  Un intervalo fechado exige año y mes conocidos; borra Periodo para localizar
  documentos sin fecha, sin mezclarlos silenciosamente con un intervalo.

Los filtros se combinan por intersección. El contexto efectivo siempre es visible.
Un documento seleccionado abre una ficha; un mes muestra documentos individuales
sin gráfica histórica; un intervalo, una empresa o el histórico muestran cobertura,
categorías, incidencias y evolución cuando hay varios meses. «Volver al contexto»
conserva empresa y periodo; «Restablecer filtros» devuelve la selección inicial.
Se conserva únicamente el estado de controles en la sesión, sin caché documental.

Los indicadores cuentan documentos y meses, nunca ingresos. Los huecos solo se
cuentan dentro de una ventana explícita y se marcan inciertos si hay contexto
incompleto compatible. En todas las empresas, un mes cubierto significa que hay
algún documento ese mes, no que todas las empresas estén documentadas. El intervalo
observado no es la duración del contrato ni un periodo de liquidación.

La gráfica reutiliza C.3: cada importe es individual, conserva multipago y
`presentation.withheld_document_ids`, y evalúa el contexto completo antes de
restringir a un documento. La media opcional mantiene sus contratos, no incluye
meses multipago y no equivale a salario certificado. La ficha muestra los estados
del inspector, el contexto económico registrado y los hechos por versión y
extracción, sin resolver versiones ni interpretar conceptos. Las tablas de hechos
se consultan completas por extracción, sin truncar las ocurrencias de conceptos. Los identificadores completos,
SHA y relaciones de soporte quedan accesibles en desplegables.

### Evolución histórica documental

La navegación lateral incluye «Evolución histórica». Consulta la misma SQLite y
configuración compartida que el explorador, exclusivamente en lectura. Permite
filtrar empresa documental exacta, intervalo de años desde 2006 y series bruto/neto.
El extremo temporal corresponde al último periodo documental disponible.

«Evolución documental, no agregación certificada»: cada punto corresponde a una
observación certificada, sin sumas ni promedios y sin alterar `evidence_only`.
Las empresas se distinguen por color y las series por el trazo. Las líneas solo
unen meses consecutivos con datos representables; los huecos no se rellenan con
ceros ni se interpolan. La gráfica permite zoom, desplazamiento y consulta de
identificadores e importes exactos al pasar el cursor.

C.3 permite puntos individuales en un mismo mes cuando las categorías específicas
están respaldadas por hechos de tipo explícitos, o cuando documentos de igual
categoría tienen intervalos documentales explícitos no solapados. Para habilitar
esta representación multipago se exige una única versión por documento y soporte
concordante; las observaciones competidoras permanecen bloqueadas. Los tipos
«otros» y «sin clasificar» no acreditan esa distinción. No se deduce aditividad.
Los puntos multipago quedan aislados de las líneas y de la media móvil, incluso
al filtrar categorías. Los intervalos se conservan como evidencia documental, sin
convertirlos en periodo económico ni atribuir fechas ausentes.

Si una revisión pendiente aún no está expresada en la evidencia, puede restringirse
solo la presentación mediante `[presentation].withheld_document_ids` en el
`config.toml` local (ver `config.example.toml`). La lista usa IDs completos, bloquea
el periodo afectado antes de filtrar y mantiene sus filas con una advertencia.
No modifica la clasificación ni autoriza representar ningún valor. Esta restricción
local debe conservarse al trasladar la configuración; no forma parte de SQLite.

La multiplicidad sin soporte suficiente sigue marcada como ambigua. Las observaciones de
versiones ya resueltas se recuperan mediante las consultas y certificación
existentes; la pantalla no resuelve versiones. La tabla conserva cada observación
por separado, los estados sin observación y los identificadores de documento,
observación y versiones. Los documentos con año desconocido permanecen en ella
al filtrar años. Las divisas explícitas distintas de EUR generan una advertencia
y no se dibujan como euros. El eje gráfico usa aproximación numérica; la tabla y
los tooltips conservan el importe exacto con formato español.

### Cobertura documental (C.4.1)

La página «Cobertura documental» responde qué documentos hay por denominación
empresarial exacta y año. Cuenta identidades lógicas, muestra meses documentados,
huecos del intervalo elegido y categorías C.1; no calcula ingresos ni porcentajes.
Un hueco no implica desempleo ni salario cero. Con contexto incompleto, la ausencia
se muestra como incierta y los documentos sin año permanecen separados.

La disponibilidad distingue observaciones certificadas por el inspector,
observaciones no certificadas, observaciones múltiples y ausencia de observación.
El criterio C.1 exige además una sola versión: se muestra por separado y no invalida
las resoluciones ya existentes. Multiversión no equivale a conflicto pendiente.
Las incidencias para revisión son señales de contexto, clasificación o disponibilidad,
no decisiones humanas ni una nueva evaluación económica. Las restricciones locales
`presentation.withheld_document_ids` se muestran sin quitar documentos de los recuentos.

Cada indicador permite consultar sus documentos, versiones, extracciones, hashes,
observaciones y referencias de hechos. Una única instantánea de lectura alimenta
los modelos inmutables y el cálculo puro de `src.documentary_coverage`. No hay caché,
nuevas tablas ni cambios de certificación o elegibilidad. La certificación privada
opcional usa `CANONICAL_COVERAGE_TEST_DB` con una base de referencia ya preparada:
`pytest -q --run-private tests/private/test_documentary_coverage.py` (no reconstruye).

Para la persistencia legacy, `python -m scripts.init_db` crea únicamente el esquema,
sin datos. La base predeterminada
es `data/runtime/nominas.sqlite`; para otra ruta: `python -m scripts.init_db --db RUTA`.
Las ingestas locales se ejecutan como módulos, por ejemplo `python -m scripts.ingest_ineco`.
En el modelo legacy los importes opcionales todavía usan ceros por
compatibilidad con el modelo: no deben interpretarse como extracción confirmada.
Los hechos conservan los valores extraídos y sus incertidumbres; no se corrigen
descuadres silenciosamente. No se garantiza cobertura de formatos no certificados.

## Validación

```bash
./scripts/check.sh
python -m pytest -q
python -m pytest -q --run-private  # suite completa; requiere corpus privado local
python -m pytest --collect-only
```

`check.sh` ejecuta Ruff, mypy y tests portables. Utiliza `PYTHON`, el entorno activo,
`venv/bin/python` o `python3`, y exige la versión de `.python-version`.
Las dependencias runtime y dev están fijadas por separado. La línea base estática
solo admite diagnósticos heredados enumerados; errores nuevos o entradas obsoletas
fallan. No actualizarla automáticamente para aceptar errores nuevos.

La suite se organiza por responsabilidad:

- `tests/unit/`: modelos y contratos canónicos (`canonical/`).
- `tests/synthetic/`: parsers (`parsers/`) y seguridad transversal con datos sintéticos.
- `tests/integration/`: extracción, ingesta (`ingestion/`) y persistencia (`persistence/`)
  con datos sintéticos y SQLite aisladas.
- `tests/private/`: regresiones del corpus privado; los nombres conservan la empresa
  y el área (`parser` o `ingestion`).

Los tests de `tests/private/` son locales y no se recogen por defecto:

```bash
python -m pytest -q --run-private  # suite completa; requiere corpus privado local
python -m pytest --collect-only --run-private
# Solo con documentos propios y autorización: abre PDFs locales
python -m pytest --run-private -m private
```

Los documentos reales, bases y exportaciones nunca se versionan. Guardarlos en
`data/testdata/`, `data/runtime/`, `data/private/`, `private/`, `exports/` o `backups/`.
Imágenes y CSV/XLSX públicos son admisibles; sus equivalentes privados deben quedar
en esas carpetas ignoradas. Guardar claves/certificados privados en `private/`.
Los tests portables contienen exclusivamente ejemplos sintéticos.

## Hook y CI

```bash
git config core.hooksPath .githooks
```

El pre-push usa `./scripts/check.sh`, igual que CI. GitHub Actions ejecuta el check
`foundation` en PRs hacia `dev`/`main` y pushes a ramas de trabajo y principales.
No hay despliegue automático ni credenciales de despliegue.

`feature/*`, `fix/*`, `chore/*` → PR a `dev` con squash.
`dev` → PR a `main` con merge commit para conservar ancestry.
Sin commits directos a las ramas protegidas después del bootstrap inicial.

### ALTEN A.3: selección explícita de versiones

La configuración de construcción v1 admite el campo opcional `alten_resolutions`,
ruta a un JSON privado relativa al archivo de configuración. Si se omite, se
mantiene el comportamiento A.2: solo se proyectan documentos de versión única.
Si se aporta, debe contener una decisión por cada documento multiversión del
corpus ALTEN configurado; no se admiten listas vacías ni decisiones duplicadas.

El archivo tiene los campos exactos `contract: "alten-version-resolutions"`,
`version: 1` y `resolutions`. Cada resolución contiene exclusivamente
`document_id`, `version_id`, `expected_version_ids` (lista completa sin duplicados)
y `reason` (justificación humana). Los identificadores deben proceder del
inventario real. El inventario se ordena canónicamente; no se infieren decisiones.
Las versiones vinculan documento, SHA256 del PDF y segmento/página. Un cambio de
inventario invalida la decisión. Guardar este archivo bajo `data/private/`, nunca
en ejemplos públicos. Se rechazan campos adicionales, claves JSON duplicadas,
tipos incorrectos y referencias ajenas al corpus.

Este contrato representa una selección con efecto de proyección y es distinto
de `canonical.decisions`, que solo reconoce hechos documentales sin efectos
económicos. No modifica ese contrato ni el esquema SQLite v8.

La proyección `alten-economic-projection/v2` conserva en `projection/manifest`
la decisión, el inventario revisado, las huellas de hechos, las páginas, la
extracción original y la ejecución de ingesta. Las bases A.2 siguen siendo
legibles; aplicar v2 requiere construir una base nueva, no actualizar una
proyección v1. Tampoco se permite cambiar una decisión sobre una base ya
proyectada. La repetición exacta es idempotente; los estados parciales se rechazan.
Todas las observaciones ALTEN permanecen `evidence_only`, excluidas de candidatos
y KPIs. La selección no certifica por sí misma aditividad ni elegibilidad.

Construir siempre con un destino nuevo mediante `python -m src.canonical_builder
--config <configuración-privada> --output <candidata-nueva>`. La publicación sigue
siendo atómica y sin sobrescritura. La reproducibilidad se compara con
`CanonicalStateReader` (estado lógico, excluyendo marcas temporales operativas),
no mediante igualdad binaria de los archivos SQLite.

## CLI v0.1 (solo lectura)

Desde el entorno Python existente (Click ya está incluido):

```sh
source venv/bin/activate
cp config.example.toml config.toml
# Edita config.toml para apuntar a una base canónica v8 existente.
./nominas empresas
./nominas listar --empresa "ALTEN DELIVERY CENTER SPAIN SLU" --anio 2025
./nominas ver --empresa "ALTEN DELIVERY CENTER SPAIN SLU" --anio 2025 --mes 1
./nominas estado
./nominas config
```

Para usar `nominas` sin `./`, añade la raíz del repositorio a `PATH`.
También se admite `python -m src.cli` desde la raíz. El ejecutable puede
invocarse por su ruta absoluta desde cualquier directorio con el entorno activo.
No requiere instalar el repositorio como paquete.

`config.toml` es local y está ignorado por Git. En `[paths]`, `database` es
obligatorio salvo que exista `ANALISIS_NOMINAS_CANONICAL_DB`, que tiene prioridad.
`payroll_directory` es opcional e informativo. Todas las rutas relativas, también
las de la variable de entorno, se resuelven desde la raíz del repositorio.
CLI y GUI usan el mismo lector (`src/cli_config.py`, conservado por compatibilidad).
La precedencia es: argumentos explícitos del lector, variable de entorno,
`config.toml` y valores por defecto. Los comandos actuales no añaden argumentos
de rutas: los argumentos opcionales son del API Python `load_config`.
La variable compatible solo afecta a la base; el directorio documental procede
del TOML (o de un argumento explícito) y por defecto no está configurado.
No hay base predeterminada: su ausencia produce un error comprensible.
Un TOML ilegible o mal formado se informa incluso si existe una variable de entorno;
no se ignora silenciosamente. No se modifica ni guarda configuración desde la GUI.

Las consultas exigen una base v8 existente con journal DELETE y verifican
integridad y claves foráneas. No crean, migran ni reparan bases. WAL se rechaza
para evitar la creación de archivos auxiliares. `config` solo muestra la
configuración resuelta, sin abrir la base; sus rutas completas pueden ser privadas.
Los demás comandos omiten rutas completas y datos personales.

Los filtros utilizan denominaciones y periodos documentales concordantes, sin
inferir identidad empresarial. `listar` admite filtros opcionales; `ver` exige
empresa, año y mes y conserva todos los documentos coincidentes. No selecciona
una versión ni muestra contenido personal del PDF. Los importes no certificados,
ambiguos o sin observación se indican explícitamente, sin mostrar un valor.
EUR es la única moneda funcional admitida: moneda documental ausente o EUR
se presenta con `€`, sin modificar la evidencia. Otras monedas explícitas muestran
una incompatibilidad, sin reinterpretación ni conversión. La certificación de
un valor no permite sumarlo: no hay agregaciones ni cambios de `evidence_only`.

Validación dirigida:

```sh
venv/bin/pytest -q tests/integration/persistence/test_nominas_cli.py tests/integration/persistence/test_canonical_inspector.py
venv/bin/ruff check .
venv/bin/mypy
```

### Categorías visibles en el panel (D.2.1)

«Tipos de ingreso visibles» permite activar cada categoría por separado, sin salir del
contexto de empresa y periodo. Todas las categorías presentes se muestran inicialmente;
las ausentes se identifican con «Sin registros». Las preferencias se conservan al cambiar
el contexto o abrir una ficha, y «Restablecer categorías» no modifica los filtros documentales.
El mismo control se reutiliza en Evolución histórica.

Se distinguen ordinarias, extraordinarias, **Variables / bonus**, beneficios, atrasos /
regularizaciones, finiquitos / liquidaciones, otros y sin clasificar. `VARIABLE_BONUS`
se asigna a su propia categoría desde el tipo documental explícito, conservando las
comprobaciones de evidencia contradictoria o incierta. El contrato de parsing actual
no identifica un tipo específico de beneficios ni de atrasos: esas categorías se
mantienen disponibles en el dominio, sin inferencias por empresa, fecha o importe.
Un bonus no se considera una paga de beneficios.

La cobertura y «Documentos disponibles» siempre incluyen el contexto completo.
«Registros económicos visibles» y el gráfico reflejan únicamente la visibilidad elegida.
Ocultar una categoría no resuelve conflictos ni restricciones locales, no selecciona
versiones y no habilita continuidad. La ficha seleccionada explícitamente permanece accesible.

Las ordinarias conservan líneas y puntos, con sus interrupciones; las demás categorías
y los multipagos se dibujan como marcadores aislados. Hay ocho formas estables, una por
categoría; el color distingue empresas y el trazo/opacidad distingue bruto y neto.
Los identificadores completos siguen disponibles en el detalle documental.

La media opcional se calcula sobre el contexto completo de ordinarias representables,
antes de aplicar visibilidad; extras, bonus y demás categorías no entran en ella.
Se oculta junto a la serie ordinaria. Sin clasificación ordinaria fiable no se ofrece
la antigua referencia sobre documentos sin clasificar. Se mantienen los requisitos de
12 meses válidos consecutivos y las exclusiones por multipago, huecos y contexto incompleto.
Ninguna referencia constituye salario certificado ni autoriza sumar ingresos.


### Explorador de conceptos internos (D.2.3-A)

Al seleccionar un documento en **Panel de análisis**, la ficha conserva el resumen
certificado y añade **Desglose documental de conceptos**. Las partidas se presentan
por devengos, deducciones u otros/grupo desconocido, manteniendo la denominación,
código, columna y categoría originales. Unidades, precio, porcentaje y base solo
ocupan columnas cuando hay información disponible. Las unidades no se interpretan
como días u horas. Los importes usan formato español y solo muestran un código de
moneda cuando está registrado: no se añade EUR a la evidencia.

Las filas se reconstruyen exclusivamente por documento, versión, extracción y
ocurrencia (`nomina.conceptos.<grupo>.<ocurrencia>.<campo>` o
`payload/conceptos/<posición>/<campo>`). Los códigos y etiquetas repetidos conservan
filas distintas. No se fusionan los dos vocabularios ni distintas extracciones.
Los estados desconocido, no extraído, no presente, no aplicable, no fiable y nulo
técnico nunca se convierten en cero; los candidatos no fiables permanecen en la
trazabilidad con su motivo, sin presentarse como cantidades disponibles.

Con una única versión se muestra directamente su desglose. Con varias, el selector
**Versión para consultar** comienza sin elección y permite una inspección local.
No modifica resoluciones ALTEN, importes certificados, elegibilidad ni filtros del
panel. Las extracciones de la versión se muestran separadas. Incluso una versión
sin extracciones permanece en el selector; no se elige otra por omisión.

Los **Datos complementarios y de referencia** muestran escalares disponibles,
incluyendo bases, IRPF y prorratas. Pueden repetir el desglose y nunca representan
pagos adicionales. Si no existe una lista de conceptos —como sucede en Coritel e
INSIS4— se explica expresamente y se conservan estos campos, sin reconstruir partidas.

Los desplegables permiten consultar identificadores completos, claves, estados,
motivos y páginas asociadas a cada hecho. El visor avanzado conserva todos los
hechos de todas las extracciones, diferenciadas por versión; no hay caché documental.
La lectura completa utiliza APIs del inspector, sin consultas SQL en la presentación.

Este incremento no certifica conceptos, suma importes, calcula neto de bonus ni
reinterpreta bruto/neto. **D.2.3-B** queda pendiente: selección de familias y magnitudes,
gráficos de conceptos y sus contratos de comparabilidad y representación. Las gráficas
actuales y las categorías documentales no cambian.

### Totales y componentes extraordinarios (D.2.3-B1)

El Panel de análisis y Evolución histórica distinguen **«Bruto/neto del documento,
incluidos posibles conceptos extraordinarios»** de una segunda gráfica de componentes.
Una nómina ordinaria conserva su total completo y su clasificación, aunque incluya un
bonus. La media móvil sigue siendo opcional y documental: no descuenta partidas para
fabricar una serie de salario recurrente. Los controles de componentes no la recalculan.

**Tipos de ingreso** mantiene la visibilidad de las categorías documentales.
**Componentes económicos visibles** permite ocultar independientemente las partidas
internas disponibles, con **Restablecer componentes** y preferencias de sesión.
No cambia cobertura, filtros, ficha, certificaciones ni restricciones. En el panel,
ambas gráficas respetan la intersección de empresa, periodo y documento. La histórica
reutiliza exactamente el mismo lector, proyector y controles, con su intervalo de años
existente; su sección de componentes aparece después de los registros documentales.
No hay un selector vacío cuando faltan puntos aptos.

El contrato de presentación `documentary-components/d2.3-b1-v1` admite únicamente estas
correspondencias exactas de extractor, código, denominación, categoría y marca de atraso,
siempre en la columna **devengos**, con importe canónico `present` decimal:

| Extractor | Código y denominación original | Representación |
|---|---|---|
| INECO | `9032` · `paga extra vera`; `9033` · `paga extra navi` | Extra de verano / Navidad incluida |
| INECO | `9RPE` · `r. pext dic 2012`, categoría `regularizaciones` | Ajustes de extras, en el periodo del documento |
| Exceltic | `1` · `P.P.EXTRA` | Prorrata de extras |
| Altran | `R1X` · `Parte Proporcional Pagas Extras` | Prorrata de extras |
| ALTEN (evidencia legacy) | `9016` · `P.P. Extra Verano`; `9017` · `P.P. Extra Navidad` | Prorratas de extras, conservando etiquetas distintas |
| ALTEN (evidencia legacy) | `9122` · `Bono`; `9030` · `Bono/Variable` | Bonus / variable |

Estas correspondencias no son equivalencias entre empresas. No dependen del mes, del
importe ni del nombre del archivo. La marca de atraso de los casos admitidos es `false`;
la regularización INECO se reconoce por su código, denominación y categoría explícitos,
no porque toda regularización o atraso sea una extraordinaria. Otras denominaciones,
códigos, categorías contradictorias o revisiones con otro vocabulario quedan fuera,
accesibles en la ficha. No se infiere que incentivos, beneficios, horas extras o
«gratificaciones extraordinarias» sean bonus. Las bases, porcentajes, deducciones y
prorratas escalares informativas no entran en esta gráfica.

Solo se representan conceptos de una versión con un único desglose de extracción
inequívoco. Multiversión, varias extracciones con conceptos o vocabularios alternativos
no provocan una elección automática. Las restricciones locales y multipago se calculan
sobre el contexto completo, antes de ocultar categorías, bruto/neto o componentes.
Seleccionar una versión para leerla en la ficha no autoriza su representación global.
Los totales multiversión que ya permiten los contratos anteriores se conservan.

Todos los componentes usan **marcadores aislados**, incluso las prorratas. No se trazan
líneas sin un contrato adicional de continuidad, ni se interpolan meses, apilan conceptos,
suman partidas o calculan netos parciales. Las empresas se separan visualmente cuando
hay varias. La información emergente y el desplegable conservan etiqueta, código,
importe exacto, estado, moneda registrada, periodo documental, página e identificadores
completos de documento, versión, extracción, ocurrencia y hecho. Los puntos coincidentes
pueden solaparse; sus ocurrencias permanecen separadas en la tabla de trazabilidad.
El eje utiliza EUR como convención visual, sin acreditar la moneda canónica ausente;
las monedas explícitas incompatibles se excluyen con aviso.

Sin desglose persistido, Coritel e INSIS4 conservan sus totales y extras independientes,
pero no generan componentes mediante diferencias matemáticas. **D.2.3-B2** queda pendiente
para otras familias y correspondencias justificadas. **D.2.3-C** deberá definir el contrato
para series de conceptos multiversión; B1 no aplica a partidas parciales las resoluciones
de totales ALTEN. No se crean observaciones ni se modifica SQLite.

### Clasificación y conciliación económica (D.2.3-B2a)

La ficha añade una sección **Clasificación y conciliación económica**, independiente
de las categorías documentales, totales certificados y series B1. Se muestra para la
versión seleccionada y para cada extracción por separado; no se crea una vista económica
combinada de versiones. Los hechos originales y su visor avanzado permanecen disponibles.

La clasificación inmutable separa **naturaleza contable** (devengo, deducción, base,
información, desconocida), **función económica**, **marca documental de atraso**,
**periodicidad** y **relación con los totales**. Un salario base identificado no implica
un salario mensual fijo comparable. Las periodicidades permanecen desconocidas: repetir
una partida no acredita un compromiso contractual. Beneficios documentados y bonus son
funciones distintas; un beneficio marcado como atraso conserva ambos atributos.

Las correspondencias exigen extractor, código, denominación, categoría, columna y marca
de atraso exactos. B1 sigue siendo la única fuente de sus correspondencias: B2a reutiliza
`component_label`, sin ampliar los puntos representables de B1. Las nuevas reglas cubren
salarios base, complementos identificados, retenciones, cotizaciones, algunas ayudas y
regularizaciones explícitas de INECO, Exceltic, Altran y ALTEN. Las variantes no previstas
permanecen **No clasificables**. No se usan empresa, fecha, frecuencia o importe para inferir
una función; no se homologan conceptos entre empresas. Las reglas no importan ni ejecutan
los parsers y no modifican la evidencia.

Las referencias escalares nunca se añaden a la lista de partidas. Bases y porcentajes son
referencias; las prorratas de cotización solo se identifican como tales en los campos y
extractores cuya sección se ha comprobado (INECO, Exceltic y Altran). Los totales de una
extra independiente se identifican mediante el tipo explícito de la misma extracción.
Códigos y etiquetas repetidos conservan ocurrencias distintas. Las posibles discrepancias
entre determinados escalares y su fila única se advierten sin corregir valores ni obtener
residuos salariales.

**Contrato de conciliación:** `reconcile(extraction, contract=None)` diagnostica devengos,
deducciones y relación bruto/neto exclusivamente dentro de una extracción. El contrato
explícito `ReconciliationContract` es una entrada de confianza del llamador: debe estar
revisado, referenciado y vinculado al nombre y revisión exactos del extractor. Debe
acreditar completitud, aditividad, convención de signos, unidad común y, para bruto/neto,
la compatibilidad de la fórmula. No se crea a partir de una igualdad numérica ni se
expone como casilla de autorización en la interfaz. El contrato admitido exige combinar
los importes con su signo documentado y restar las deducciones del bruto; formatos con
otra convención no se activan. Una proyección recortada respecto a los hechos de la
extracción se rechaza como conflicto, aunque el llamador aporte un contrato.

**Contratos B2b.1:** la ficha evalúa completitud por sección mediante
`breakdown_completeness.diagnose_breakdown()`. INECO y Exceltic tienen contratos
acotados a las revisiones exactas revisadas, con verificación del hash de todos los
hechos, estructura de filas, signos, unidad y total de la misma extracción.
Altran conserva cobertura de filas, pero no participación acreditada en los totales;
ALTEN no conserva revisión del parser original en su puente legado. Ambos permanecen
no evaluables, al igual que los formatos sin desglose Coritel e INSIS4.
Una sección puede conciliar mientras otra no es evaluable. La ficha muestra
completitud, contrato, componentes, total y diferencia, con trazabilidad desplegable.
**Conciliado aritméticamente no equivale a certificado económicamente.**
Véanse [justificaciones y límites](docs/breakdown-contracts.md).

El motor está probado con contratos sintéticos completos. Cuando existe soporte válido,
calcula exactamente con coeficientes enteros y resultados `Decimal`, sin `float`,
tolerancias ni redondeo dependiente del contexto decimal. Conserva fórmula, participantes,
total objetivo, documento, versión, extracción, referencia del contrato y diferencia.
Una diferencia se denomina **Diferencia no explicada**, nunca bonus o salario inferido.
Una igualdad no certifica partidas. Moneda ausente no se convierte en EUR, un grupo
sin partidas no se rellena con cero y los totales alternativos no se eligen por importe.
Los resultados distinguen documentado, calculado, estimado y no determinable; B2a no
emite estimaciones ni escribe derivados en SQLite.

Quedan fuera de este incremento:

- **B2b.2:** descomposición retributiva y fijo comparable, condicionados a contratos suficientes.
- **C:** selección/resolución autorizada de conceptos multiversión para series; B1 sigue excluyéndolos.
- **B2c:** gráficas normalizadas y equivalencias salariales entre 12 y 14 pagas.
- **D.2.5:** comparabilidad de IRPF, cotizaciones y bases; su identificación actual no la acredita.
