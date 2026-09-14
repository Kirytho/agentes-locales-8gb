# ¿Pueden convivir varios cerebros? — medido 22/07/2026

Las mediciones anteriores se hicieron **con cada modelo solo**, así que eran el mejor
caso posible. Esta prueba mide lo que la visión de varios expertos realmente necesita:
**qué cuesta que convivan**.

Montaje: **tres modelos residentes a la vez** — Bonsai-27B en GPU (8080),
Qwen2.5-Coder-1.5B en RAM (8083) y Qwen3.5-2B en RAM (8084).

---

## 1. La residencia es barata

| Concepto | Valor |
|---|---:|
| Suma de los archivos en disco | 6,37 GB |
| **RAM real de los 3 procesos** | **6,79 GB** |
| **Overhead** | **+6,6 %** |
| RAM libre del sistema | 15,6 GB de 31,9 GB |
| VRAM | 5646 MiB usados / 2379 libres |

**Corrige una estimación previa.** Se venía presupuestando **+38 % de overhead**,
extrapolado del GLM (14,2 GB de modelo → 19,6 GB de proceso). Ese número era específico
de *ese* modelo (MoE, contexto 8192, `--cpu-moe`): en modelos pequeños con contexto pequeño
el overhead es **de apenas 6,6 %**.

**Consecuencia: tener muchos cerebros residentes NO es el problema.** Con ~22 GB libres
caben cómodamente 8-10 expertos pequeños.

---

## 2. El paralelismo es caro

| Modelo | Solo | Los 3 a la vez | Penalización |
|---|---:|---:|---:|
| Bonsai-27B (GPU) | 29,1 t/s | 26,7 t/s | **−8 %** |
| Qwen2.5-Coder-1.5B (RAM) | 27,0 t/s | 13,9 t/s | **−49 %** |
| Qwen3.5-2B (RAM) | 19,4 t/s | 10,1 t/s | **−48 %** |

- **La GPU casi no sufre (−8 %)**, confirmando lo que ya mostraba `benchmark_base.md`:
  GPU y CPU apenas compiten.
- **Los dos modelos en RAM pierden la mitad de su velocidad cada uno.** Es exactamente
  lo que se espera de dos procesos repartiéndose un recurso único.

### El dato que de verdad importa: el caudal agregado no crece

| Escenario | Caudal total en RAM |
|---|---:|
| Un solo modelo trabajando | **27,0 t/s** |
| Dos modelos trabajando a la vez | 13,9 + 10,1 = **24,0 t/s** |

**Sumar un segundo modelo en RAM no aumenta el trabajo total: lo reparte** — y además
cuesta un 11 % en contención.

> **N modelos en RAM comparten un solo canal.** Pueden coexistir, pero no pueden trabajar
> en paralelo de forma productiva. El techo lo pone el ancho de banda (48 GB/s), no la
> cantidad de modelos.

### ¿Era sobresuscripción de hilos? No — probado

Con `--threads 6` en cada servidor, dos servidores suman **12 hilos sobre 6 núcleos**.
Se repitió la prueba con **3 hilos por servidor** (2 × 3 = 6 hilos sobre 6 núcleos, sin
sobresuscripción):

| Modelo | Solo 3h | Solo 6h | Juntos 3h | Juntos 6h |
|---|---:|---:|---:|---:|
| Bonsai-27B (GPU) | 29,5 | 29,1 | 27,7 | 26,7 |
| Coder-1.5B (RAM) | **24,9** | **27,0** | 14,7 | 13,9 |
| Qwen3.5-2B (RAM) | 18,8 | 19,4 | 10,6 | 10,1 |

| Caudal agregado en RAM | |
|---|---:|
| con 6 hilos | 24,0 t/s |
| con 3 hilos | **25,2 t/s** (+5 %) |

**La sobresuscripción NO era la causa principal.** Eliminarla mejora el caudal agregado
apenas un **5 %**, y la penalización baja de −49 %/−48 % a −41 %/−44 %. El grueso de la
degradación es **inherente a compartir el ancho de banda de memoria**, tal como predice
el modelo físico — no es un problema de planificación de CPU.

**Y hay un contra:** con 3 hilos cada modelo es **más lento cuando se ejecuta solo**
(el Coder cae de 27,0 a 24,9 t/s, −8 %).

> **Recomendación: dejar `--threads 6`.** Con enrutado los modelos **se turnan**, así que
> la velocidad *en solitario* es la que importa — y ahí 6 hilos gana por 8 %. La
> configuración de 3 hilos optimiza un escenario (generación concurrente) que el
> enrutado está justamente diseñado para evitar.

---

## 3. Qué significa para la visión

Las dos mediciones apuntan en direcciones distintas, y juntas dan la respuesta:

| Pregunta | Respuesta |
|---|---|
| ¿Pueden coexistir muchos cerebros? | **Sí.** El overhead es 6,6 % y sobra RAM |
| ¿Pueden trabajar todos a la vez? | **No.** El caudal agregado tiene un tope |

**Y aquí es donde el enrutado salva la arquitectura:** si el enrutador envía cada petición
a **un solo experto**, los modelos se turnan y cada uno trabaja a **velocidad plena**. La
penalización del 49 % solo aparece cuando dos generan **simultáneamente** — algo que con
un único usuario es infrecuente.

**Conclusión:** la visión de varios cerebros es viable **para un usuario que enruta**, y
falla **bajo carga concurrente**, justamente el modo en que el intermediario se usa hoy.

---

## 4. Lo que sigue sin medirse

- **Más de dos en RAM a la vez.** Si dos reparten el caudal a la mitad, cuatro deberían
  repartirlo en cuartos — pero conviene confirmarlo, y ver si la contención crece.
- **El tiempo de inicio** como alternativa a la residencia: si cargar un experto tarda
  ~2 s (medido hoy), quizá no haga falta tenerlos todos residentes.

## 5. El modelo de GPU como supervisor — YA PROBADO

> **Actualizado:** esta idea se midió el mismo día. Resultados en
> **`resultado_supervisor.md`**: detección 100 % (3/3), falso descubrimiento 0 % (0/9),
> costo 733 ms. Funciona — pero **ir directo a la GPU sale más rápido y acierta igual**,
> así que la cascada queda como modo de respaldo, no como ruta por defecto.

Propuesta del autor: **usar el modelo grande de la GPU para supervisar la salida de
los pequeños**.

Coincide con lo que recomienda la evidencia externa: la *cascada por incertidumbre* del
caso de fracaso documentado y el enfoque de CARGO hacen exactamente eso — revisar la
**salida** del modelo barato y escalar al capaz cuando la calidad no convence. Es la
pieza que le falta al diseño actual, que solo enruta por la **entrada**.

El costo a vigilar está cuantificado en *Cluster-Route-Escalate*: **51 % de falsos
descubrimientos** (escalan la mitad de las respuestas que ya eran correctas). Y esta
medición aporta un dato a favor: **supervisar sale barato**, porque el modelo de GPU solo
pierde un 8 % al convivir con los de RAM.
