# Bonsai-27B-Q1_0 como candidato de GPU (T1) — medido 22/07/2026

Primer paso del plan de expertos: **probar lo que ya está en disco antes de descargar
nada**. Metodología de `benchmark_base.md` (API real leyendo el campo `timings`),
mismos parámetros del lanzador del backend principal.

---

## Medición

| Métrica | **Bonsai-27B-Q1_0** | Qwythos-9B (referencia) |
|---|---:|---:|
| Parámetros | **27B** | 9B |
| Tamaño del archivo | **3,54 GB** | 5,34 GB |
| VRAM usada | **5545 MiB** | 6483 MiB |
| **VRAM libre** | **2480 MiB** | 1542 MiB |
| Tiempo de carga | 9 s | — |
| Generación | **30,2 – 31,1 t/s** (plana) | 48 t/s |
| Prefill @783 tok | 465 t/s | ~1200 t/s |

Config: `--ctx-size 16384 --parallel 2 --flash-attn auto --cache-type-k/v tbq3 --threads 6`.

---

## Hallazgo 1 — El tamaño del archivo NO predice la velocidad en GPU

Bonsai tiene un archivo **más pequeño** que Qwythos (3,54 vs 5,34 GB) y sin embargo es
**más lento** (30 vs 48 t/s).

Esto **corrige el modelo físico** que se había derivado: con cuantización ternaria
extrema, el cuello deja de ser el ancho de banda de memoria y pasa a ser el **cómputo de
descuantización**. Hay que descomprimir 27B de parámetros aunque ocupen 3,54 GB en disco.

> **Regla corregida:** en GPU con quants normales domina el ancho de banda; con quants
> extremos (ternario, Q1/Q2) domina el **número de parámetros**, no los bytes.

Es exactamente el tipo de suposición que solo se detecta midiendo.

---

## Hallazgo 2 — Razona por defecto y quema el presupuesto de tokens

Con `max_tokens=300` y una pregunta que pedía **una sola frase**:

| Campo | Resultado |
|---|---|
| `reasoning_content` | **1322 caracteres** de razonamiento |
| `content` | **21 caracteres** — cortado a mitad de frase |
| `finish_reason` | `length` |

Es decir: consumió los 300 tokens pensando y **nunca terminó la respuesta**.

**El intermediario ya maneja esto**: al construir la solicitud envía
`chat_template_kwargs: {"enable_thinking": False}` a los backends de GPU. Pero hay que
documentarlo, porque **quien consulte el backend directamente obtiene respuestas
vacías**. Repetida la prueba con el flag —tal como lo hace el intermediario— el modelo responde
normalmente.

---

## Hallazgo 3 — Q1_0 no destruyó la calidad

Cuantizar un 27B a ~1 bit hacía temer un modelo degradado. No es el caso:

**Código (verificado objetivamente).** Pidió `es_primo(n)` y produjo:

```python
def es_primo(n):
    if n < 2: return False
    if n == 2: return True
    if n % 2 == 0: return False
    for i in range(3, int(n**0.5) + 1, 2):
        if n % i == 0: return False
    return True
```

Ejecutado contra el rango −5…100, casos borde (0, 1, −7) y primos grandes
(7919, 104729): **todos correctos**. Buena implementación, además — descarta pares y
solo prueba divisores impares hasta la raíz.

**Detección de premisa falsa.** Ante *"¿por qué Python compila a código máquina nativo
antes de ejecutarse?"* respondió: *"La premisa de tu pregunta es **incorrecta**. Python
**no** compila a código máquina nativo"*. Detectar una premisa falsa exige comprensión
real, no completado de patrones — es una señal fuerte de que el modelo sigue sano.

**Contra:** es verboso. No respetó la instrucción "en una frase" en ninguna respuesta.

---

## Veredicto como candidato T1

**Viable.** El intercambio es claro:

| A favor | En contra |
|---|---|
| 3× parámetros (27B vs 9B) | 37 % más lento (30 vs 48 t/s) |
| **1 GB más de VRAM libre** (2,48 vs 1,54 GB) | Prefill 2,5× más lento |
| Calidad intacta pese al Q1_0 | Verboso, ignora instrucciones de formato |
| Generación plana con contexto | Razona por defecto (mitigable con el flag) |

El GB extra de VRAM libre es relevante: es el margen que permitiría **un segundo modelo
pequeño residente en GPU**, o mucho más contexto.

**Pendiente para decidir:** una comparación de calidad cabeza a cabeza contra
Qwythos-9B en la misma batería. Estos tres casos sugieren que Bonsai es más capaz, pero
tres casos no son una medición.
