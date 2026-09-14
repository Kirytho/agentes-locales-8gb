# Plan+ejecución vs. reparto en equipo — 4 solicitudes, 2 modelos (27/07/2026)

Comparación real (código ejecutado con asserts, no leído a ojo) de los dos
caminos para repartir una solicitud de código entre `nanbeige4.2-3b` y
`Qwen3.5-4B` en Linux. 4 solicitudes en total: la primera (validación de
formulario) de la ejecución anterior, más 3 nuevos con distinto nivel de
acoplamiento entre sus partes — independientes, moderado, y explícitamente
dependiente — para no extraer conclusiones de una sola muestra.

## Aviso metodológico importante: la verificación de VRAM del pipeline

En la segunda serie, con los dos modelos ya cargados a la vez (~1GB libre de
8GB), el pipeline **falló en silencio** en 2 de 3 solicitudes nuevas —
el intermediario exige 1.0 GB de VRAM libre antes de ejecutar la
etapa de ejecución, y con ese margen tan ajustado la verificación fallaba
("VRAM too low (0.8GB) for qwen35") y la solicitud volvía al enrutado
normal de un solo modelo, sin que la respuesta lo indicara (no hay
ninguna marca de pipeline cuando esto pasa). Se detectó, se le bajó el `--ctx-size`
a los dos modelos (16384/8192 → 4096 los dos) para liberar margen, y se
repitieron esas 2 solicitudes — ahí sí con el pipeline activado de verdad. Los
números de abajo ya son los corregidos.

**Hallazgo aparte, útil para producción**: en este hardware (8GB, dos
modelos de ~3GB simultáneos), el pipeline plan+ejecución es genuinamente
frágil por margen de VRAM — no es un caso raro, pasó en 2 de 3 intentos con
la config por defecto. Si se quiere usar pipeline con dos modelos residentes
a la vez, hace falta un contexto más pequeño que el predeterminado, o más VRAM.

## Resultado por tarea

| Tarea | Acoplamiento | Pipeline | Equipo |
|---|---|---|---|
| Validación de formulario (ejecución anterior) | moderado | ❌ bug de 1 línea (no quita el `+`) | ❌ reescribió la especificación del teléfono, no cumple la solicitud |
| `independiente` (palíndromo numérico + siguiente primo) | ninguno | ✅ PASA (34,8s) | ✅ PASA (36,2s) |
| `moderado` (inventario: 3 funciones sobre el mismo dict) | comparten estructura, no lógica | ✅ PASA (32,5s) | ✅ PASA (35,4s) |
| `dependiente` (parser INI: la 2da función usa el resultado de la 1ra) | fuerte | ⚠️ falla mi test, no el código (ver abajo) (40,2s) | ❌ `SyntaxError` real: `if/elif/else/else` duplicado (48,3s) |

### Sobre el "fallo" del pipeline en `dependiente`

No es un bug del modelo: mi test llamaba
`get_valor_tipado(config, "puerto", int)` pasando el **objeto** `int`, pero
el modelo generado esperaba el **string** `'int'`
(`get_valor_tipado(config, 'max_users', 'int')`). El enunciado decía "un
tipo (int, float, bool o str)", que admite las dos lecturas — el modelo
eligió una razonable, mi arnés de test asumía la otra. Es una ambigüedad de
la consigna, no una falla de generación. El código del equipo, en cambio,
interpretó "tipo" como el objeto (coincidiendo con mi test) pero **no
compila** — un bug real y sin ambigüedad posible.

## Comparación acumulada (las 4 solicitudes)

| | Plan + ejecución | Reparto en equipo |
|---|---:|---:|
| Pasa limpio | 2/4 (independiente, moderado) | 2/4 (independiente, moderado) |
| Falla por bug real de código | 1/4 (formulario, bug de 1 línea) | 2/4 (formulario — reescribió la spec; dependiente — no compila) |
| Falla por ambigüedad del test, no del código | 1/4 (dependiente) | 0/4 |
| Tiempo típico | ~25-52s | ~35-49s (similar) |
| Ya integrado en el intermediario | Sí | No (script en `pruebas/`) |
| Riesgo operativo encontrado | Falla en silencio si el margen de VRAM es pequeño | Ninguno nuevo (no depende de la verificación de VRAM) |

## Conclusión, con más muestra

