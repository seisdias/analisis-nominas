# Análisis de Nóminas

Proyecto Python en fase temprana para extraer texto de PDFs laborales, interpretar
formatos conocidos y consultar nóminas en SQLite y Streamlit. No incluye OCR.
Alten, Altran, Exceltic, Ineco e Insis tienen parsers iniciales; Coritel devuelve
un error explícito hasta disponer de una implementación fiable.

## Instalación (Python 3.14.0)

```bash
python3.14 -m venv venv
source venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m scripts.init_db
streamlit run app.py
```

La inicialización crea únicamente el esquema, sin datos. La base predeterminada
es `data/runtime/nominas.sqlite`; para otra ruta: `python -m scripts.init_db --db RUTA`.
Las ingestas locales se ejecutan como módulos, por ejemplo `python -m scripts.ingest_ineco`.
La UI admite `ANALISIS_NOMINAS_DB`. Los importes opcionales todavía usan ceros por
compatibilidad con el modelo: no deben interpretarse como extracción confirmada.
Los parsers requieren periodo y totales reconocibles, rechazan descuadres y la
persistencia rechaza IDs duplicados. No se garantiza cobertura de todos los formatos.

## Validación

```bash
./scripts/check.sh
python -m pytest -q
python -m pytest --collect-only
```

`check.sh` ejecuta Ruff, mypy y tests portables. Utiliza `PYTHON`, el entorno activo,
`venv/bin/python` o `python3`, y exige la versión de `.python-version`.
Las dependencias runtime y dev están fijadas por separado. La línea base estática
solo admite diagnósticos heredados enumerados; errores nuevos o entradas obsoletas
fallan. No actualizarla automáticamente para aceptar errores nuevos.

Los tests de `tests/integration/` son locales y no se recogen por defecto:

```bash
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
