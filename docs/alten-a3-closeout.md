# ALTEN A.3 — informe de cierre, 13 de octubre de 2026

## A. Estado

**A.3 certificado, 100 % del alcance solicitado.** El desfase está justificado
documentalmente y resuelto mediante un oráculo privado revisado. La batería
privada integral y `check.sh` pasan sin fallos. No quedan bloqueos de certificación.
La integración en `dev` y la promoción de la base operativa no forman parte de
esta certificación y no se han ejecutado.

La rama es `feat/alten-a3-version-resolution`. Se preservaron los cambios iniciales
y `.agents/` sin modificarlo. No se editaron parsers certificados ni migraciones.

## B. Cambios

- `src/alten_resolutions.py`: contrato inmutable, inventario canónico y JSON
  estricto `alten-version-resolutions` v1. Rechaza campos y claves adicionales,
  tipos incorrectos, duplicados, inventarios vacíos y selección fuera de inventario.
- `src/alten_projection.py`: validación del inventario y ámbito, soporte físico,
  completitud de las decisiones multiversión y proyección v2 con manifiesto
  recuperable. Rechaza cambios de decisión, proyecciones v1 y estados parciales
  en reejecución; exige reconstrucción. Transacción con rollback.
- `src/canonical_build.py`: entrada opcional `alten_resolutions`, relativa al JSON
  de configuración; mantiene publicación atómica y sin sobrescritura.
- Pruebas: `tests/integration/ingestion/test_alten_resolutions.py`,
  `test_alten_projection.py`, `test_canonical_builder.py` y
  `tests/private/test_alten_a3_projection.py`.
- `README.md`: contrato y procedimiento; este informe documenta el alcance real.

`canonical.decisions.ManualDecision` solo admite reconocimientos documentales sin
resolución ni efecto económico. El contrato de selección no modifica ni duplica
ese mecanismo. La base continúa en esquema v8. A.2 conserva sus datos originales;
las nuevas construcciones usan identidades de proyección v2.

## C. Verificación

| Comprobación | Resultado |
|---|---|
| `bash scripts/check.sh` final | Correcto |
| Pytest público, incluido por `check.sh` | 1.378 superadas |
| Ruff | 0 diagnósticos |
| mypy | 0 diagnósticos |
| Pruebas privadas dirigidas A.3 | 3 superadas, incluidas en las 376 |
| Suite privada integral con oráculo revisado | 376 superadas, 0 fallos, 0 errores |
| Reproducibilidad global y nueva candidata A.3 | Mismo estado lógico canónico |
| Reejecución en copia temporal | Idéntico estado, incluidas marcas operativas |
| Integridad SQLite y claves foráneas | Correctas |
| `git diff --check` | Correcto |

**Total final: 1.754 pruebas superadas** (1.378 generales + 376 privadas), sin
pruebas omitidas en esas ejecuciones. La batería privada completa tardó 261,68 s.
Además se aplicaron las tres verificaciones dirigidas a la nueva candidata
certificada mediante el script privado, incluida la reejecución en copia.

La investigación encontró una compilación histórica renombrada sin cambio de
SHA256, una reproducción individual bajo su antigua ruta y tres nóminas de nuevos
periodos. Ninguna versión histórica desapareció. El inventario pasa de 55 a 59
PDFs físicos y de 84 a 88 páginas, con 55 documentos lógicos y 82 versiones.
Las rutas, hashes, páginas e identidades canónicas exactas se guardan únicamente
en `data/private/a3-oracle-review/documentary-audit.json` y `findings.md`.

Se revisaron visualmente las cuatro páginas nuevas y se contrastaron las filas
por coordenadas PDF. El nuevo `alten-manifest-a3-v2.json` conserva las 78 versiones
históricas, actualiza la ruta de la compilación y añade cuatro versiones; el
manifiesto original sigue intacto. No se generaron expectativas económicas desde
el parser productivo. La extensión reproducible está documentada en el script
privado `a3-oracle-review/extend_oracle.py`, que no permite sobrescritura.

Los 85 errores históricos procedían de la fixture de inventario obsoleta. Los
cuatro fallos correspondían a esa misma fixture solicitada desde ingesta, los
recuentos del puente ALTEN y los recuentos de las dos pruebas globales. Se detectó
además una suposición obsoleta: distintas versiones físicas no siempre implican
contenido económico diferente. La reproducción individual equivale a una página
de la compilación; la nueva prueba admite exclusivamente esa pareja revisada y
mantiene la diversidad del resto. No se deduce un pago adicional ni sustitución.

