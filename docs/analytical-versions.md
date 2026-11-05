# Selección documental para componentes

El documento lógico agrupa versiones del mismo documento. Cada versión identifica
un archivo y segmento. Cada extracción pertenece a una sola versión y las
ocurrencias conservan extracción, posición documental y hechos. El bruto y el
neto representados proceden de las observaciones y certificaciones ya existentes.

## Autoridad de la decisión

La escritura canónica de A.3 valida una decisión humana de `VersionResolution`
contra todas las versiones del documento. La proyección v2 conserva esa decisión
en `projection/manifest` junto a la extracción original, su huella, la huella de
la implementación y las referencias a **todos** los hechos de origen y sus páginas.
La resolución selecciona una versión documental. Esta propiedad permite leer
partidas desde la extracción original explícitamente vinculada. Cada partida
sigue su contrato propio de representación y conserva su estado documental.

`analytical_version()` verifica en memoria el contrato v2 y la implementación
revisada, la identidad de la proyección derivada del manifiesto, la resolución
v1 decodificada con el lector A.3, el inventario completo, la extracción original
y las huellas de contenido. Contrasta todas las referencias, páginas y ocurrencias
con los hechos leídos y compara los campos proyectados con el original elegido.
Un productor nuevo requiere revisión explícita de compatibilidad.

Para las series se contrasta además el inventario con la procedencia del dataset.
Cuando hay observaciones bruta o neta, su soporte debe corresponder al campo
proyectado de la misma versión. Se excluyen totales alternativos o con soporte
incompatible. La política monoversión sigue requiriendo una sola extracción de
conceptos. Las restricciones locales y multipago se aplican al contexto completo.

## Inspección y representación

La ficha muestra el estado de autorización, el motivo revisado, las alternativas,
sus extractores, totales y componentes. La selección de inspección es local a la
ficha. Conciliación y reconstrucción operan exclusivamente sobre la extracción
abierta. Los visores de hechos conservan el acceso a los originales.

Los gráficos usan únicamente la extracción autorizada que satisfaga el contrato
de su serie. Códigos repetidos conservan sus ocurrencias distintas dentro de ella.
Un documento autorizado puede carecer de correspondencias B1. La igualdad del
bonus entre versiones tampoco constituye una decisión. Un rechazo de partidas
permite seguir consultando totales certificados bajo su propio contrato.

Para documentos sin decisión, la capacidad disponible es inspeccionar y comparar.
El mecanismo existente para registrar una elección revisada es el bundle A.3
con inventario esperado y su proceso canónico de construcción. No existe una
escritura interactiva de decisiones de versión. Los reconocimientos de hechos
de ManualDecision tienen un ámbito diferente. Este incremento sólo lee SQLite.

La selección documental no acredita periodicidad, cobertura salarial anual,
aditividad entre nóminas ni equivalencia entre empresas. Éstas siguen siendo
condiciones independientes para B2c.
