
---

## Medición contra el intermediario (el caso que faltaba)

Conversación de 8 turnos contra `:8086`, con memoria inyectada, servidor caliente:

| | sin `--cache-reuse` | con `--cache-reuse 256` |
|---|---:|---:|
| tokens de prompt en total | 2.017 | 2.019 |
| **de esos, hay que procesar** | **1.958 (97,1%)** | **1.960 (97,1%)** |
| tiempo total de prompt | 11.441 ms | 12.757 ms |

**`--cache-reuse` tampoco sirve aquí. Descartado.***

> Aviso: una primera ejecución dio 37.195 ms para el caso "sin", lo que parecía un
> −66% a favor de la bandera. Era **arranque en frío**: servidor recién
> iniciado y modelo de embeddings cargándose. Repetida con el servidor
> caliente, la diferencia desaparece. Los tokens procesados eran idénticos en
> ambas (97%), y eso fue lo que delató la medición mala.

## El hallazgo real: el 97% se reprocesa en cada turno

Desde el turno 3 en adelante, **`cache_n` es 0**: no se recupera ni un token.

La causa no es una bandera que falte, es **dónde se inyecta la memoria**.
El paso que añade la memoria la ponía en el mensaje `system`, es decir, al **principio***
del prompt. Como ese contenido cambia en cada turno (la memoria recuperada es
distinta), el prefijo cambia, y el caché de prefijo del servidor —que necesita
que el comienzo sea idéntico— queda inservible.

Comparación: enviando **directamente al backend**, sin intermediario, `prompt_n` se
queda en 73 tokens por turno aunque el historial crezca. Con el intermediario en
medio, sube a 316.

**La mejora no es de configuración, es de arquitectura**: inyectar la memoria
**al final**, junto al último mensaje del usuario, en vez de al principio. Con
eso el prefijo (system fijo + historial) queda estable y el caché del servidor
vuelve a servir. Falta medir cuánto rinde y verificar que el modelo preste la
misma atención a la memoria puesta al final — no es gratis: la posición cambia cómo
la pondera.
