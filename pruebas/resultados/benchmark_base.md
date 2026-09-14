# Benchmark base (20/07/2026)

Línea base de rendimiento de ambos backends, medida antes de cualquier optimización.
Metodología: `llama-bench` (build 15d22acc8) para CPU sintético + requests reales a `/v1/chat/completions` leyendo el campo `timings` de llama-server.

## Hardware

| Componente | Detalle |
|---|---|
| CPU | AMD Ryzen 5 3600XT — 6 núcleos / 12 hilos, 3.8 GHz |
| RAM | 4×8 GB DDR4-3000 (XMP activo, dual channel ≈ 48 GB/s) |
| GPU | RTX 3060 Ti 8 GB (583 MiB usados en reposo → ~7.4 GB útiles) |
| RAM libre en reposo | ~21.5 GB |

## Backend GPU — Qwythos-9B-v2 Q4_K_M (fork buun, puerto 8080)

Config: ctx 16384, `--parallel 2`, flash-attn, KV `tbq3`/`tbq3`.

| Test (API real) | Prompt toks | Prefill tok/s | Gen tok/s |
|---|---:|---:|---:|
| corto | 52 | 113 | 48.3 |
| medio | 540 | 1177 | 48.3 |
| largo | 1974 | 1199 | 47.6 |

- **VRAM con modelo cargado: 6483 MiB usados / 1542 MiB libres.**
- Generación estable ~48 tok/s independiente del largo del prompt. Prefill ~1200 tok/s.
- RAM host del proceso: ~4.6 GB.

## Backend CPU — GLM-4.7-Flash-REAP-23B-A3B Q4_K_XL (puerto 8083)

Config: `--cpu-moe`, 6 threads, ctx 8192, KV q8_0/q4_0.

**llama-bench sintético** (backends apagados, 3 repeticiones):

| Test | tok/s |
|---|---:|
| pp512 (prefill) | 34.19 ± 0.50 |
| tg128 (generación) | 12.35 ± 0.14 |

**API real** (con thinking del GLM incluido):

| Test | Prompt toks | Prefill tok/s | Gen tok/s | Total |
|---|---:|---:|---:|---:|
| corto | 18 | 10.7 | 10.8 | 49 s |
| medio | 546 | 32.3 | 9.8 | 69 s |
| largo | 1587 | **16.1** | **6.7** | **163 s** |

- **RAM del proceso: 19.6 GB** (más de lo esperado para un modelo de 14.2 GB; vigilar con otras apps abiertas — quedan ~7 GB de margen antes de swap).
- **Degradación con contexto**: la generación cae de 10.8 a 6.7 tok/s y el prefill se desploma de 32 a 16 tok/s con ~1600 tokens de prompt. Un prompt de 2000 tokens tarda ~100 s solo en prefill.

## Concurrencia (ambos backends atendiendo a la vez)

| Backend | Gen solo | Gen concurrente | Penalización |
|---|---:|---:|---:|
| GPU (Qwythos) | 48.3 | 45.1–45.7 | **−6%** |
| CPU (GLM) | 10.8 / 9.8 / 6.7 | 11.3 / 9.8 / 6.7 | **~0%** |

Los backends casi no compiten entre sí: la inferencia GPU usa poco CPU y el MoE en CPU no toca la GPU. El diseño de dos backends separados funciona bien en esta máquina.

## Interpretación

1. **Generación CPU = límite de hardware.** 12.35 t/s sintético está clavado en el techo teórico del ancho de banda DDR4-3000 dual channel para un MoE A3B (~2 GB de pesos activos por token sobre ~48 GB/s). No hay optimización de software que supere ese techo.
2. **El dolor real del backend CPU es el prefill** (34 t/s en el mejor caso, 16 t/s con contexto). Aquí sí hay margen de software: el prefill es compute-bound y se acelera enormemente descargándolo en la GPU (build CUDA + `--n-gpu-layers` con `--cpu-moe`), incluso dejando toda la generación de expertos en CPU.
3. **Margen de VRAM: solo 1.5 GB libres** con Qwythos cargado. Para un offload híbrido del GLM habría que liberar VRAM primero (bajar ctx de 16384 a 8192 o `--parallel 2` → 1 en Qwythos).
4. **La degradación con contexto del backend CPU** (6.7 t/s a 1600 tokens) merece investigación aparte: puede ser el V-cache q4_0 (dequant costosa en atención CPU) o presión de memoria. Probar KV q8_0/q8_0.
5. GPU saludable: ~48 t/s de generación y prefill de 1200 t/s para un 9B Q4 en una 3060 Ti es un resultado muy bueno; la KV tbq3 está cumpliendo (ctx 16K ×2 slots en 8 GB).

## Comparación con mediciones previas (suite de pruebas del 19/07)

| Fuente | GPU gen | CPU gen |
|---|---:|---:|
| suite de pruebas (19/07) | 35–45 t/s | ~11 t/s máx |
| Este benchmark | 45–48 t/s | 6.7–10.8 t/s |

Consistentes; este benchmark añade prefill, VRAM/RAM reales y el escenario concurrente.

---

# Experimentos de optimización (misma fecha)

## Experimento A — V-cache q4_0 vs q8_0 en CPU: SIN EFECTO

llama-bench, tg128 a profundidad 0 y 1536:

| KV (k/v) | tg128 @ d0 | tg128 @ d1536 |
|---|---:|---:|
| q8_0 / q4_0 (actual) | 12.10 | 7.92 |
| q8_0 / q8_0 | 12.56 | 7.93 |

**Conclusión:** la degradación con contexto (~35%) es del cómputo de atención en CPU, no de la cuantización del V-cache. Mantener `q4_0` (misma velocidad, menos RAM).

