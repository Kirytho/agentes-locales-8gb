# El mejor 2B para agentes residentes (19-20/08/2026)

**Banco**: `pruebas/instrumentos/probar_modelo.py` · batería de 53 tareas de código (ejecutadas)
+ 25 de razonamiento (5 trampas) · **5 ejecuciones por candidato**.

| modelo | n | código | rango | razonamiento | rango | tok/s | VRAM |
|---|---:|---:|---:|---:|---:|---:|---:|
| **google/gemma-4-E2B-it** (Q4_K_M) | 5 | **48,8/53** | 48-49 | **13,6/25** | 13-15 | 135,7 | 1.710 Mi |
| unsloth/Qwen3.5-2B-MTP (Q5_K_M) | 5 | 35,2/53 | 33-37 | 6,0/25 | 5-8 | 180,7 | 1.627 Mi |
| unsloth/Qwen3.5-2B (Q5_K_M) | 5 | 34,4/53 | 32-36 | 5,4/25 | 4-7 | 177,2 | 1.633 Mi |
| empero-ai/Qwen3.8-2B-Distill (Q5_K_M) | 8 | 28,0/53 | 26-32 | 6,3/25 | 5-8 | 175,5 | 1.673 Mi |
| Jackrong/Qwen3.5-2B-**Reasoning-Distilled** | 1 | 19,0/53 | — | **2,0/25** | — | 168,9 | 1.619 Mi |

## Gana gemma-4-E2B, y no es discutible

**+13,6 puntos de código y +7,6 de razonamiento** sobre el mejor Qwen, con rangos
que **no se tocan** (48-49 contra 33-37). Con 5 ejecuciones y una desviación de ~2,
la diferencia es real.

Y cabe igual: **1.710 MiB**, prácticamente lo mismo que los Qwen de 1,34 GB,
aunque su archivo pese 2,89 GB. La arquitectura E2B mantiene parte de los pesos
(*per-layer embeddings*) fuera de la VRAM por diseño. **Caben 4 en la GPU.**

**Lo que se paga: velocidad.** 135,7 contra 180,7 tok/s, un **25% menos**. Con
cuatro agentes esa diferencia se multiplica.

## Dos resultados secundarios

**MTP de fábrica no cambia la calidad**: 35,2 contra 34,4 de código, rangos
solapados. Da **+2,0% de velocidad**. Coherente con lo ya sabido: la
decodificación especulativa es neutra por construcción — verifica cada token, así
que solo puede cambiar cuándo llega la respuesta, no cuál es.

**El "Reasoning-Distilled" es el peor de todos, y obtiene 2/25 en razonamiento** —
exactamente lo que promete su nombre. Descartado tras una ejecución. El nombre de
un repo no es un dato.

---

## Segunda serie: ¿es la arquitectura o la generación? (20/08)

| candidato | código | razonamiento | tok/s | VRAM | caben |
|---|---:|---:|---:|---:|---:|
| gemma-4-E2B (Q4_K_M) · 5 ejecuciones | 48,8/53 | 13,6/25 | 135,7 | 1.710 Mi | 4 |
| **gemma-3n-E2B (Q4_K_M)** · 1 ejecución | **48/53** | 11/25 | 113,7 | 1.763 Mi | 4 |
| Qwen2.5-Coder-3B (Q4_K_M) | 45/53 | 4/25 | 135,9 | 2.195 Mi | 3 |
| LFM2.5-2.6B (Q4_K_M) | 25/53 | **0/25** | 169,3 | 1.873 Mi | 3 |
| MiniCPM5-1B Thinking (Q8_0) | 9/53 | 0/25 | 254,3 | 1.173 Mi | 6 |

**Gana la arquitectura, no la generación.** `gemma-3n-E2B` —la generación
anterior— obtiene 48/53, empatado con gemma-4 (48,8) dentro del ruido. Lo que hace
la diferencia es el diseño **E2B**: los *per-layer embeddings* quedan fuera de la
VRAM, así que un archivo de 2,8 GB ocupa 1,7 GB y rinde muy por encima de lo que
su huella sugiere.

Consecuencia: para seguir buscando conviene recorrer **esa familia** (E2B, E4B,
variantes QAT) antes que más 2B sueltos de otras familias.

gemma-4 sigue siendo la elección: mismo código, **+2,6 de razonamiento** y
**+19% de velocidad** (135,7 contra 113,7).

**Los otros tres:**

- **Qwen2.5-Coder-3B**: especialista real — 45/53 en código y **4/25 en
  razonamiento**. Escribe bien y decide mal. Ocupa 2.195 MiB: caben 3, no 4.
- **LFM2.5-2.6B**: 25/53 y **0/25**. El fabricante lo desaconseja para código y
  conocimiento y la medición lo confirma. **No queda descartado para el rol de
  memoria/RAG con 128K de contexto** que le asignaba `backends/lfm25-2b6/`: eso
  la batería no lo mide.
- **MiniCPM5-1B**: 9/53. Rapidísimo (254 tok/s, caben 6) e inservible para esto.
  Segundo modelo con una promesa en el nombre ("Thinking") que no se cumple.


---

## Tabla final: 14 configuraciones medidas (20/08)

Caudal = tok/s x cuántos caben x eficiencia medida por agente (0,48 con 4
agentes, 0,77 con 2 — ver `resultado_concurrencia.md`).

