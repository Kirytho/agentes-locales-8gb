# buun-llama-cpp: DFlash / speculative decoding + KV cache VBR

> ## MEDIDO EL 28/08/2026 — leer esto antes que el resto del documento
>
> **`-ct vbr` PROBADO Y NO ADOPTADO.** Ornith-1.5-9B-MTP, ctx 81.920, mismo
> modelo y mismo contexto en los dos brazos, 12 ejecuciones de
> `pruebas/eval_stack_completo.py` cada uno:
>
> | | q8_0/q4_0 | vbr |
> |---|---|---|
> | VRAM | 7.363 MiB | **6.053 MiB** |
> | mediana por tarea | **9,6 s** | 19,1 s |
> | rango | 3-15 s | 14-24 s |
> | aciertos | 8/12 | 11/12 |
> | degradación de nivel | — | nunca |
>
> **Lo firme**: VBR es ~2x más lento POR TAREA y las distribuciones **no se
> solapan** (peor caso de la base 14,6 s contra mejor caso de VBR 13,6 s). Y
> libera 1.310 MiB sin corromper: en 12 conversaciones multiturno con 21
> herramientas nunca bajó de nivel.
>
> **Lo que NO es firme**: 11/12 contra 8/12 da Fisher p = 0,317. No se puede
> decir que VBR acierte más. (La base obtuvo 11/12 a ctx 65.536 y 8/12 a 81.920:
> también ruido. Con n=12 estas diferencias no significan nada.)
>
> **TRAMPA DE MEDICIÓN, la misma que apareció dos veces ese día**: una prueba
> única de 200 tokens daba a VBR **+38% en tok/s** (64,9 contra 46,9). El banco
> agéntico da 2x MÁS LENTO. Las dos son correctas y miden cosas distintas: con
> el contexto VACÍO VBR va más rápido, pero en una sesión agéntica el contexto
> SE LLENA y el controlador de degradación trabaja en cada decodificación.
> **Un tok/s de una prueba única no predice el rendimiento agéntico.**
>
> **CUÁNDO SÍ CONVENDRÍA**: los 1.310 MiB son reserva de KV, que es el techo del
> paralelismo (~7 subagentes, medido el 28/08). Si algún día se quieren
> más subagentes en paralelo, 2x de latencia por vuelta a cambio de superar ese
> techo puede valer la pena. Como configuración por defecto, no.
>
> **SIN PROBAR**: el log avisa `no measured VBR degrade order for this
> arch/n_layer -- using the generic cross-model order` y sugiere
> `VBR_DEGRADE_ORDER=<file>`. Parte del costo podría venir de ahí. Tampoco se
> probó `--vbr-floor` con un piso menos agresivo (resolvió solo a 1,25
> bits/valor, nivel turbo1_tcq).
>
> **DFLASH 2 NO SE PUEDE USAR HOY**: el build actual (799e399, 16/08/2026) incluye
> `dflash`, `draft-dflash` y `draft-dspark`, pero ninguna cadena `dflash2`. DFlash 2
> solo es alcanzable desde un PR sin fusionar en llama.cpp/vLLM/SGLang, necesita
> un modelo con arquitectura `DFlashDraftModel` (los que existen son de 27B, no
> caben en 8 GB) y además un modelo borrador, que no hay en disco.


> **Nota del 18/08/2026.** Documento del 26/07. Lo que dice del binario sigue
> vigente, pero las conclusiones sobre decodificación especulativa quedaron
> **superadas por mediciones**: MTP no inicia con `-ngl 99` (falta VRAM, y bajar
> el contexto solo libera 199 MiB), y las variantes sin modelo borrador dan
> **2,9× copiando texto de la solicitud pero pierden 15-33% en todo lo demás**.
> Ver `pruebas/resultado_spec.md`. Los modelos que menciona (Bonsai-27B,
> Ternary-Bonsai) ya no están en disco.


> Nota para el futuro (24/07/2026). El backend GPU ya usa buun-llama-cpp, pero con
> DFlash desactivado y un KV cache fijo. Aquí queda la receta para aprovecharlo más.

## 1. Ya se está usando

El backend GPU del proyecto **es un build de buun-llama-cpp** (el fork de
spiritbuun, "TurboQuant"). Evidencia: el binario contiene las cadenas `TurboQuant`,
`DFlash`, `tbq3`, `tbq4`, `dflash`, y el lanzador inicia con
`--cache-type-k tbq3 --cache-type-v tbq3` — un tipo de caché que **no existe en el
llama.cpp oficial**. Los modelos Bonsai-27B / Ternary-Bonsai salen del mismo
ecosistema.

Así que la pregunta "¿conviene pasarse a buun-llama?" ya está respondida. Lo que falta
es **activar lo que está desactivado** y, quizás, **actualizar el build**.

## 2. La idea de fondo (por qué esto importa y por qué no es magia)

Las mediciones del proyecto mostraron que la generación está limitada por el **ancho
de banda de memoria**. El motor no es el cuello de botella. La **decodificación
especulativa** es la única técnica que puede superar ese techo en un solo stream: un
modelo pequeño "borrador" adivina varios tokens y el grande los verifica en una sola
pasada, en vez de uno por uno.

**El costo:** el borrador (o las cabezas MTP) ocupan VRAM, y la VRAM es el recurso
escaso. Por eso no es gratis: solo conviene si la ganancia en tok/s supera lo que se
pierde por tener menos VRAM/contexto. **La variante `ngram` no usa modelo borrador ni
VRAM extra — es la primera a probar en 8 GB.**

