# Escalado con muchos agentes, capacidad y largo de respuesta (19-22/08/2026)

Complementa a [concurrencia](resultado_concurrencia.md), que midió 1, 2 y 4
agentes. Aquí se barre hasta 16 agentes, se mide la capacidad sostenida y cuánto
del tiempo es generar texto.

**Bancos:** `pruebas/rendimiento/medir_escalado.py`, `medir_concurrencia.py`,
`medir_capacidad.py`, `medir_respuesta.py` y `medir_flujo_prompt.py`.

## 1. El umbral de kernel: con 9+ solicitudes simultáneas todo mejora

Al barrer el escalado apareció una discontinuidad que se repite, siempre en el
mismo punto. `medir_escalado.py` sobre gemma-4-E4B, con repeticiones y niveles en
orden alternado para descartar calentamiento:

| agentes | agregado (tok/s) | rango | por agente | prefill (ms) |
|---:|---:|---|---:|---:|
| 1 | 72,4 | 71,6 – 73,2 | 77,7 | 53 |
| 2 | 119,3 | 112,1 – 124,7 | 64,9 | 88 |
| 4 | 170,4 | 164,2 – 175,6 | 46,9 | 137 |
| 6 | 193,6 | 188,6 – 198,0 | 35,9 | 190 |
| 8 | 208,1 | 202,8 – 213,0 | 29,4 | 236 |
| **12** | **384,8** | 358,5 – 398,9 | **39,4** | 329 |
| 16 | 454,7 | 442,4 – 464,7 | 35,6 | 384 |

**Crudos:** `resultado_escalado.json`.

Entre 8 y 12 agentes el agregado casi se duplica **y** cada agente va más rápido.
Se reprodujo tres veces de forma independiente:

```
gemma-4-E4B    8 agentes 195,8  →   9 agentes 339,2   (+73%)
gemma-4-E2B    8 agentes 359,4  →   9 agentes 548,3   (+53%)
gemma-4-E4B    8 agentes 214,9  →  10 agentes 352,7   (+64%)   (barrido con niveles intermedios)
```

**Es del motor, no del modelo:** hasta 8 solicitudes en el lote, llama.cpp usa
multiplicación matriz-vector; desde 9 pasa a matriz-matriz, mucho mejor
aprovechada por la GPU.

**Depende de las solicitudes simultáneas, no de los slots:** con 8 solicitudes, un
servidor de 8, 12 o 16 slots da 220,0 / 222,4 / 225,9 tok/s. Abrir más slots con
poca carga no sirve.

**Consecuencias prácticas:**

- **Entre 4 y 8 agentes está la peor zona:** el agregado sube poco (170 → 208)
  mientras cada agente cae de 47 a 29 tok/s.
- **Cruzar a 9 o más da las dos cosas:** más rendimiento total y menos latencia
  por agente que con 8.
- **La VRAM no lo impide:** con `--kv-unified`, 16 slots cuestan 88 MiB más que 4.
  El límite pasa a ser el contexto compartido.
- Es una razón medida para preferir **divisiones finas** de una tarea (ver
  [reparto de piezas](resultado_reparto_piezas.md)).

**Defecto del banco corregido antes de confirmarlo:** `medir_concurrencia.py`
tenía 6 prompts y los repetía; con 8 o más agentes, la caché de prefijo regalaba
el prefill. El umbral se confirmó después de darle a cada agente un prompt único.

## 2. Un MoE en RAM escala mal con agentes

El mismo barrido sobre Qwen3-30B-A3B en RAM (servidor con 12 slots, sin swap):

| agentes | 30B en RAM | vs 1 | gemma-4-E4B en GPU |
|---:|---:|---:|---:|
| 1 | 12,5 tok/s | 1,00× | 72 |
| 4 | 20,3 | 1,62× | 170 |
| 8 | 24,1 | 1,93× | 208 |
| 12 | **27,3** | **2,18×** | **455 (6,3×)** |

Las columnas de gemma de esta tabla y de la siguiente vienen de ejecuciones
distintas a la del punto 1 (por eso 455 y 469 contra 384,8 con 12 agentes). Los
valores absolutos varían entre ejecuciones; la forma de la curva se mantiene.

Con 12 agentes, 455 contra 27,3 tok/s: 17 veces. Una primera medición daba 1,54×
con 4 agentes, pero el servidor tenía solo 4 slots y pedirle más medía cola, no
concurrencia; con 12 slots la conclusión se sostiene.

La explicación propuesta al principio fue que un MoE no aprovecha el lote porque
cada token usa expertos distintos. **Se corrigió el 23/08** midiendo un modelo
denso en RAM (Qwen3-4B, `resultado_concurrencia_qwen4b-denso-ram.json`):

| | 1 agente | 12 agentes | escala |
|---|---:|---:|---:|
| gemma-4-E4B denso, GPU | 84 | 469 | 6,3× |
| Qwen3-4B denso, RAM | 11,8 | 32,1 | **2,71×** |
| Qwen3-30B-A3B MoE, RAM | 12,5 | 27,3 | 2,18× |

