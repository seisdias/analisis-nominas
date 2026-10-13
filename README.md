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
ANALISIS_NOMINAS_CANONICAL_DB=/ruta/absoluta/canonica.sqlite \
  streamlit run app.py --server.address 127.0.0.1
```

La interfaz requiere una base canónica existente (esquema v8, journal DELETE),
preparada mediante el [constructor canónico](examples/canonical-build.md). Abre
[http://localhost:8501](http://localhost:8501). No crea ni migra bases. La ruta se indica exclusivamente
mediante `ANALISIS_NOMINAS_CANONICAL_DB`; no se usa la base legacy como alternativa.

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
