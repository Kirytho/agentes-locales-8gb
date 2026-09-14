# Candidatos de modelo para la GPU de 8 GB — Fase 2 (22/07/2026)

Investigación de modelos que quepan **enteros** en la RTX 3060 Ti, motivada por la
hipótesis de que el razonamiento debería ejecutarse en GPU.

Complementa a `benchmark_base.md`, que aporta la línea base y la metodología.

---

## 1. El replanteamiento: la corrección del enrutado cambió el cálculo

La idea original era *invertir los roles*: razonamiento a GPU, código a CPU. Pero:

- El **Experimento E** ya midió esa inversión: el GLM en GPU (`ncmoe=29`) **casi no
  acelera la generación** (10,8 → 11,1 tok/s), porque los expertos MoE siguen en RAM.
  Solo se dispara el prefill (100 s → 2,2 s).
- Tras el **reequilibrio del enrutado del 22/07**, la GPU atiende **3 de 4 perfiles**
  (coding, quality, quick) y la CPU solo `reasoning`. Desplazar al modelo de GPU para
  colocar el de razonamiento perjudicaría a tres perfiles para beneficiar a uno.

**Conclusión:** la inversión ya no es el camino. La pregunta correcta pasó a ser
*¿puede **un solo modelo** cubrir ambos roles y caber entero en la VRAM?*

---

## 2. Presupuesto de VRAM (medido, no estimado)

| Concepto | Valor |
|---|---|
| VRAM total | 8 GB |
| Ocupada en reposo | 583 MiB |
| **Útil** | **~7,4 GB** |
| Qwythos-9B Q4_K_M actual (ctx 16384, `--parallel 2`) | 6483 MiB → **1,5 GB libres** |

**Objetivo para un reemplazo:** pesos **≤ 5,5 GB**, dejando ~1,5-2 GB para KV cache y
overhead. Cualquier candidato por encima de eso obliga a recortar contexto o slots.

---

## 3. Candidatos verificados en HuggingFace

Tamaños **reales** de los archivos, consultados vía la API de HF (no estimaciones de
blogs). Todos en formato GGUF, compatibles con `llama-server`.

| Modelo | Quant | Tamaño | Licencia | Modo *thinking* | ¿Cabe? |
|---|---|---:|---|---|---|
| **Qwen3.5-9B** | Q4_K_M | **5,29 GB** | Apache 2.0 | sí, `enable_thinking` | ✅ |
| Qwen3.5-9B | Q4_K_S | 5,02 GB | Apache 2.0 | sí | ✅ |
| Qwen3.5-9B | UD-Q4_K_XL | 5,55 GB | Apache 2.0 | sí | ✅ ajustado |
| Qwen3.5-9B | Q5_K_M | 6,12 GB | Apache 2.0 | sí | ⚠️ sin margen |
| **Qwen3-8B** | Q4_K_M | 5,03 GB | Apache 2.0 | sí, `/think` `/no_think` | ✅ |
| **Qwen3.5-4B** | Q4_K_M | 2,74 GB | Apache 2.0 | sí | ✅ holgado |
| Qwen3.5-4B | Q6_K | 3,53 GB | Apache 2.0 | sí | ✅ holgado |
| DeepSeek-R1-Distill-Qwen-7B | Q4_K_M | 4,68 GB | *(sin verificar)* | **siempre razona** | ✅ pero ⚠️ |
| Phi-4-reasoning (14B) | Q4_K_M | ~9 GB | — | sí | ❌ no cabe |

**Notas:**

- **DeepSeek-R1-Distill** razona siempre, sin interruptor. Sirve como modelo dedicado
  de razonamiento, pero es **mala opción para un modelo unificado**: pagaría el costo
  del `<think>` incluso en un saludo — justo el problema que acabamos de eliminar.
- Los quants **UD-** son de unsloth (cuantización dinámica). El proyecto ya usa uno
  (el GLM es `UD-Q4_K_XL`), así que es terreno conocido.
- **Qwen3.5-4B** deja ~4 GB libres: es el único que permitiría **dos modelos
  residentes** en la GPU, o un contexto muy amplio.

---

## 4. Por qué Qwen3.5-9B es el candidato principal

