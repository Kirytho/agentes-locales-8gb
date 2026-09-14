# Operar como agente: el harness y la conducta pesan más que el modelo (24/08 – 03/09/2026)

Resume varias mediciones sobre una misma pregunta: **¿por qué un modelo que
programa bien falla cuando tiene que operar herramientas?** Todas usan oráculos
sobre el resultado real (trazas de llamadas, archivos en disco), no la opinión de
un modelo.

**Bancos**: `pruebas/calidad/eval_agente.py` (herramientas simuladas) y
`pruebas/calidad/eval_stack_completo.py` (Hermes real → intermediario → modelo).
**Crudos publicados**: `resultado_agente_*.json`. Las ejecuciones del banco de
sistema completo quedaron en registros locales que no se incluyen; aquí se
reproducen sus tablas.

## 1. Un modelo puede obtener 51/53 programando y no servir para operar

El 23/08, gemma-4-E4B obtenía 51,4/53 en la batería de código y dentro de Hermes
no lograba terminar tareas simples. La batería no mide **operar**: pedir la
herramienta correcta, mirar antes de actuar, recuperarse de un error, parar
cuando terminó.

`eval_agente.py` mide eso con 7 escenarios y herramientas simuladas. El oráculo
revisa **qué** llamó el modelo, **en qué orden** y **con qué argumentos**. Antes
de medir modelos, el banco se prueba a sí mismo con 31 trazas escritas a mano
(`--autotest`).

## 2. Cinco defectos del banco antes de poder creerle

Los primeros resultados culpaban al modelo. Los cinco defectos eran del
instrumento:

| # | Defecto | Efecto |
|---|---|---|
| 1 | Las herramientas simuladas respondían `"ok"` a cualquier comando | el modelo que exploraba terminaba probando si la herramienta funcionaba |
| 2 | Ignoraban sus argumentos | listar `/` devolvía los archivos del proyecto |
| 3 | Leer un archivo devolvía `"ok"` en vez del contenido | un modelo releyó el mismo archivo ocho veces |
| 4 | `which` solo miraba el último argumento | la pregunta correcta recibía una respuesta vacía |
| 5 | Se contaba como bucle cualquier ejecución de más de 8 pasos | se confundía explorar de más con repetir lo mismo |

Además, el banco hablaba directo con el servidor del modelo, **sin la instrucción
de sistema que usa el intermediario**, así que no medía la configuración real.

El sesgo era asimétrico: un entorno incoherente no afecta a un modelo que casi no
llama herramientas, pero castiga al que explora.

## 3. Resultado con el banco corregido

| | gemma-4-E4B | Ornith-1.5-9B |
|---|---:|---:|
| sin instrucción de sistema | 6,0/7 | 5,3/7 |
| con la instrucción de brevedad del intermediario | **7,0/7** (8 ejecuciones, 56/56) | **5,4/7** |
| con el prompt real de Hermes (~5.700 tokens) + brevedad | **7,0/7** (8 ejecuciones) | — |

**La misma instrucción tiene efectos opuestos según el modelo.** En gemma, la
instrucción de brevedad arregló el escenario de recuperarse de un error (0/8 →
7/8, Fisher p = 0,0014): sin ella, explicaba el error al usuario en vez de
corregirlo. En Ornith rompió ese mismo escenario (3/3 → 0/5): sin espacio para
razonar en prosa, entraba a probar variantes de la misma orden.

Los fallos de Ornith no son bucles: nunca repite la misma llamada. Explora con
llamadas siempre nuevas y **no decide cuándo tiene suficiente información**.

**Consecuencia:** cambiar de modelo obliga a volver a medir la instrucción de
sistema, no solo el modelo.

## 4. En el sistema completo, el fallo no es de llamar herramientas

96 vueltas de agente con Hermes (21 herramientas, prompt de sistema de ~25.900
caracteres): **una sola llamada narrada como texto**. El modelo llama bien. Lo que
falla es que **no verifica contra la fuente**. Cuatro mecanismos, cada uno
confirmado por separado:

