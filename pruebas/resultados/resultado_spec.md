# Decodificación especulativa sin modelo borrador (`--spec-type`) — backend GPU

**Fecha**: 17/08/2026
**Modelo**: Qwen3.8-9B-Q5_K_M, RTX 3060 Ti 8 GB, `-ngl 99`, ctx 16384
**Script**: `pruebas/medir_spec.py` · **Crudos**: `pruebas/resultado_spec.json`
**Método**: 3 repeticiones × 5 prompts, `temperature 0`, `seed` fijo, thinking apagado
(igual que producción). Se mide `timings.predicted_per_second` que devuelve
llama-server, no tiempo de pared.

## Resultado en una línea

**Sirve muchísimo en un caso y perjudica en el resto.** No es una bandera para
dejar puesta siempre.

## Media general (engañosa, ver el desglose)

| config | media tok/s | min | max | vs baseline |
|---|---:|---:|---:|---:|
| baseline | 59,4 | 58,5 | 60,7 | — |
| `ngram-cache` | 66,4 | 43,2 | 124,0 | +11,7% |
| `copyspec` | 70,5 | 53,2 | 141,8 | +18,7% |
| `suffix` | 71,9 | 37,7 | 173,7 | +20,9% |
| `recycle` | 49,7 | 29,2 | 72,7 | −16,3% |

La media esconde lo que importa: el rango va de 37 a 173 tok/s. El promedio de
esas dos cosas no describe ninguna de las dos.

## El desglose, que es el verdadero resultado

| config | codigo_clase | codigo_refactor | codigo_tests | prosa | **copia_larga** |
|---|---:|---:|---:|---:|---:|
| baseline | 58,8 | 60,1 | 59,6 | 59,6 | 59,1 |
| `ngram-cache` | 48,2 | 52,0 | 52,3 | 55,6 | **123,8** |
| `copyspec` | 62,0 | 56,4 | 53,9 | 58,4 | **122,1** |
| `suffix` | 49,3 | 44,8 | 52,2 | 39,7 | **173,2** |
| `recycle` | 39,1 | 58,6 | 54,2 | 30,9 | 65,8 |

`copia_larga` es el prompt donde la respuesta repite casi textual un bloque que
ya venía en la solicitud (devolver un archivo con un nombre cambiado). Ahí `suffix`
da **2,9×** — 173,2 contra 59,1 — y con **salida byte a byte idéntica** al
baseline en las 3 repeticiones (mismo hash `fdc79e`).

En todo lo demás pierde: escribir código nuevo o prosa baja entre 15% y 33%,
porque el borrador falla casi siempre y cada fallo se paga.

## Por qué pasa esto

Estos métodos no usan un segundo modelo: adivinan que lo que viene ahora ya
apareció antes en el texto. Cuando la tarea es *copiar con cambios* (refactor,
reescribir un archivo, aplicar un diff), aciertan casi siempre y el modelo
verifica varios tokens en una sola pasada. Cuando la tarea es *escribir algo
nuevo*, no aciertan nunca y el trabajo de adivinar y descartar es puro costo.

## Aviso sobre la salida

Con `temperature 0` el baseline es determinista (mismo hash en las 3
repeticiones). Las configuraciones especulativas **no siempre** devuelven lo
mismo que el baseline: en `codigo_clase` con `suffix` cambió el texto. La
verificación por lotes cambia el orden de las sumas en punto flotante y eso
basta para desempatar de otra forma un token. En `copia_larga` sí dio idéntico.
Es decir: no se puede prometer "misma salida, más rápido" en general.

## Qué hacer con esto

No es una bandera global. Sirve por tipo de tarea, y el intermediario **ya sabe** el tipo
de tarea: lo clasifica antes de elegir el modelo.

**Por solicitud no se puede**: se probó enviar `speculative.types` en el cuerpo de la
solicitud (y `spec_type`, y la forma en lista). El servidor acepta la solicitud sin
error pero **ignora el parámetro** — las cuatro formas dieron 58,7-59,0 tok/s,
es decir, velocidad de baseline. `/props` expone
`default_generation_settings.params.speculative.types = none` como propiedad del
servidor, no de la solicitud. La estrategia se fija al iniciar y no se puede cambiar.

Entonces, para aprovecharlo hay dos caminos: un segundo servidor GPU con
`--spec-type suffix` al que se enrute solo la reescritura sobre texto dado (cuesta
VRAM: otro modelo cargado), o cambiar la estrategia del único servidor según el
perfil, que implica reiniciarlo — inaceptable en caliente. Con 8 GB, ninguno de
los dos es viable hoy; con más VRAM, el primero es directo.

`recycle` se descarta: pierde en todos los casos.

## MTP (`--spec-type draft-mtp`): no cabe, y ya sabemos por qué

Qwen3.8-9B **sí trae** los tensores (`qwen35.nextn_predict_layers`,
`blk.32.nextn.eh_proj.weight`), pero el servidor no inicia. El log es explícito:

```
common_fit_params: failed to fit params to free device memory:
n_gpu_layers already set by user to 99, abort
srv load_model: [spec] could not find a safe target/MTP fit
```

Se probó bajando el contexto a 8192 y a 4096: **falla igual**. Y ahora se sabe
por qué no basta — bajar el contexto libera poco:

| ctx | VRAM usada | velocidad |
|---|---:|---:|
| 16384 | 6875 MiB | 59,4 |
| 8192 | 6730 MiB | 59,0 |
| 4096 | 6676 MiB | 59,2 |

De 16k a 4k se recuperan **199 MiB**, y el contexto borrador necesita ~900 MiB.
El peso está en el modelo (~6,1 GB), no en el KV. Bajar el contexto no es el
camino, y además no aporta velocidad (59,4 / 59,0 / 59,2: los tres iguales
dentro del ruido).

**El camino que queda**: un cuantizado más pequeño. Q4_K_M pesa ~5,4 GB contra los
~6,1 GB de Q5_K_M — esos ~700 MiB más los 199 del contexto acercan el presupuesto
a lo que MTP pide. Habría que medir si el +50% de MTP compensa la pérdida de
calidad de bajar de Q5 a Q4, con la batería y 3 repeticiones.