**a) Encaja con el código que ya existe.** Qwen3.5 razona por defecto y se desactiva
con `"enable_thinking": False` dentro de `chat_template_kwargs` — exactamente lo que
el intermediario ya envía. También emite etiquetas `<think>`, que el intermediario ya
limpia, y ya existe un reintento para el caso en que el modelo solo razone. **La
maquinaria está construida.**

**b) Es más pequeño que el modelo actual.** 5,29 GB contra los ~5,7 GB de Qwythos-9B:
cabe con **más** margen de KV cache, no menos.

**c) Rompe el techo de los 12 tok/s.** Es la única vía real: al estar entero en VRAM,
la generación deja de depender del ancho de banda DDR4.

**d) La comparación de calidad no está perdida de antemano.** El GLM-4.7-Flash-REAP es
un **MoE de 23B con solo ~3B activos por token**; Qwen3.5-9B es **denso**, activa sus
9B. No es descabellado que un denso de 9B iguale o supere a un MoE A3B en
razonamiento, siendo 4-5× más rápido. **Esto hay que medirlo, no asumirlo.**

**e) Contexto de 262K nativos**, contra los 8192 con los que se ejecuta el GLM hoy.

### Ganancia esperada (a verificar)

| Métrica | Hoy (GLM en CPU) | Esperado (Qwen3.5-9B en GPU) |
|---|---:|---:|
| Generación en razonamiento | 6,7–11 tok/s | **~45–50 tok/s** |
| Prefill @2000 tokens | ~100 s | **~2 s** |
| RAM del sistema ocupada | 19,6 GB | **~0** |
| Backends a mantener | 2 | 1 |

### Riesgos

1. **Calidad de razonamiento** frente al GLM-23B — es la incógnita central.
2. **Se pierde Qwythos-9B** y su configuración con KV ternaria ya ajustada (trabajo invertido).
3. **Un solo backend elimina el fallback**: la maquinaria de derivación del
   intermediario asume dos. Habría que decidir si se conserva el GLM como backend
   de razonamiento profundo bajo demanda.

---

## 5. Cambio necesario para el modelo unificado

Hoy el modo *thinking* se decide **por backend**: activado en los backends de
razonamiento y desactivado en los de GPU.

Con un modelo unificado debe decidirse **por perfil**: `reasoning` → activado; el
resto → desactivado. Es un cambio acotado, y encaja con el diseño (el perfil ya se
conoce al construir la solicitud).

---

## 6. Protocolo de evaluación

Reutilizar la metodología de `benchmark_base.md` para que los números sean comparables
con la línea base:

1. **`llama-bench` sintético** (pp512 / tg128), backends apagados, 3 repeticiones.
2. **API real** leyendo el campo `timings` de llama-server, en los tres tamaños de
   prompt (corto / medio / largo). El largo es el que revela la degradación con
   contexto.
3. **VRAM real** con `nvidia-smi` y RAM del proceso.
4. **Escenario concurrente**, no solo secuencial.
5. Extender la **matriz de decisión final** del benchmark con las filas nuevas.

**Además, batería de calidad** (no basta con tok/s, porque el criterio acordado fue
reemplazar solo «si hay algo mejor»): un conjunto fijo de prompts —de código y de
razonamiento— resuelto por Qwythos-9B, GLM-23B y el candidato, comparando las salidas.
Sin esta parte, la decisión se toma a ciegas.

---

## 7. Orden sugerido

1. Descargar **Qwen3.5-9B Q4_K_M** (5,29 GB) e iniciarlo en un puerto aparte, sin
   tocar la configuración actual.
2. Ejecutar el protocolo de velocidad y compararlo con la línea base.
3. Ejecutar la batería de calidad contra los dos modelos actuales.
4. Solo entonces decidir: unificar en un modelo, o mantener dos.

---

## Fuentes

- <https://huggingface.co/api/models/unsloth/Qwen3.5-9B-GGUF/tree/main> — tamaños reales
- <https://huggingface.co/unsloth/Qwen3.5-9B-GGUF> — ficha del modelo
- <https://huggingface.co/api/models/unsloth/Qwen3.5-4B-GGUF/tree/main>
- <https://huggingface.co/Qwen/Qwen3-8B-GGUF>
- <https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF>
