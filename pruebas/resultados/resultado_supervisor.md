# ¿Sirve que la GPU supervise a los modelos pequeños? — 22/07/2026

Idea del autor, registrada en `resultado_convivencia.md` §5 y probada ahora.
Arnés: `eval_supervisor.py`. Supervisor: **Bonsai-27B-Q1_0 en GPU**.

**Por qué esta prueba es objetiva:** los 12 códigos que juzga el supervisor ya fueron
verificados **por ejecución** en `eval_expertos.py`. Se sabe cuál está bien y cuál mal.
El supervisor no lo sabe. No hay margen para que el que analiza incline el resultado.

---

## 1. Detección: 12 de 12

| | Códigos | Supervisor acertó |
|---|---:|---:|
| Con error real | 3 | **3** |
| Correctos | 9 | **9** |

| Métrica | Medido | Referencia externa |
|---|---:|---:|
| **Detección** (errores detectados) | **100 %** | — |
| **Falso descubrimiento** (correctos escalados de más) | **0 %** | 51 % (*Cluster-Route-Escalate*) |
| Costo por revisión | **733 ms** | — |

Detectó los tres: `duracion` del especialista, `agrupar` del especialista y `duracion`
del control. No escaló ni uno solo de los nueve que estaban bien.

> **Esa salvedad se confirmó: el 100 % era suerte de una muestra pequeña.*** Repetida la prueba
> el 23/07 sobre **50 códigos con 18 errores reales** (batería de 25 tareas × 2 modelos),
> la detección cae a **56 %**. Ver la sección 6.

---

## 2. La otra mitad: ¿el destino de la escalada resuelve?

Detectar no sirve si el que recibe la escalada falla igual. Se le dieron al supervisor
las dos tareas que los modelos pequeños fallaron, verificando **por ejecución**:

| Tarea | Pequeños | Bonsai-27B | Tiempo |
|---|---|---|---:|
| `duracion` | fallan **los dos** | **RESUELVE** | 3,8 s |
| `agrupar` | falla el especialista | **RESUELVE** | 2,6 s |

**La cascada funciona.** Pequeño 5/6 + supervisión + escalada = **6/6**.

---

## 3. El resultado incómodo: en este hardware, la cascada no conviene para código

Sumando lo que cuesta cada camino para una tarea de código:

| Camino | Latencia | Aciertos |
|---|---:|---:|
| Solo el pequeño (control, 19,4 t/s) | ~5,5 s | 5/6 |
| Pequeño + supervisión + escalada del 25 % | ~7,0 s | **6/6** |
| **Directo a la GPU (Bonsai, 29,1 t/s)** | **~3,2 s** | **6/6** |

**Ir directo a la GPU es más rápido *y* más acertado que toda la cascada.** La cascada
existe para ahorrar un recurso caro; aquí el recurso "caro" (la GPU) resulta ser el
**barato**, porque tiene más ancho de banda que la RAM.

Esto no contradice la literatura: la contradice el hardware. En la nube el modelo grande
cuesta dinero por token y el pequeño es casi gratis, así que la cascada ahorra. Aquí el
modelo grande cuesta **VRAM ocupada**, que ya está pagada, y el pequeño cuesta **ancho de
banda de RAM**, que es el recurso escaso — el mismo hallazgo de `resultado_convivencia.md`,
visto desde otro ángulo.

### Cuándo sí conviene supervisar

La supervisión sigue siendo valiosa donde la generación en GPU no está disponible:

1. **Cuando la GPU está ocupada** con otra petición. Supervisar cuesta 733 ms; generar
   cuesta 3,2 s. Como **revisor** la GPU atiende ~4× más peticiones que como generador.
2. **Cuando no cabe el modelo grande*** — otro equipo, otra GPU, o el T1 tomado por un
   modelo de visión.
3. **Bajo concurrencia**, donde los pequeños de RAM pierden el 49 % cada uno y la GPU
   apenas el 8 %: ahí el reparto pequeño-genera / GPU-revisa aprovecha los dos canales.

