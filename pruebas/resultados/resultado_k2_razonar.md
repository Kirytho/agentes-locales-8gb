# ¿Le sirve a K2 razonar para programar? — medido 11/09/2026

## Cómo apareció

K2-Horizon **razonaba en todas las llamadas** y nadie lo había notado: ~550
caracteres de razonamiento por solicitud de edición. Con los 4.000 tokens de los
bancos le bastaba para pensar y responder, así que ningún resultado se veía
raro. Salió a la luz por una prueba con `max_tokens` pequeño, que consumió
entero pensando.

Tuvo dos consecuencias:

- **Un bug latente en el servidor MCP**, que concatenaba respuesta +
  razonamiento antes de buscar bloques: si el modelo esbozaba un bloque
  mientras pensaba, se aplicaban los dos. Ya está corregido.
- **La comparación contra Spark estaba sesgada**: a Spark se le apagó el
  razonamiento, a K2 no.

## Resultado, 5 ejecuciones por lado

Edición (el banco pide archivos enteros):

| | edición | rompió | seg/tarea |
|---|---:|---:|---:|
| K2 pensando | 61/65 | 0 | 24,0 |
| K2 sin pensar | 57/65 | 1 | 17,3 |

acierto p=0,364 · tiempo p<0,0001 (Mann-Whitney), **−28%**

Formato con bloques (lo que el MCP usa de verdad):

| | formato | aplica | PASA | rompió | seg |
|---|---:|---:|---:|---:|---:|
| K2 pensando | 62/65 | 60/65 | 56/65 | 3 | 10,0 |
| K2 sin pensar | 59/65 | 54/65 | 49/65 | 2 | 2,2 |

formato p=0,49 · aplica p=0,18 · PASA p=0,18 · rompió p=1,0

## La cuenta que decide

Ninguna caída de acierto es significativa, **pero todas apuntan a que pensar
ayuda un poco** a construir bloques. Lo que decide es el flujo real del servidor —
bloques primero, archivo entero si fallan —:

| | tiempo esperado | éxito final |
|---|---:|---:|
| pensando | 13,1 s | 99,3% |
| sin pensar | **6,1 s** | 98,1% |

**2,1x más rápido perdiendo un punto de éxito final.** Los reintentos son
internos del servidor: no le cuestan tokens al harness, solo segundos locales.

Aplicado en el modo de código (`--reasoning off`).

## Y lo que cambia para Spark

Ahora la comparación es pareja, los dos sin pensar:

| | GB | VRAM | edición | bloques PASA | bloques rompió |
|---|---:|---:|---:|---:|---:|
| Spark-X2.5-4B-Q4_K_M | 2,42 | 3.527 | 58/65 | 46/65 | **9** |
| K2-Horizon-7B-Q4_K_S | 5,00 | 6.142 | 57/65 | 49/65 | 2 |

- **Editando empatan** en igualdad de condiciones. El empate de ayer era contra
  un K2 que razonaba; sin esa ventaja K2 baja al nivel de Spark.
- **El problema de Spark con bloques no era el razonamiento apagado**: K2 sin
  pensar rompe la regresión 2 veces, Spark 9 (p=0,054, al borde). Es del modelo.
