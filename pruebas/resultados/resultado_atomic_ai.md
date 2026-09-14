# Atomic AI (proxy de descomposición de tareas) — probado y descartado (11-19/08/2026)

> **ESTADO: retirado del proyecto el 16/08/2026.** Nunca llegó a estar
> activo (siempre fue opcional y nunca se incluyó entre los backends por
> defecto). Se retiró después de medirlo contra el mismo backend directo, con
> estos números:
>
> | | precisión (ejercicios que pasaron su prueba) | duración promedio |
> |---|---:|---:|
> | llamada directa | **90.5%** | **20.4 s** |
> | vía atomic_ai | 79.3% | 77.4 s |
>
> Es decir: peor precisión **y** ~3.7x más lento. La medición completa quedó en
> una hoja de cálculo de una copia experimental (ejecuciones
> `atomic_complejo_*` y `bench_atomic_analisis`), que no forma parte de este
> repositorio.
>
> Qué se borró: `backends/atomic_ai/` (71 MB) y su entrada en la configuración
> del intermediario.
>
> Lo de abajo es el informe original del 11/08; se conserva como registro de
> qué se probó y por qué en su momento pareció prometedor.

---

**Fecha**: 11/08/2026
**Dónde**: `backends/atomic_ai/` (copiado de `github.com/Nichonauta/atomic_ai`,
un repositorio de 1 día al momento de copiarlo — 3 estrellas, código sin
revisión comunitaria; se probó a mano aquí antes de confiar en él).

## Qué hace

Proxy que se sitúa delante de un backend compatible con OpenAI (aquí: nanbeige,
backend principal, puerto 8080). Recibe una instrucción, decide si es atómica o
si conviene dividirla en subtareas (árbol recursivo hasta
`MAX_DECOMPOSITION_DEPTH`), ejecuta cada hoja con su propia llamada al
modelo y sintetiza la respuesta final. Usa el protocolo OpenAI hacia dentro y
hacia fuera — no necesitó ningún cambio de código en el intermediario para
conectarse a nanbeige.

## Pruebas reales ejecutadas

| Tarea | Profundidad | Tiempo | Resultado |
|---|---:|---:|---|
| Función que valida email (copia experimental) | 1 | ~42s | OK, código correcto, decidió que era atómica |
| Factorial con manejo de errores (proyecto real) | 2 | ~5m33s | OK, código correcto (`ValueError`+`TypeError`), `finish_reason: stop` |

Las dos veces devolvió código Python real y correcto, con el árbol de
descomposición visible en `reasoning_content` (fases explícitas: dividir →
ejecutar subtareas → sintetizar).

## Costo real — el compromiso que importa

**Mucho más lento que consultar directamente al backend.** Una función de email
en profundidad 1 tardó 42s (contra ~1-2s de una solicitud directa a
nanbeige). Una tarea con dos aspectos (cálculo + manejo de errores)
en profundidad 2 tardó más de 5 minutos — cada subtarea es una llamada
completa al modelo, y con un 3B a ~50 tok/s eso se nota mucho. Profundidad
3 (probada en la copia experimental, no en el proyecto real) tardó varios
minutos incluso para una tarea simple — por eso se bajó a 2 en la
configuración de producción.

## Cómo quedó integrado

- `backends/atomic_ai/` — código copiado, configurado para reenviar a
  `http://127.0.0.1:8080` (nanbeige), con su propio entorno virtual
  (ligero, FastAPI/uvicorn/httpx, sin PyTorch).
- Un lanzador con el mismo patrón que los demás backends; requiere que el
  backend principal ya esté en ejecución.
- Una entrada nueva en la configuración del intermediario, de tipo proxy (no
  GPU, a propósito). **Opcional**: no estaba entre los backends por defecto y,
  aunque se añadiera, quedaba fuera del filtro automático de backends GPU. No se
  le asignó ningún rol, así que el clasificador nunca lo elegía por sí solo.

## Por qué opcional y no enrutado automático

El costo en tiempo es real y grande. Incluirlo en el enrutado automático haría
que cualquier pregunta de esa clase tardara minutos en vez de segundos, sin que
el usuario lo hubiera pedido. Para usarlo había que activarlo con una variable de
entorno (sin cambiar código) y consultar directamente su puerto (8000) o pedirlo
como modelo explícito — no pasaba por el clasificador automático.

## Pendiente si se quiere ir más allá

- No se probó con `tool_calls` reales (el proxy los soporta según su
  documentación: pausa y devuelve al cliente — no se ejercitó ese camino).
- No se decidió si vale la pena exponerlo como opción explícita en el
  clasificador (p. ej. "modo profundo", activado por el usuario en la
  solicitud) — ese sería el siguiente paso si se quiere usar más allá de lo
  manual.

---

## Probado de nuevo en modelos pequeños (19/08/2026)

**La hipótesis**: la prueba de agosto fue contra un modelo *fuerte*, donde
descomponer solo añade llamadas. En un modelo *débil* el argumento se invierte
— si falla por no sostener varias cosas a la vez, dividirlas debería ayudar.
Además la aritmética del tiempo cuadraba: atomic cuesta 3,7× y el 2B es 3,2× más
rápido que el 9B, así que `2B + atomic ≈ 9B directo` en tiempo de reloj. El
premio sería grande: cuatro agentes de esos caben en la GPU donde cabe un 9B.

**Montaje**: `Qwen3.8-2B-Q5_K_M` en :8080, proxy en :8000 con
`MAX_DECOMPOSITION_DEPTH=2` (con 3 el informe original ya medía minutos por
tarea simple). Las dos ramas sobre **el mismo subconjunto** de 12 tareas y 12
preguntas. Umbrales fijados **antes** de medir.

| | 2B directo | 2B + atomic | umbral |
|---|---:|---:|---:|
| código | 6/12 | **3/12** | ≥ 9/12 |
| razonamiento | 2/12 | 3/12 | ≥ 6/12 |
| tiempo por tarea | 2,5 s | 3,8 s (**1,5×**) | ≤ 3× |

**El tiempo no fue el problema**: 1,5×, no 3,7×. Con un modelo rápido, el proxy
además decide que muchas tareas son atómicas y no las divide.

**Falló la calidad, y por el mecanismo esperable**: descomponer *es* razonar. El
proxy le pide al modelo que decida cómo dividir el problema — justo lo que peor
hace (6/25 en la batería de razonamiento). No lo ayuda: le añade un trabajo
difícil ANTES del trabajo fácil.

No es un artefacto del banco. En `aplanar`, el directo escribió
`if isinstance(item, list)` y el proxy `[elem for sublist in lista for elem in
sublist]`, que falla con `TypeError` si un elemento no es lista.

**Tercera medición independiente en la misma dirección**: atomic en modelo fuerte
(79,3% contra 90,5%), el pipeline de dos etapas del 19/08 (9/12 contra 12/12) y
esta. La descomposición previa no compensa en este proyecto.

> **Matiz posterior (22/08):** el pipeline del 19/08 fallaba sobre todo por su
> prompt de ejecución, no por dividir en dos etapas; con un prompt sano, planificar
> dio lo mismo que no planificar (51 contra 50 de 53). La conclusión sobre atomic
> se mantiene, pero ese apoyo es más débil de lo que parecía. Ver
> [misma tarea](resultado_misma_tarea.md).

**Salvedad**: 12 tareas, una ejecución. Por sí solo, un 6→3 no bastaría; junto con
las otras dos mediciones y la explicación mecánica, basta para no seguir
invirtiendo en esto.