| mecanismo | cómo se confirmó |
|---|---|
| la lectura de archivos antepone `N\|` a cada línea; el análisis falla y queda un 0 | ejecutando la lectura y mirando la salida literal |
| una búsqueda con ruta absoluta como patrón vuelve vacía; el modelo concluye "no existe" y **fabrica los datos de entrada** | secuencia de llamadas grabada en el tráfico |
| escribe con separadores rotos (`\n` literal dentro del archivo) | inspección byte a byte |
| informa como éxito lo que nunca releyó | las ejecuciones que pasaron sí releyeron |

El segundo es el grave: destruye la entrada y reporta su invento. Desde entonces
el banco toma una huella SHA-1 de la entrada antes de ejecutar e informa aparte si
se modificó.

**Una skill no lo arregló.** Se escribió una skill apuntando al primer defecto:

| condición | aciertos | vueltas por ejecución |
|---|---:|---:|
| sin skill | 2/4 | 2,3 |
| skill disponible | 3/6 | 2,7 |
| skill forzada en la solicitud | 1/6 | 10,8 |

Sin forzarla, el modelo nunca la abrió (0 de 6). Forzada, costó 4 veces más
vueltas sin mejorar.

## 5. Un modelo más grande no es un mejor agente

Mismo banco de sistema completo (`eval_stack_completo.py`, 12 ejecuciones):

| modelo | parámetros | aciertos |
|---|---|---:|
| Ornith-1.5-9B-MTP | 9B denso | **11/12** |
| granite-4.2-3b | 3B | 10/12 |
| Qwen3-30B-A3B | 30B (3B activos) | **5/12** |

Ornith contra Qwen3-30B: p = 0,027. El 30B falla sin insistir: en el escenario de
inventario hizo una sola búsqueda, salió vacía y respondió que no había archivos,
tres de tres veces.

Salvedad del granite: una ejecución de 103 vueltas llamando a la terminal durante
300 s dejó el disco correcto, pero el agente nunca terminó. Contarla como acierto
inflaba el puntaje de 10/12 a 11/12; el banco ahora la cuenta como fallo.

## 6. Recortar herramientas empeora a la mitad (03/09)

El presupuesto fijo de Hermes pesa: ~15.300 tokens de esquemas de herramientas y
~7.400 de prompt de sistema. Parecía la forma más barata de liberar contexto. Se
midió quitando 7 herramientas que ninguna tarea del banco usaba (navegador, web,
voz, visión, uso de computadora, búsqueda de sesiones), 12 ejecuciones por brazo:

| | herramientas | aciertos | s/tarea |
|---|---:|---:|---:|
| A | 21 | **12/12** | 10,8 |
| B | 14 | **6/12** | 10,1 |

Fisher p = 0,014. **Con menos herramientas, el modelo dejó de usar
herramientas**: en el escenario `informe`, 2 de 3 ejecuciones respondieron sin
una sola llamada, sin mirar el directorio. No le faltaba ninguna de las quitadas.

## 7. El harness importa tanto como el modelo (03/09)

Misma tarea, mismo oráculo byte a byte, mismo intermediario y mismo modelo
(Ornith-1.5-9B-MTP). Solo cambia quién maneja el bucle:

| harness | resultado | tiempo | peticiones |
|---|---|---:|---:|
| Hermes | OK | 13 s | 5 |
| opencode | MAL (sin archivo) | 231 s | 43 |
| kimi | MAL (sin archivo) | 168 s | 13 |

- **opencode** falló con `Context size has been exceeded`: carga sus herramientas
  una por una y repetidas veces, y cada carga agranda la conversación.
- **kimi** abortó con `The API returned an empty response`: el modelo devolvió una
  respuesta vacía y kimi no reintenta.

**Salvedades:** una ejecución por harness y una sola tarea. La diferencia es
grande (13 s contra 231 s), pero no es una medición fina. Y Hermes juega de local:
el modelo, el contexto y las instrucciones se ajustaron midiendo con él.

## Qué queda establecido

- Operar como agente es una capacidad distinta de programar o razonar; la batería
  de código no la predice.
- El límite observado es de **conducta**: insistir, verificar contra la fuente,
  no rendirse ante un resultado vacío.
- La instrucción de sistema y el conjunto de herramientas cambian esa conducta, a
  veces en direcciones opuestas según el modelo. Hay que medirlos junto con el
  modelo.
