# Qwen3.5-4B-Q4_K_M — confirma la hipótesis de compatibilidad con `turbo3` (27/07/2026)

Arnés: `eval_expertos.py`, backend Linux, `--cache-type-k/-v turbo3` (el mismo
que corrompía la salida de `Qwen3-4B` simple, ver
`resultado_experto_qwen3-4b_linux.md`).

## Por qué se probó este modelo puntual

El README de `buun-llama-cpp` menciona por nombre que **"Qwen35"** (Qwen3.5)
tiene un *price order* de degradación TCQ calibrado por los propios autores
del fork (160 pasos medidos sobre paneles KLD, igual tratamiento que le dan a
Gemma4-31B) — a diferencia de arquitecturas sin calibración propia, que caen
en un "generic cross-model order". El Qwen3 simple que falló no aparece
nombrado ahí. La hipótesis era: si el fork calibró específicamente para
Qwen3.5, debería ser seguro con `turbo3` donde el Qwen3 simple no lo fue.

## Resultado: hipótesis confirmada

Antes de ejecutar la batería completa, se repitió 3 veces el mismo prompt
(fizzbuzz) que había mostrado corrupción reproducible en Qwen3-4B — aquí salió
**código limpio y correcto las 3 veces**, con `kv_bpv: 3.5` confirmando que
`turbo3` estaba activo. Después, la batería completa:

| | nanbeige-3B | Qwen3-4B (`q8_0`, `turbo3` roto) | **Qwen3.5-4B (`turbo3`, sin problema)** |
|---|---:|---:|---:|
| Código | 20/25 | 20/25 | **23/25** |
| Velocidad | 62,0 t/s | 50,8 t/s | **98,3 t/s** |
| Cache-type | `turbo3` (seguro) | `q8_0` (`turbo3` corrompe) | **`turbo3` (seguro, confirmado)** |
| Falla en | duracion, romano, parentesis, bytes, lotes | duracion, desde_romano, camel, comprimir, parentesis | **duracion, desde_romano** |

Mejor resultado de los tres hasta ahora, en código y en velocidad — y esta
vez con el cache-type que se pretendía usar desde el principio.

## ¿Complementa a nanbeige? Ahora sí, limpio

- **Fallan los dos**: solo `duracion` — la única tarea que **ningún** modelo
  probado hasta ahora (ni en este proyecto ni en ejecuciones previas con otros
  modelos) resolvió bien. Parece ser una tarea genuinamente dura para
  modelos pequeños, no una debilidad puntual de ninguno.
- Qwen3.5-4B resuelve las **4 tareas** que le fallaban a nanbeige (romano,
  parentesis, bytes, lotes).
- Su único fallo extra (`desde_romano`) nanbeige lo resuelve bien.

**Juntos cubrirían 24/25** — solo `duracion` queda sin resolver por ninguno.
Esto es lo que se buscaba desde el principio: un complemento real, no
especulativo.

## VRAM con los dos cargados a la vez

Medido con `nvidia-smi`: nanbeige 3048 MiB + Qwen3.5-4B 2962 MiB = **6783 MiB
de 8192 MiB**, ~1GB libre. Caben los dos sin recortar `--ctx-size` de
ninguno, con el mismo margen ajustado que ya se había visto con Qwen3-4B.

## Fuente

Detalle completo en `resultado_experto_qwen35_4b_linux.json`.