| modelo | n | código | rango | razonam. | rango | tok/s | VRAM | caben | caudal |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **gemma-4-E4B** | 5 | **51,4/53** | 50-52 | **17,0/25** | 16-18 | 83,6 | 3.221 Mi | 2 | 129 |
| **gemma-4-E2B** | 5 | 48,8/53 | 48-49 | 13,6/25 | 13-15 | 135,7 | 1.710 Mi | 4 | **260** |
| gemma-3n-E2B | 1 | 48,0/53 | — | 11,0/25 | — | 113,7 | 1.763 Mi | 4 | 218 |
| gemma-4-E2B QAT q4_0 | 3 | 46,0/53 | 45-47 | 13,0/25 | 12-14 | 140,6 | 1.644 Mi | 4 | 270 |
| Qwen2.5-Coder-3B | 1 | 45,0/53 | — | 4,0/25 | — | 135,9 | 2.195 Mi | 3 | 253 |
| Qwen3.5-2B MTP | 5 | 35,2/53 | 33-37 | 6,0/25 | 5-8 | 180,7 | 1.627 Mi | 4 | 347 |
| Qwen3.5-2B | 5 | 34,4/53 | 32-36 | 5,4/25 | 4-7 | 177,2 | 1.633 Mi | 4 | 340 |
| Qwen3.8-2B (Q4/Q5/Q8) | 8 | 27-30/53 | 25-32 | 6-7/25 | 4-10 | 142-185 | 1,5-2,2 G | 3-4 | 264-355 |
| LFM2.5-2.6B | 1 | 25,0/53 | — | 0,0/25 | — | 169,3 | 1.873 Mi | 3 | 315 |
| Qwen3.5-2B Reasoning-Distilled | 1 | 19,0/53 | — | 2,0/25 | — | 168,9 | 1.619 Mi | 4 | 324 |
| MiniCPM5-1B Thinking | 1 | 9,0/53 | — | 0,0/25 | — | 254,3 | 1.173 Mi | 6 | 732 |

### El QAT es PEOR, y confirmado

`gemma-4-E2B-it-qat-q4_0` de Google obtiene **46,0/53** contra **48,8** del Q4_K_M
normal, con rangos que **no se tocan** (45-47 contra 48-49) en 3 y 5 ejecuciones.
Contraintuitivo: Google entrena esos modelos justamente para resistir 4 bits, y
aun así la cuantización aplicada después rinde más en esta batería. Ahorra 66 MiB
y gana +4% de velocidad; cuesta ~3 puntos de código.

### Cuidado con la columna de caudal

MiniCPM5-1B lidera el caudal (732) con 9/53 de calidad. **El caudal solo no
decide**: seis agentes inútiles no hacen un sistema. Sirve para comparar modelos
de calidad parecida, no para ordenar la tabla.

### La decisión que queda

| opción | agentes | calidad | caudal |
|---|---:|---|---:|
| E4B | 2 | 51,4/53 · 17,0/25 | 129 |
| E2B | 4 | 48,8/53 · 13,6/25 | 260 |
| **mixto E4B+E2B** | 1+1 | el que decide y el que ejecuta | — |

Los dos caben juntos: 3.221 + 1.710 = 4,9 GB de los 7,4 disponibles.

---

## Convivencia E4B + E2B en la misma GPU (20/08)

`pruebas/rendimiento/medir_convivencia_2b.py`. Los dos cargados a la vez, 2 agentes en cada
uno, prompts distintos por solicitud.

**Caben con holgura**: E4B 3.159 MiB + E2B 1.705 = **5.833 de 7.832 MiB**, con
2 GB libres.

| | solo (2 agentes) | conviviendo | costo |
|---|---:|---:|---:|
| E4B | 124,5 tok/s | 91,7 | **-26%** |
| E2B | 218,6 tok/s | 93,4 | **-57%** |
| **total del equipo** | | **185,1 tok/s** | |

**Los dos convergen a ~92 tok/s.** Al compartir GPU se reparten el cómputo casi
en partes iguales, sin importar la velocidad de cada uno solo: el rápido renuncia
a 125 tok/s y el lento a 33.

**Es distinto de la convivencia 9B+30B** (-7% y -0,6%, `resultado_concurrencia.md`):
allí uno residía en VRAM y el otro en RAM, no competían por el mismo recurso. Aquí sí.

### Las tres opciones, medidas

| opción | calidad | caudal |
|---|---|---:|
| 4 x E2B | 48,8/53 · 13,6/25 | **260** |
| E4B + E2B | lo mejor de cada uno según la tarea | 185 |
| 2 x E4B | 51,4/53 · 17,0/25 | 129 |

El mixto cuesta **29% de caudal** contra 4xE2B y a cambio da acceso al único
modelo que razona 17/25.

**Advertencia antes de montarlo**: el reparto "uno planifica, otro ejecuta" se
midió TRES veces en este proyecto y las tres salió peor (atomic_ai en modelo
fuerte 79,3% vs 90,5%; pipeline de dos etapas 9/12 vs 12/12; atomic_ai en 2B 3/12
vs 6/12). Antes de montarlo hay que medir que el traspaso E4B->E2B mejore algo.

**Trampa del banco, ya corregida**: la primera versión dividía los tokens de cada
modelo por el reloj de la serie COMPLETA. Como los dos generan 2x128 tokens, el
resultado salía idéntico por construcción. Ahora cada modelo se mide contra su
propia ventana de tiempo.
