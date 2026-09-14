# Memoria híbrida (BM25 + vector + RRF) vs similitud plana

**Fecha**: 11/08/2026
**Dónde**: primero en una copia experimental (validado) y después integrado en el módulo de memoria del intermediario (11/08/2026)
**Banco**: `pruebas/resultados/banco_memoria_multihop.json`, 19 casos (7 directa, 12 multihop) — el mismo banco usado para el hallazgo original.

## Qué se comparó

- **Antes**: la búsqueda en la memoria de sesión — un solo ranking, similitud de vector (`turbovec`/`TurboQuantIndex`) contra el embedding de la pregunta.
- **Después**: mismo método, pero fusiona dos rankings — vector (igual que antes) + BM25 (coincidencia de palabra exacta, `rank_bm25`) — vía Reciprocal Rank Fusion (`1/(60+rank)` sumado entre los dos).

Ningún otro cambio: mismos casos, mismo `k=5`, mismo modelo de embeddings.

## Resultado

| | Directa (control) | Multihop (el test) |
|---|---:|---:|
| **Antes** (solo vector) | 7/7 | 9/12 |
| **Después** (híbrido) | 7/7 | **12/12** |

La parte directa no se movió (esperado — ahí el vector solo ya bastaba). El cambio real está en multihop: corrigió exactamente los 3 fallos que había antes.

## Caso por caso, lo que cambió

Las preguntas del banco se redactaron en lenguaje coloquial; aquí se muestran en
español neutro. El JSON conserva el texto exacto con el que se midió.

| Caso | Pregunta | Antes | Después |
|---|---|---|---|
| `multihop_3` | "¿funcionará bien si lo inicio tal como dije?" | FALLO — no aparecía en top-5 | OK (top-5) |
| `multihop_4` | "¿cabrá en la tarjeta gráfica si hago ese cambio?" | FALLO — no aparecía en top-5 | OK (top-2) |
| `multihop_10` | "¿cuál era el número que habíamos puesto para eso?" | FALLO — no aparecía en top-5 | OK (top-4) |

Los otros 9 casos multihop y los 7 directa ya funcionaban bien antes — el híbrido no los rompió (verificado, no asumido: se ejecutó el banco completo, no solo los 3 casos que fallaban).

## Por qué se movió justo eso

Los 3 casos que fallaban comparten un patrón: la pregunta usa referencia vaga ("eso", "así como dije") **sin repetir ninguna palabra** del dato que hacía falta. El vector solo no encontraba una similitud de *significado* suficiente. BM25 tampoco encuentra coincidencia de palabra ahí (no hay palabra compartida) — pero al fusionar los dos rankings vía RRF, el dato sube lo suficiente en al menos uno de los dos como para entrar al top-k combinado, en vez de perderse en la cola de ambos rankings por separado.

## Costo

- Un archivo modificado (el módulo de memoria), una dependencia nueva (`rank_bm25`, ligera, sin PyTorch).
- BM25 se reconstruye en cada búsqueda — barato para los tamaños de bloque que usa el intermediario (50-500 entradas), no se probó con volúmenes mayores.
- No se necesitó grafo, Neo4j, ni ningún servicio nuevo — la alternativa pesada que se había descartado por falta de evidencia previa.

## Bug real encontrado y arreglado: escala del score

Este cambio casi se lleva a producción roto. El paso que añade la memoria
filtra resultados con `score < 0.35` (`min_relevance`) antes de inyectarlos
al contexto — calibrado para similitud de coseno (rango 0-1). El score
crudo de RRF vive en otra escala completamente distinta: medido, el máximo
posible con `K=60` es **0.033*** — ni el mejor resultado llega ni
cerca de 0.35.

Sin arreglar esto, conectado a producción tal cual, **el filtro descartaría
el 100% de los resultados siempre, en silencio** — la inyección de memoria
dejaría de funcionar del todo, peor que antes (que al menos inyectaba algo
cuando superaba 0.35).

**Arreglo**: normalizar el score a 0-1 antes de devolverlo — `raw / (2.0 /
K)`, ya que el máximo teórico de RRF con 2 rankings es `2/K`.
Verificado: pasa de `~0.033` a `~0.99` para el mismo resultado.

**Verificado de nuevo con el filtro real en medio** (el banco ahora
simula `min_relevance=0.35` exactamente como lo hace
el intermediario, no solo el ranking crudo): **12/12 multihop, 7/7
directa** — sigue en el mismo resultado, ahora sobreviviendo la condición
real de producción, no solo el ranking aislado.

## Conclusión: ¿mejora el sistema completo?

**La recuperación mejora, medido y verificado dos veces** (ranking crudo,
y con el filtro real de producción simulado encima). Pero "mejora el
sistema completo" todavía no está probado — dos brechas reales quedan
abiertas:

1. **No se probó con tráfico real end-to-end** — que la respuesta del LLM
   sea mejor cuando recibe el contexto correcto, no solo que el contexto
   correcto llegue a estar disponible. Retrieval correcto es necesario,
   no suficiente.
2. **No se probó con los otros bloques de memoria** (la memoria central y la
   de archivo) — el cambio está en la clase base común, en
   teoría aplica a los tres, pero solo se probó la memoria de sesión con este
   banco.

Tampoco se midió impacto en latencia bajo carga real (el banco se ejecuta en
milisegundos con pocos cientos de entradas; producción puede tener
sesiones más grandes, y BM25 se reconstruye en cada búsqueda).