Con 4 solicitudes en vez de 1, la imagen es más equilibrada de lo que sugería la
primera ejecución, pero **plan+ejecución sigue adelante**: sus fallos son más
pequeños (un bug de una línea, o directamente un problema de mi test, no del
modelo) contra fallos del equipo que incluyen **código que ni compila** y
**una reescritura completa de la especificación** — ambos indicando que el
paso de "unificar" del modo equipo es el punto débil: cuando el coordinador
reescribe en vez de solo revisar, puede introducir errores nuevos que
ninguna de las dos partes originales tenía.

El hallazgo de VRAM es tan importante como el de calidad: con dos modelos
residentes en 8GB, confiar en el pipeline sin margen extra es arriesgado
independientemente de qué tan bueno sea el reparto.

**Con 4 muestras la conclusión es más firme que con 1, pero sigue sin ser
definitiva** — para más confianza haría falta una batería más grande (tipo
`eval_expertos.py`, 20+ tareas) en vez de 4 solicitudes elegidas a mano.

## Fuente

- `resultado_reparto_multi.json` — ejecución original de las 3 solicitudes nuevas
  (incluye el caso con el pipeline fallido en silencio, para que quede registro).
- `resultado_reparto_pipeline_rerun.json` — repetición de `moderado` y
  `dependiente` con VRAM suficiente, los números que se usan arriba.
- `resultado_reparto_equipo.json` — detalle de la primera solicitud (formulario).
- Scripts: `eval_reparto_codigo.py` (1 solicitud, interactivo/manual),
  `eval_reparto_multi.py` (N solicitudes, reutilizable — TAREAS es una lista, se
  pueden añadir más).

## Conclusión general: ¿esto sirve para programar en serio? (27/07/2026)

Pregunta directa del usuario tras ver los 4 resultados: si esto sirve para
uso normal de programación, no solo para funciones sueltas de juguete.

**Para tareas pequeñas y bien especificadas*** (una función utilitaria, un
algoritmo conocido, boilerplate) — sí, razonablemente. El mejor de los tres
modelos probados (Qwen3.5-4B solo, sin repartir nada) dio 23/25 en
`eval_expertos.py` a ~98 t/s.

**Para programar en el sentido amplio** — no verificado, y hay motivo para
ser escéptico. Todo lo medido en esta sesión fueron funciones aisladas de
10-20 líneas con un enunciado sin ambigüedad real (o con ambigüedad menor,
como se vio en la tarea del parser INI). Eso es mucho más fácil que trabajar
sobre un código existente, entender contexto de varios archivos, resolver un
bug esquivo, o interpretar una solicitud ambigua de un usuario real. Son modelos
de 3-4B — nada de lo probado midió si soportan eso. El propio proyecto
apunta en producción a modelos más grandes (Qwythos-9B / GLM-23B, según el
registro de estado del proyecto), y la conclusión de la campaña de medición original ya decía
"la mejora decisiva es más VRAM" — lo de hoy no contradice eso, lo confirma
con una muestra nueva.

### Sobre repartir el trabajo entre "subagentes" en vez de conseguir más hardware

El usuario preguntó si, en lugar de más VRAM, esto podría funcionar con
subagentes (repartir el trabajo entre varios modelos/instancias en vez de
usar un modelo más grande). La respuesta, con los datos de esta misma
sesión: **no, y ya se probó** — el "modo equipo" (`eval_reparto_multi.py`)
es exactamente ese patrón, y en 2 de 4 solicitudes salió **peor** que consultar
a un solo modelo directamente, porque el paso de "unificar" introdujo errores que
ninguna de las partes originales tenía (el `SyntaxError` de `if/elif/else/else`
duplicado en la tarea `dependiente` es el ejemplo más claro: ni nanbeige ni
Qwen3.5-4B por separado cometieron ese error, apareció solo al combinar).

La razón de fondo: **repartir trabajo entre subagentes no le añade
capacidad de razonamiento a un modelo pequeño, solo le añade paralelismo y
organización.*** Subagentes funcionan bien cuando el modelo de base ya es
capaz (ahí sirven para manejar contexto y explorar en paralelo cosas
independientes) — no compensan que el modelo de base sea débil, y el paso
extra de coordinar/unificar es un lugar nuevo donde pueden aparecer errores
que no existían en ninguna de las partes. Con modelos de 3-4B, sumar
subagentes multiplica el riesgo sin sumar inteligencia real.

**Conclusión**: más VRAM → modelo más grande → mejora real y medida. Más
subagentes con el mismo modelo pequeño → no es un atajo, y en esta sesión
empeoró los resultados en la mitad de los casos probados.