## 3. Speculative decoding — bandera `--spec-type`

Acepta (lista separada por comas):
`none | draft-simple | draft-eagle3 | draft-dflash | draft-mtp | ngram-cache | ngram-simple | ngram-map-k | ngram-map-k4v | ngram-mod`

| Tipo | Aceptación | Necesita | Nota |
|---|---|---|---|
| `ngram-cache` / `ngram-*` | variable | **nada** (usa n-gramas del contexto) | **Empezar por aquí**: cero VRAM extra |
| `draft-simple` | media | un borrador pequeño (`-md`) | Clásico; sirve `Qwen3-0.6B` |
| `draft-dflash` | 13–20 % | modelos existentes | Post-hoc, ganancia modesta |
| `draft-mtp` | **45–85 %** | modelo con cabezas MTP co-entrenadas | El gran salto; requiere modelo MTP |

Ajustes finos: `--spec-draft-n-max` (def. 3, tokens a adivinar), `--spec-draft-n-min`
(def. 0), `--spec-draft-p-split` (def. 0.10).

### Recetas para el lanzador del backend GPU

Partiendo de la línea actual, añadir **una** de estas al final del comando `llama-server`:

**a) ngram (probar esto primero — sin costo de VRAM):**
```
--spec-type ngram-cache --spec-draft-n-max 4
```

**b) borrador clásico con Qwen3-0.6B:**
```
-md ../../modelos/Qwen3-0.6B-Q4_K_M.gguf --spec-type draft-simple --spec-draft-n-max 4
```

**c) MTP nativo (el gran salto) — requiere descargar un modelo con cabezas MTP:**
```
llama-server -m ../../modelos/Qwen3.6-27B-DFlash-Q6_K.gguf --spec-type draft-mtp -ngl 99 --flash-attn on
```
(modelo: `spiritbuun/Qwen3.6-27B-DFlash-GGUF` en Hugging Face)

Ejemplos literales del README:
`llama-server -m model.gguf -md draft.gguf` ·
`llama-server -m Qwen3.6-27B-Q6_K.gguf --spec-type draft-mtp --mmproj-gpu-swap -ngl 99`

## 4. KV cache VBR (más contexto en la misma VRAM)

Hoy se usa `--cache-type-k tbq3 --cache-type-v tbq3` (fijo). `tbq3` es el **nombre
antiguo de `turbo3_tcq`**. El build actualizado añade el **modo dinámico VBR**:

- `-ct vbr` — inicia en FP16 y degrada por capa a medida que crece el contexto
  (`turbo8 → turbo4 → turbo3_tcq → turbo2_tcq → turbo1_tcq`). Para un modelo de 16 capas da
  ~160 pasos de calidad.
- `--vbr-vram <MiB>` — presupuesto explícito de VRAM para el KV.
- `--vbr-floor <bits>` — piso de calidad.
- `--vbr-budget <tier>` — nivel fijo o modo dinámico.

Tipos fijos disponibles: `f16, q8_0, q4_0, turbo8, turbo4, turbo3_tcq, turbo2_tcq,
turbo1_tcq`. TCQ (trellis-coded quant) da ~40 % menos divergencia KL a 3 bits usando menos
bits (3.25 vs 3.50 bpv).

**Requiere flash-attention** (`--flash-attn on`), que ya está en uso (`--flash-attn auto`).

## 5. Actualizar / compilar el build (para VBR y los TCQ nuevos)

El binario actual ya incluye DFlash pero con la nomenclatura antigua (`tbqN`). Para
`-ct vbr` y los `turbo*_tcq` conviene un build reciente: un release precompilado de
spiritbuun, o compilarlo:

```bash
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="86"
cmake --build build --config Release
```
`86` = compute capability de la RTX 3060 Ti (8.6). En Windows: Visual Studio 2022
(Desktop C++ + CMake Tools + Clang) + CUDA Toolkit.

## 6. El experimento para medir si conviene (con `medir_gpu.py`)

No se decide opinando. A/B con el **mismo modelo**:
1. Base: la configuración actual → tok/s con `medir_gpu.py`.
2. Con speculative: añadir una receta de §3 → tok/s.
3. Registrar también la **VRAM libre** en cada caso (el borrador/MTP la consume).

**Criterio fijado antes de medir:** el speculative solo gana si el aumento de tok/s
compensa el contexto/VRAM que sacrifica. En 8 GB, `ngram` (sin costo de VRAM) parte con
ventaja; `draft-mtp` puede ganar mucho más, pero solo con un modelo MTP y su VRAM.

### Antes de ejecutarlo, confirmar qué acepta el binario

El build es antiguo (nomenclatura `tbqN`). Ejecutar una vez:
```
llama-server --help
```
y buscar `--spec-type`, `-md`, `-ct vbr`, `--vbr-`. Lo que aparezca ya se puede probar;
lo que no, exige actualizar el build (§5).

## Fuentes

- Repo: https://github.com/spiritbuun/buun-llama-cpp
- DFlash anunciado: https://x.com/spiritbuun/status/2047399436368654557
- Modelo MTP: https://huggingface.co/spiritbuun/Qwen3.6-27B-DFlash-GGUF
- DFlash en llama.cpp oficial (PR): https://github.com/ggml-org/llama.cpp/pull/22105
- Otro fork con cuantizaciones SOTA: https://github.com/ikawrakow/ik_llama.cpp
