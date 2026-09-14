# Qwen3-4B-Q4_K_M — ejecución en Linux/CachyOS junto a nanbeige (27/07/2026)

Arnés: `eval_expertos.py`. Backend: `llama-server` compilado nativo para Linux
(`backends/linux/`), ejecutándose **al mismo tiempo*** que `nanbeige4.2-3b` en la
misma GPU (RTX 3060 Ti), puerto 8081.

## Hallazgo importante: el cache-type `turbo3` corrompe la salida de este modelo

La primera ejecución (`resultado_experto_qwen3-4b_linux.json`, con
`--cache-type-k/-v turbo3`, igual que usa `nanbeige` sin problema) dio
**0/25** — pero no porque el modelo respondiera mal, sino porque generaba
**tokens repetidos que rompen la sintaxis**: por ejemplo `elif i i i % 3 == 0:`
en vez de `elif i % 3 == 0:`. Confirmado repitiendo el mismo request a mano
contra el backend crudo.

Al cambiar a `--cache-type-k/-v q8_0` (sin tocar nada más), la corrupción
**desapareció por completo** y el modelo generó código limpio. Conclusión:
**`turbo3` no es seguro para todos los modelos** — funciona perfecto con
`nanbeige4.2-3b` pero corrompe la salida de `Qwen3-4B`, probablemente por
alguna diferencia de arquitectura (dimensiones de atención / GQA) que el
codebook de TurboQuant no maneja bien en este caso. Cualquier backend nuevo que se
sume a este proyecto debería **verificarse con `eval_expertos.py` antes de
confiar en `turbo3`**, no asumir que es seguro solo porque funcionó con otro
modelo — el propio `README-linux-build.md` ya quedó actualizado con esto.

Como efecto colateral: la velocidad "corrupta" con `turbo3` medía ~82 t/s,
pero era basura — la velocidad **real y válida** con `q8_0` es más baja,
**50,8 t/s**. No es un ahorro gratis: `turbo3` sí es más rápido cuando
funciona, pero aquí no se puede usar.

## Resultado (con cache-type correcto, `q8_0`)

| | nanbeige-3B | Qwen3-4B |
|---|---:|---:|
| Código | 20/25 | 20/25 |
| Velocidad | 62,0 t/s | 50,8 t/s |
| Cache-type usado | `turbo3` (seguro para este modelo) | `q8_0` (`turbo3` corrompe) |
| Falla en | duracion, romano, **parentesis**, bytes, lotes | **duracion**, desde_romano, camel, comprimir, **parentesis** |

## ¿Se complementan de verdad?

**Parcialmente — menos limpio de lo que sugería el dato viejo (de Windows).**
Comparando fallo por fallo:

- **Fallan los dos**: `duracion` y `parentesis` — ninguno de los dos resuelve
  bien el parseo de duración combinada ni el balanceo de paréntesis con pila.
- **Solo falla nanbeige** (Qwen3-4B lo resuelve): `romano`, `bytes`, `lotes`.
- **Solo falla Qwen3-4B** (nanbeige lo resuelve): `desde_romano`, `camel`,
  `comprimir`.

Juntos, eligiendo siempre la respuesta del que acierta, cubrirían **23/25**
(solo `duracion` y `parentesis` quedan sin resolver por ninguno). Es una
mejora real sobre cualquiera de los dos solos, pero no el "arregla 4 de 5"
que sugería la ejecución anterior — esa ejecución no es comparable, corresponde
a otra sesión/config no verificada aquí.

## VRAM con los dos cargados a la vez

Medido con `nvidia-smi` mientras ambos backends estaban activos: **6831 MiB
usados de 8192 MiB** (nanbeige 3048 MiB + Qwen3-4B 2870 MiB + ~900 MiB de
desktop/otros procesos) — **quedó ~1 GB libre**. Caben los dos, pero
ajustados; no hay margen para un tercero sin recortar `--ctx-size` en alguno.

## Fuente

Detalle completo en `resultado_experto_qwen3-4b_linux_q8cache.json` (ejecución
válida) y `resultado_experto_qwen3-4b_linux.json` (ejecución con `turbo3`,
conservada como evidencia del bug, **no usar sus números**).