Las cantidades globales se actualizan por deltas verificables: cuatro versiones,
tres documentos lógicos y 28 filas de conceptos adicionales. Se añaden 464 hechos
(4 × 39 + 28 × 11) y 440 vínculos de hechos a páginas (4 × 33 + 28 × 11).
La revisión conserva también los descuadres impresos; no ajusta importes.

En una ejecución pública inicial falló una aserción preexistente que busca el
texto `777` en toda la salida del inspector: apareció dentro de un identificador
aleatorio. La batería final pasó sin cambiar esa prueba. Es un riesgo de
intermitencia ajeno a A.3, registrado para su seguimiento.

## D. Resultado documental

| Métrica ALTEN | Resultado |
|---|---:|
| Documentos lógicos | 55 |
| Versión única | 30 |
| Multiversión | 25 |
| Resoluciones verificadas/aplicadas | 25 |
| Resoluciones pendientes | 0 |
| Versiones conservadas | 82 |
| Documentos con una proyección | 55 |
| Observaciones del baseline A.2 | 60 |
| Observaciones de la candidata A.3 | 110 |
| Observaciones ALTEN elegibles para KPIs | 0 |

Los 25 archivos/páginas indicados por el usuario se cotejaron unívocamente con
identidades SQLite, inventario y SHA256 del PDF disponible. Se conservaron las
compilaciones y todas las versiones. Los valores proyectados coinciden exactamente
con los hechos originales; los importes de los 30 documentos A.2 se mantienen.
Las observaciones siguen siendo `evidence_only` y no aparecen como candidatos.

La revisión bancaria previa es una declaración del usuario; no se realizó una
nueva conciliación bancaria ni se inventaron importes. Estas verificaciones no
sustituyen un oráculo económico independiente para los documentos nuevos.

## E. Seguridad y artefactos locales

No se modificó ninguna base privada preexistente, incluida
`data/private/canonical.sqlite` y el baseline A.3: SHA256 antes/después idénticos.
Se verificaron también los hashes de todos los módulos de parsers y del
manifiesto histórico original. El esquema v8 y `.agents/` permanecen intactos. No hubo operaciones destructivas, commits, push, merge ni PR.
Los datos y decisiones privados siguen excluidos de Git; no se publicaron ni
transmitieron a servicios externos.

Se crearon, sin sobrescribir archivos, bajo `data/private/`:

- `alten-resolutions-a3-v1.json`: las 25 decisiones, con permisos 0600.
- `canonical-build-a3-v1.json`: configuración privada, con permisos 0600.
- `canonical-candidate-a3-v1.sqlite`: construcción intermedia, conservada.
- `canonical-candidate-a3-v2.sqlite`: candidata verificada final.
- `canonical-candidate-a3-v2-repro.sqlite`: construcción de reproducibilidad.
- `canonical-candidate-a3-certified-v1.sqlite`: reconstrucción nueva de esta
  recertificación, comparada con la candidata v2 y reejecutada en copia temporal.
- `alten-manifest-a3-v2.json`: oráculo documental revisado, separado del histórico.
- `a3-oracle-review/`: auditoría privada, hashes iniciales, evidencia visual,
  script de extensión y script de verificación de la nueva candidata.

Las bases nuevas y los artefactos privados de revisión tienen permisos 0600. Cada construcción inventarió 248
PDFs en los seis corpus: 237 procesados, 11 omitidos por los mecanismos existentes,
0 fallos. La candidata final contiene 472 observaciones totales; 110 son ALTEN.

## F. Siguientes pasos

La integración en `dev` y cualquier promoción de la candidata a base operativa
requieren instrucciones del usuario. No se realizaron commits, push, merge ni PR.
La revisión documental no pretende autenticar criptográficamente al emisor ni
repetir la conciliación bancaria previa; certifica las garantías exigidas del
sprint sobre la evidencia local revisada.

Comandos reproducibles desde el repositorio:

```sh
bash scripts/check.sh
venv/bin/python -m pytest -q --run-private tests/private
venv/bin/python -m pytest -q --run-private tests/private/test_alten_a3_projection.py
PYTHONPATH=. venv/bin/python data/private/a3-oracle-review/verify_certified_candidate.py
PYTHONPATH=. venv/bin/python data/private/verify-alten-a3-selection-v1.py
venv/bin/python -m src.canonical_builder \
  --config data/private/canonical-build-a3-v1.json \
  --output data/private/UNA-CANDIDATA-NUEVA.sqlite
```

La última orden requiere un destino inexistente. La comparación reproducible
excluye únicamente metadatos operativos según `CanonicalStateReader`; no exige
igualdad binaria entre dos SQLite construidos en momentos distintos.