## Experimento B — GLM con offload híbrido (build CUDA del fork buun)

`--n-gpu-layers 99` + expertos en CPU, ctx 8192, KV q8_0/q8_0, `--no-mmap`:

| Config GLM | Prefill @2000 tok | Gen (corto/medio/largo) | VRAM |
|---|---:|---|---:|
| CPU puro (baseline) | 16 t/s (~100 s) | 10.8 / 9.8 / **6.7** | 0 GB |
| Híbrido total (`--cpu-moe`) | 343 t/s (~5 s) | 7.3 / 7.6 / 7.8 | 2.2 GB |
| Híbrido parcial (`--n-cpu-moe 29`) | **728 t/s (~2 s)** | **11.3 / 11.3 / 11.1** | 7.5 GB |

- El híbrido elimina la degradación con contexto (generación plana).
- `ncmoe=29` es el GLM más rápido posible en esta máquina: prefill 45×, generación +66% en contexto largo. Pero consume casi toda la VRAM → **incompatible con Qwythos residente**.
- El log recomienda `--no-mmap` cuando hay tensores en CPU; aplicado.

## Experimento C — Qwythos + GLM híbrido ligero a la vez: DESCARTADO

Qwythos con `--fit on` se auto-recorta (capas a CPU) para caber en los 5.2 GB libres:

| Backend | Gen solo | Gen conviviendo |
|---|---:|---:|
| Qwythos-9B | 48 | **14–15 (−70%)** ✗ |
| GLM híbrido ligero | 7.5 | 5.2–7.4 |

No vale la pena: mata al backend rápido.

## Experimento D — Qwen3-4B (GPU) + GLM híbrido ligero: GANADOR para convivencia

Qwen3-4B Q4_K_M (2.5 GB) reemplaza a Qwythos como modelo rápido; GLM en híbrido total. Medidos **concurrentes**:

| Backend | Prefill @2000 tok | Gen | VRAM total |
|---|---:|---:|---|
| Qwen3-4B (ctx 16384) | 3007 t/s | **58–62 t/s** | 6.5 GB usados |
| GLM híbrido (ctx 8192) | 568 t/s | 7.5–7.7 t/s | **1.5 GB libres** |

Ambos modelos acelerados a la vez, con margen de VRAM real.

## Matriz de decisión final

| Config | Modelo rápido (gen) | GLM prefill @2K | GLM gen @ctx largo | VRAM libre |
|---|---:|---:|---:|---:|
| **Actual** (Qwythos GPU + GLM CPU) | 48 | 100 s | 6.7 | 1.5 GB |
| **GLM máximo solo** (`ncmoe=29`) | — | 2 s | 11.1 | 0.5 GB |
| Qwythos fit + GLM híbrido | 14 ✗ | 3 s | 7.4 | 0.1 GB |
| **Qwen3-4B + GLM híbrido** | 58–62 | 3.5 s | 7.5 | 1.5 GB |

**Trade-off central:** en 8 GB no caben Qwythos-9B *y* el GLM acelerado. Opciones reales:
1. **Calidad del modelo rápido** → dejar la config actual y aceptar el prefill lento del GLM.
2. **Ambos ágiles** → cambiar el modelo rápido a Qwen3-4B (menos capaz que Qwythos-9B) y GLM híbrido ligero.
3. **GLM protagonista** → `ncmoe=29` solo, con Qwythos/Qwen3 iniciado bajo demanda (intercambio desde el intermediario).

## Experimento E — Roles invertidos: GLM máximo en GPU + Qwen3-4B en CPU

Idea del usuario: tareas pesadas → GPU (GLM `ncmoe=29`), tareas ligeras → CPU (Qwen3-4B).

**Qwen3-4B en CPU solo (llama-bench):** pp512 = 63.8 t/s, tg128 = 13.45 t/s.

**Ambos servidores residentes** (GLM puerto 8085 GPU, Qwen3-4B puerto 8088 CPU, 7.2 GB VRAM usados / 0.8 GB libres):

| Backend | Escenario | Prefill @~2000 tok | Gen |
|---|---|---:|---:|
| GLM ncmoe29 (GPU) | secuencial | 732 t/s | 10.8–11.1 |
| GLM ncmoe29 (GPU) | generando a la vez que Qwen | 705 t/s | 7.6–10.2 |
| Qwen3-4B (CPU) | secuencial | 50 t/s | 8.8–13.1 |
| Qwen3-4B (CPU) | generando a la vez que GLM | 38 t/s | 7.0–10.2 |

- La degradación concurrente (~25-30%) viene de que ambos usan los 6 núcleos: los expertos del GLM residen en CPU aunque la atención esté en GPU. En uso real (requests que no se solapan exactamente) los números secuenciales son los representativos.
- El GLM queda igual de rápido que solo (10.8 vs 11.3) — la convivencia casi no le cuesta.

## Matriz final actualizada

| Config | Tarea ligera (gen) | GLM prefill @2K | GLM gen | VRAM libre |
|---|---:|---:|---:|---:|
| Actual (Qwythos GPU + GLM CPU) | **48** | 100 s | 6.7–10.8 | 1.5 GB |
| D: Qwen3-4B GPU + GLM híbrido ligero | **58–62** | 3.5 s | 7.5 | 1.5 GB |
| E: GLM ncmoe29 GPU + Qwen3-4B CPU | 9–13 | **2.2 s** | **10.8–11.1** | 0.8 GB |

- **D** maximiza las tareas ligeras (62 t/s) con GLM decente (7.5).
- **E** maximiza el GLM (11 t/s, el mejor de todos) con tareas ligeras aceptables (9-13 t/s).
- Ambas eliminan el problema del prefill (100 s → 2-4 s).
