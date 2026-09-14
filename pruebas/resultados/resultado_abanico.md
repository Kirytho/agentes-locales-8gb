# Abanico de subagentes: repartir y consolidar son capacidades distintas (28/08 – 07/09/2026)

**Pregunta:** si una tarea se divide naturalmente en partes independientes,
¿el agente la reparte entre subagentes y junta los resultados?

**Escenario:** N archivos de servicio de ~540 líneas cada uno, con **un solo
defecto** por archivo. El agente tiene que encontrarlos y escribir un único
archivo de hallazgos. La tarea tiene forma de delegación: leer todo en una sola
sesión cuesta más de la mitad del contexto.

**Bancos:** `pruebas/calidad/eval_fanout.py` (16 servicios) y
`eval_fanout_pequeno.py` (4 servicios), sobre Hermes → intermediario → modelo.
Para contar delegaciones útiles: `herramientas/medir_reparto.py`.
**Crudos:** registros locales, no incluidos; aquí se reproducen las tablas.

## 1. La delegación sí se dispara (28/08)

Con 8 servicios, `delegate_task` de Hermes lanzó 8 subagentes en paralelo (dos
llamadas), visibles en el tráfico con 18 herramientas y ~22.600 caracteres de
prompt de sistema cada uno.

Y ahí falló, con **308 errores** de `Context size has been exceeded`:

```
por subagente:  ~5.657 tokens de prompt + ~5.651 del archivo = ~11.308
8 en paralelo:  ~90.464 tokens
reserva de KV compartida (--kv-unified, ctx 81.920): 81.920
```

Con `--kv-unified` el contexto es **una reserva única** entre todos los slots, y
cada subagente retiene la suya. El techo era de ~7 subagentes; con el contexto
posterior de 98.304 pasó a 8.

Antes de esto hubo un falso negativo: con las tareas mecánicas del banco (sumar,
contar), el modelo nunca delegaba. Tenía razón: la descripción de la herramienta
dice que no se use para trabajo mecánico sin razonamiento. Hizo falta una tarea
con forma de delegación para verlo.

## 2. Con 16 servicios: 0 aciertos (07/09)

7 ejecuciones con 6 modelos: cinco cuantizaciones de Ornith-1.5-9B-MTP y la
versión ternaria. **Ningún acierto.** Cada modelo eligió una estrategia distinta (leer archivo por archivo,
usar la terminal, escribir scripts, ejecutar código) y todos terminaron igual.

Se subió antes el límite de subagentes concurrentes de Hermes de 10 a 16: por
defecto, **Hermes descarta en silencio** las llamadas que lo exceden, y se habría
medido ese tope en vez del modelo.

## 3. Con 4 servicios: el hallazgo real

| modelo | puntaje | llamadas | tareas repartidas | servicios reales apuntados | entregó |
|---|---:|---:|---:|---:|---|
| IQ3_M | 4/4 | 4 | 4 | 0/4 | sí |
| IQ2_M | 1/4 | 4 | 4 | 0/4 | sí |
| Q4_K_M | 0/4 | 0 | 0 | 0/4 | no |
| IQ4_XS | 0/4 | 1 | 4 | **4/4** | **no** |
| Q5_K_M | 0/4 | 4 | 4 | **4/4** | **no** |
| TB-8B (ternario) | 0/4 | 1 | 4 | **4/4** | **no** |

**Repartir y consolidar son capacidades separadas, y ningún modelo tiene las
dos:**

- **Tres modelos reparten bien** (apuntan a los 4 servicios reales con rutas
  válidas) y son exactamente **los tres que no entregan nada**. La separación es
  perfecta, sin cruces. Q5_K_M cerró diciendo que iba a leer y analizar cada
  función **después** de haber delegado bien: anunció en vez de hacer.
- **IQ3_M entregó 4/4 perfecto**, pero delegó a nombres de servicio inventados
  que no existen. Resolvió todo solo, con 17 lecturas y 35 llamadas a la
  terminal. El reparto fue decorativo.
- **IQ2_M** delegó a rutas falsas y entregó un archivo con 3 de 4 funciones
  **inventadas**, con nombres de relleno y formato válido.

**Contar llamadas a `delegate_task` da la conclusión al revés:** habría coronado
a IQ3_M como el mejor coordinador, y es el que peor delegó. Por eso
`medir_reparto.py` cuenta servicios reales apuntados, no llamadas.

La forma canónica de delegar la usó solo IQ4_XS: **una** llamada con una lista de
4 tareas, cada una con su ruta y su contexto.

## 4. Lo que agota el contexto no es el paralelismo

Durante horas se sostuvo que la reserva de KV se agotaba por la concurrencia
(agente principal + 4 subagentes sobre 98.304 tokens). **Es falso:** una
ejecución con **cero delegaciones** produjo 32 errores de contexto. El agente
principal solo, con 25.941 caracteres de prompt de sistema más cuatro archivos de
~9.600 tokens, ya no cabe.

El error de razonamiento fue reproducir a propósito una condición **suficiente**
(cinco sesiones grandes concurrentes), verla fallar y tomarla por **necesaria**.

Palancas evaluadas:

| palanca | resultado |
|---|---|
| subir `--parallel` | no sirve: con reserva compartida, más slots son más sesiones sobre el mismo contexto |
| menos ramas (4 → 2) | no concluyente: la delegación es aleatoria (1, 1 y 0 delegaciones con el mismo modelo) |
| menos herramientas solo para las ramas | Hermes no lo permite: los subagentes heredan siempre las herramientas del agente principal |
| menos herramientas para todos | medido: empeora de 12/12 a 6/12 (ver [agente y harness](resultado_agente_harness.md)) |

Hermes **sí** permite asignar un modelo distinto a los subagentes, pero lo decide
la configuración, no el modelo.

## Qué queda establecido

- La delegación funciona en el harness; el techo es la **reserva de contexto**,
  no la concurrencia ni un repartidor faltante.
- Con 8 GB de VRAM, cuatro archivos de ~540 líneas ya son demasiado para una sola
  sesión de agente.
- **Riesgo para automatización desatendida:** un modelo entregó un archivo con
  formato válido y contenido inventado. Es peor que no entregar, porque pasa
  inadvertido. El oráculo tiene que verificar el contenido contra la fuente, no
  solo el formato.
