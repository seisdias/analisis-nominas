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
