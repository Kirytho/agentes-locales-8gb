# nanbeige4.2-3b-Q4_K_M — primera ejecución en Linux/CachyOS (27/07/2026)

Arnés: `eval_expertos.py`. Código verificado **por ejecución** en subproceso
aislado; razonamiento guardado sin etiquetar para juicio a ciegas. Backend:
principal (GPU, RTX 3060 Ti), compilado nativo para Linux esta sesión (ver
`backends/linux/README-linux-build.md`), cache-type `turbo3`.

> **Nota:** una sola ejecución, un solo modelo — no es una comparación (para
> eso están `resumen_bateria.py` y los demás `resultado_experto_*.md`). Sirve
> como línea base de que el build de Linux genera código funcionalmente
> correcto y a qué velocidad, no como veredicto sobre el modelo.

## Resultado

| | nanbeige4.2-3b-Q4_K_M |
|---|---:|
| Tamaño | 2,57 GB |
| **Código** (ejecutado) | **20/25** (80%) |
| **Velocidad** | **62,0 t/s** (61,3–63,0 t/s en las 25 tareas — muy estable) |
| Razonamiento | 4/4 respondidas, ver salvedad abajo |

## Código: las 5 que fallaron

Repasé el código generado en cada una — son errores reales del modelo, no
artefactos de extracción (el bloque ```python``` siempre se extrajo bien):

| Tarea | Error | Causa |
|---|---|---|
| `duracion` | AssertionError | El parser de "1h30m" separa mal horas/minutos con `.replace().split()`, pierde precisión en formatos combinados. |
| `romano` | TIMEOUT (bucle infinito) | La tabla de numerales romanos tiene entradas duplicadas y mal mapeadas (`1000` apunta a `'D'` en vez de `'M'`, `900`/`500`/`400` repetidos) — la resta nunca converge para números grandes. |
| `parentesis` | AssertionError | Balanceo de paréntesis implementado con un contador en vez de una pila real; `texto[contador - 1]` no tiene sentido como lookup de "tope de pila". |
| `bytes` | AssertionError | Formato de bytes humanos (KB/MB/GB) con bug de redondeo/formato en el caso fraccionario. |
| `lotes` | NameError | El modelo nombró la función `_lotes` en vez de `en_lotes` que pedía el enunciado — falla por incumplir la firma, no por lógica. |

## Razonamiento (guardado para juicio a ciegas)

| Pregunta | Respuesta (resumen) |
|---|---|
| Por qué un índice acelera lecturas y enlentece escrituras | Correcta y concisa. |
| Cuándo monolito vs. microservicios | Correcta, algo más larga de lo pedido (se fue de "3 frases" a varios párrafos con viñetas). |
| Por qué Python compila a código máquina nativo (premisa falsa a propósito) | **Detectó la trampa** — corrigió que Python no compila a nativo, sino a bytecode. Pero la respuesta **mezcla portugués** ("não", "é", "máquina", "código") en medio del español, un glitch de idioma real, visible en el JSON crudo. |
| Qué problema resuelve la inyección de dependencias | Correcta. |

Vale la pena notar el paralelo con `resultado_expertos.md` (otra ejecución,
otro modelo): la misma clase de pregunta trampa ("Python compila a código
máquina nativo") volvió a producir mezcla de idiomas ahí también ("el
control... derivó al portugués"). Parece un patrón recurrente en esa
pregunta específica más que una rareza de este modelo — no verificado con
más ejecuciones.

## Fuente

Detalle completo (código generado tarea por tarea, texto íntegro de las 4
respuestas de razonamiento) en `resultado_experto_nanbeige3b_linux.json`,
mismo formato que usa `resumen_bateria.py` para comparar ejecuciones.
