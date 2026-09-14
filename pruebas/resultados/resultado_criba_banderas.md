# Criba de banderas de llama-server en dos etapas (19/08/2026)

**Problema:** el binario de `llama-server` tiene unas 270 banderas y probarlas
todas con la batería completa es multiplicativo. Con varias cuantizaciones y 3
repeticiones, serían cientos de baterías de 53 tareas.

**Solución:** un camino de tres pasos, donde cada paso descarta antes de gastar en
el siguiente.

**Scripts:** `pruebas/rendimiento/detectar_gguf.py`, `cribar_flags.py` y
`pruebas/instrumentos/probar_modelo.py`.
**Crudos:** `resultado_criba_2b-q5.json`.

## Paso 1: preguntarle al archivo qué soporta

`detectar_gguf.py` lee los nombres de los tensores en la cabecera del GGUF. Así
se evita probar lo que no aplica (MTP sin cabezas MTP, opciones de MoE en un
modelo denso):

| modelo | arquitectura | MoE | MTP |
|---|---|---|---|
| Qwen3-30B-A3B | qwen3moe | sí (`ffn_*_exps`) | no |
| Qwen3.8-9B | qwen3 | no | sí (`nextn.*`) |
| Qwen3.8-2B | qwen3 | no | sí |

**Trampa encontrada:** buscar el texto suelto en la cabecera da falsos positivos,
porque el vocabulario del tokenizador contiene palabras como "expert". El 9B denso
aparecía como MoE. Hay que mirar solo los nombres con el patrón
`blk.<n>.<nombre>`.

## Paso 2: criba rápida, solo velocidad

`cribar_flags.py` inicia el servidor con cada configuración y mide **solo
velocidad**, ~40 s por configuración. Usa dos prompts a propósito:

- **copia:** la respuesta repite texto que ya está en la solicitud;
- **generación:** escribir código nuevo.

La decodificación especulativa acelera un caso y perjudica el otro; promediarlos
esconde las dos cosas.

Qwen3.8-2B Q5_K_M (1,35 GB), en tok/s:

| configuración | copia | generación | generación vs base |
|---|---:|---:|---:|
| base | 185,4 | 185,0 | — |
| **draft-mtp** | 187,1 | **212,7** | **+15%** |
| ngram-simple | 185,7 | 187,1 | +1% |
| ngram-map-k4v | 186,6 | 187,1 | +1% |
| ngram-map-k | 177,5 | 185,4 | 0% |
| ngram-mod | 185,0 | 185,2 | 0% |
| kv f16 | 185,0 | 184,9 | 0% |
| kv q4_0 | 173,5 | 179,6 | −3% |
| copyspec | 170,3 | 176,4 | −5% |
| ngram-cache | 168,8 | 171,5 | −7% |
| draft-dflash | 173,1 | 169,3 | −8% |
| recycle | 85,0 | 129,1 | −30% |
| suffix | 126,4 | 124,8 | −33% |

## Paso 3: batería completa solo sobre lo que sobrevivió

`probar_modelo.py` con la configuración ganadora (`draft-mtp`):

- **215,0 tok/s (+21%)** por +192 MiB de VRAM;
- calidad igual dentro del ruido: código 25/53 contra 28/53 sin la bandera, y
  razonamiento 8/25 contra 5/25.

Es lo esperable: la decodificación especulativa no cambia lo que el modelo dice,
solo cuánto tarda. **MTP funciona en el 2B**, donde sobra VRAM. En el 9B siguió
bloqueado por los ~0,93 GB que pide el contexto del borrador (ver
[spec](resultado_spec.md)).

## Salvedades

- **Una ejecución por configuración en la criba:** todo lo que esté por debajo
  de ±5% es ruido.
- **El prompt de "copia" pide renombrar variables, no copiar literalmente.** No es
  una prueba justa para `suffix`, que está pensado para reescritura literal. En
  ese caso sí dio 2,9× (ver [spec](resultado_spec.md)).
- **Discrepancia sin aclarar:** las notas de ese día registran `dflash` como "no
  inicia", pero el JSON publicado tiene velocidades para `draft-dflash`. No se
  pudo determinar cuál corresponde a qué ejecución. En cualquiera de los dos casos
  no mejora a la base.