El denso en RAM también se aplana: entre 8 y 12 agentes el agregado no se mueve
(31,9 → 32,1) mientras cada agente cae a 2,7 tok/s. El MoE añade una penalización
pequeña, pero **el factor dominante es el ancho de banda de la memoria**. En GPU no
pasa porque la VRAM tiene ancho de banda de sobra y el cuello de botella pasa a ser
el cálculo, que sí se amortiza al agrupar solicitudes.

**Consecuencia:** un modelo en RAM sirve para atender de uno en uno, no para
varios agentes a la vez.

## 3. Capacidad sostenida en lazo cerrado

`medir_capacidad.py`: C trabajadores envían solicitudes una tras otra durante 40 s.
Cada solicitud lleva ~600 tokens de prompt y pide 128 de respuesta, con un
identificador único para que la caché no la conteste. Pasa por el intermediario.

| escenario | agentes | solicitudes/min | p50 | p95 | errores |
|---|---:|---:|---:|---:|---:|
| código (GPU) | 4 | 36,3 | 5,4 s | 14,3 s | 0 |
| código (GPU) | 8 | 67,1 | 5,6 s | 14,1 s | 0 |
| código (GPU) | 9 | 72,0 | 6,4 s | 13,6 s | 0 |
| código (GPU) | 12 | **85,1** | 6,7 s | 14,8 s | 0 |

**Crudos:** `resultado_capacidad.json`.

El intermediario no añadió un costo apreciable: en una medición anterior, 15,6 s
contra 17,9 s del backend directo para la misma carga.

**Advertencia sobre el mismo archivo:** los escenarios "razonamiento (RAM)" y
"mezcla por ruteo" dan 87-141 tok/s, una velocidad de GPU y no del modelo de 30B en
RAM (12-27 tok/s). Lo más probable es que esas solicitudes se hayan derivado a la
GPU por falta de VRAM libre o de backend de RAM activo. **No se interpretan.**

## 4. El tiempo se va en generar: la instrucción de brevedad

Medido en una conversación de 8 turnos que alterna GPU y RAM (`medir_flujo_prompt.py`):

| | turnos | tiempo | por turno |
|---|---:|---:|---:|
| GPU | 4 | 12,0 s (**15%**) | 3,0 s |
| RAM | 4 | 67,2 s (**85%**) | 16,8 s |

En los turnos de RAM, con el 61% del prompt ya reutilizado, quedan ~218 tokens
por leer: ~2,4 s de los 16,8. **El resto es generación.** Optimizar el camino del
prompt podía ganar ~13%, no más.

**Ajustes del prompt: no conviene mover ninguno.** 3 repeticiones alternadas,
descartando una de calentamiento:

| configuración | media | rango | reutilización |
|---|---:|---:|---:|
| **referencia** | **75,2 s** | 73,1 – 79,2 | 55% |
| cabeza fija de 5 mensajes | 77,8 s | 74,7 – 83,8 | 56% |
| historial de 25/16 mensajes | 84,5 s | 75,4 – 99,7 | 64% |

Los rangos se solapan. Más historial reutiliza más (64%) pero **no baja el
tiempo**: se reutiliza más de un prompt más grande.
**Crudos:** `resultado_flujo_prompt.json` (la primera ejecución,
`resultado_flujo_181027.json`, incluye el arranque en frío: 242 s de calentamiento
contra ~75 s de las demás).

**Como el tiempo es generación, la palanca es el largo de la respuesta.** Sin
instrucción, el modelo escribía 800-1.400 tokens por respuesta:

| solicitud | sin instrucción | con brevedad |
|---|---|---|
| código (validar un RUT) | 998 tokens · 19,5 s | 340 tokens · 7,4 s |
| código (agrupar diccionarios) | 808 tokens · 15,9 s | 257 tokens · 5,6 s |
| análisis | 1.396 tokens · 116,7 s | 325 tokens · 35,7 s |
| análisis | 1.359 tokens · 116,1 s | 65 tokens · 6,9 s |

**Crudos:** `resultado_respuesta.json`.

Validado con la batería para ver si cuesta calidad: código 49/53 sin la
instrucción y 50/53 con ella. No cuesta.

**El bug que explicaba los 116 s:** en las respuestas largas de análisis, el
límite de tokens de razonamiento (4.096) al ritmo real del modelo en RAM
(6,9-9,0 tok/s) daba ~500 s, contra un tiempo de espera de 90 s. Cada solicitud
larga esperaba 90 s, fallaba y se **rehacía entera en la GPU**, sin avisar: la
elección de modelo por calidad se anulaba en silencio. Se corrigió derivando los
límites del ritmo medido (900 tokens de salida y 180 s de espera): 4 de 4
respuestas completas y 0 tiempos de espera agotados.