> **Recomendación: no adoptar la cascada como ruta por defecto.** Implementarla como
> **modo de respaldo** para cuando el T1 esté saturado. La regla de la arquitectura de
> dos niveles no cambia: **si el modelo capaz cabe en la GPU, consultarlo directamente.***

---

## 4. Lo que esto aporta a la duda de fondo

`resultado_expertos.md` dejó planteada la tensión: los modelos de ≤2B **fallan con
confianza**, y esa es la falla que hundió el proyecto documentado en el caso externo.

**Esta medición aporta el antídoto:** el fallo con confianza es invisible *desde dentro*
del modelo pequeño, pero **es visible desde fuera**. El supervisor no se dejó engañar por
la fluidez: los tres códigos que detectó eran plausibles a la vista.

Eso desplaza la conclusión previa. La visión de varios cerebros pequeños no queda esperando
mejor hardware por falta de **confiabilidad** — la confiabilidad se puede recuperar con un
verificador externo barato. Queda esperando por lo que ya se midió en convivencia: el
**caudal agregado de RAM que no crece**. El límite sigue siendo físico, no de calidad.

---

## 6. Segunda ejecución sobre 50 códigos — 23/07/2026

Ampliada la batería a 25 tareas, el banco de juicios pasó de 12 a **50 códigos con 18
errores reales**. Mismo supervisor, mismo prompt, misma verdad por ejecución.

| Métrica | 12 códigos (3 errores) | **50 códigos (18 errores)** |
|---|---:|---:|
| **Detección** | 100 % (3/3) | **56 % (10/18)** |
| **Falso descubrimiento** | 0 % (0/9) | **0 % (0/32)** |
| Costo por revisión | 733 ms | 873 ms |

### El 100 % era suerte

Con tres errores, acertarlos todos por azar tiene probabilidad razonable. Con dieciocho,
el número real aparece: **el supervisor detecta algo más de la mitad**.

### El 0 % de falso descubrimiento, en cambio, se sostiene

Treinta y dos respuestas correctas y **ni una sola escalada de más**, contra el 51 % que
reporta *Cluster-Route-Escalate*. Con esta muestra ya es un resultado sólido, y es el que
define cómo conviene usar la supervisión:

> **Es una red parcial, pero nunca rompe nada.** Añadirla no puede empeorar una respuesta
> que ya estaba bien —jamás descartó una— y recupera algo más de la mitad de las que
> estaban mal. A 873 ms, el intercambio es claramente favorable.

### Corrección: no hay un patrón limpio por tipo de error

`resultado_equipo.md` afirmaba que la supervisión *"cubre errores de lógica visible y no
errores de conocimiento de la biblioteca"*. Esa regla se apoyaba en **un solo caso**. Con
18 errores clasificados no se sostiene:

| Clase de error | Detectados | No detectados |
|---|---:|---:|
| El código falla (`NameError`, `TypeError`, `ValueError`, `SyntaxError`) | 3 | 4 |
| El código se ejecuta y devuelve mal (`AssertionError`) | 6 | 5 |

**Aproximadamente mitad y mitad en las dos clases.** Y el mismo enunciado recibe veredictos
distintos según el código: `parentesis` fue detectado en un modelo y pasó inadvertido en el otro;
`duracion`, al revés. **Lo que decide no es el tipo de error ni la tarea, sino el código
concreto.** No hay una regla que permita anticipar qué se le va a escapar.

---

## 5. Lo que falta medir

1. **Errores sutiles.** Repetir con código que pasa la lectura y falla en un caso borde.
   Es la prueba que de verdad decide, y la que este banco no tiene.
2. **Muestra mayor.** Tres errores no sostienen una tasa de detección. Va junto con
   ampliar la batería a 20-30 tareas, que ya era el paso pendiente.
3. **Supervisión de razonamiento**, no solo de código. Ahí no hay verdad por ejecución,
   así que hay que juzgar a ciegas — y es donde el falso descubrimiento del 51 % que
   reporta la literatura tiene más probabilidades de aparecer.
4. **Supervisión concurrente**: medir la cascada con la GPU revisando mientras los pequeños
   generan, que es el escenario donde el punto 3 de arriba dice que conviene.
