# Mover la memoria al final del prompt

**Fecha**: 18/08/2026 · **Scripts**: `medir_reuse_intermediario.py`, `eval_memoria_posicion.py`

## Qué se cambió

La memoria recuperada iba en el mensaje `system`, es decir, al **principio*** del
prompt. Como su contenido cambia en cada turno, cambiaba el **prefijo**, y el
caché de prefijo de llama-server —que exige que el comienzo sea idéntico— quedaba
inservible.

Ahora va unida al **último mensaje del usuario**. Son dos inyectores y **hubo que
mover los dos**: el de fragmentos relevantes y el de bloques de memoria
(~286 caracteres de contexto de sesión). Mover solo el primero no produjo
ninguna mejora.

Para volver atrás existe una variable de entorno que restaura la memoria al inicio.

## Velocidad

| | tokens de prompt reprocesados |
|---|---:|
| memoria al inicio | **97,1%** |
| solo el primer inyector movido | 98,9% |
| **los dos movidos** | **90,4%** |

Mejora, pero menos de lo esperado. El tiempo total de prompt bajó de 11.441 a
10.917 ms (−4,6%).

## Calidad: no se perdió nada

El riesgo real no era de forma sino de atención: el modelo pondera distinto lo
que está al principio y lo que está junto a la pregunta. Se midió con
`eval_memoria_posicion.py` — 5 conversaciones donde la respuesta depende de un
dato dicho 4 turnos antes, 3 repeticiones:

| | recuperaciones correctas |
|---|---:|
| memoria al inicio | 14/15 |
| **memoria al final** | **15/15** |

Sin pérdida. (Con n=1 el resultado se había invertido, 5/5 contra 4/5: otra vez
la lección de que una sola ejecución no distingue nada.)

## Lo que impide llegar más lejos

Desde el turno 5, `cache_n` vuelve a 0. La causa es el manejo de contexto: trunca a
los últimos N mensajes (15 en GPU, 8 en CPU). El log lo muestra:
**`Messages: 15 -> 9`**.

Una ventana deslizante **no puede tener prefijo estable por construcción**: cada
turno descarta el mensaje más viejo, así que el comienzo del prompt siempre
cambia. Además la nota que se antepone (`"Hay N mensajes anteriores..."`) lleva
un número que también cambia.

Para aprovechar el caché de verdad habría que conservar una **cabeza fija** —los
primeros K mensajes siempre iguales— y recortar solo la parte intermedia. Eso es rediseñar
el manejo de contexto, no un ajuste.
