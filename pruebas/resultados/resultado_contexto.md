# Cuánto contexto usa una solicitud real (y un bug que apareció al medirlo)

**Fecha**: 17/08/2026 · **Script**: `pruebas/medir_contexto.py`
**Crudos**: `pruebas/resultado_contexto.json`
**Cómo**: conversación de 12 turnos contra el intermediario (:8086), enviando en
cada turno el historial completo, como haría un cliente. El `prompt_tokens` que
devuelve la respuesta cuenta el prompt **ya construido por el intermediario**,
con la memoria inyectada dentro.

## La respuesta: el contexto sobra

| turno | mensajes enviados | prompt tokens | salida |
|---:|---:|---:|---:|
| 1 | 1 | 69 | 120 |
| 2 | 3 | 206 | 120 |
| 3 | 5 | 417 | 120 |
| 5 | 9 | **744** | 120 |
| 6 | 11 | 718 | 120 |
| 7 | 13 | 702 | 120 |

**Máximo medido: 744 tokens de prompt, 864 contando la respuesta.** Contra un
slot de 4096 eso es el **18%**; contra uno de 8192, el 9%.

Y no crece indefinidamente: del turno 5 al 7 se mantiene estable (744, 718, 702)
porque el intermediario recorta el historial a 15 mensajes (8 en el backend de
CPU) y los bloques de memoria tienen un tope de 1000 caracteres comprimidos al
50%.

**Conclusión: dividir el contexto en cuatro slots de 4096 no perjudica a nadie.**
El cuello de botella no es el contexto — con este perfil de uso sobra cinco
veces. La decisión de `--parallel 4` (de 88,7 a 119,8 tok/s agregados) no tiene
contras.

Salvedad honesta: esto mide una conversación de trabajo con respuestas de 120
tokens. Un agente que reciba un archivo entero pegado en la solicitud consume
otra cantidad; para ese caso hay que medir de nuevo.

## El bug: la caché semántica responde preguntas que no le hicieron

De los 12 turnos, **6 nunca llegaron al modelo**: los respondió la caché
semántica en 0,1 s con una respuesta antigua. Y ninguna de las 6 correspondía.

Las preguntas del banco están redactadas en lenguaje coloquial; aquí se muestran
en español neutro.

| turno | lo que se preguntó | lo que respondió |
|---|---|---|
| 4 | "¿Qué pasa si la tabla tiene celdas con colspan?" | la función que analiza la tabla (turno 3) |
| 8 | "Quiero guardarlo en SQLite, escribe el esquema" | la función que analiza la tabla |
| 9 | "La función que inserta evitando duplicados" | la función que analiza la tabla |
| 10 | "Resume todo lo que llevamos" | la función que analiza la tabla |
| 11 | "¿Cuál función es la más frágil?" | la función que analiza la tabla |
| 12 | "Escribe el README del proyecto" | la respuesta sobre reintentos (turno 7) |

Las estadísticas de la caché lo confirman: **6 aciertos sobre 12 consultas, 50%
de acierto declarado** — y los seis eran errores.

### Por qué pasa

La caché se consultaba **solo con el último mensaje del usuario**, sin la
conversación, y con un umbral de similitud de 0,55.

Dentro de una conversación sobre un mismo tema, dos preguntas distintas superan
0,55 de similitud de coseno sin ningún esfuerzo: "escribe la función que analiza
la tabla" y "¿qué pasa si la tabla tiene colspan?" hablan de lo mismo aunque
pidan cosas opuestas. La caché las considera equivalentes y devuelve la antigua.

### Por qué importa más de lo que parece

En una consulta suelta el error es molesto. En un sistema **multiagente**, donde
los agentes mantienen conversaciones largas sobre un mismo tema, es devastador:
cuanto más enfocado está el agente, más se parecen entre sí sus solicitudes, y
con más frecuencia la caché le devuelve algo falso. Justo lo contrario de lo que
uno querría.

Además revela un riesgo silencioso: el 50% de "hit rate" que muestran las
estadísticas se lee como un logro de eficiencia cuando en realidad es la tasa de
respuestas equivocadas.

### Qué habría que hacer

1. **Subir el umbral** bastante por encima de 0,55 y medirlo con un banco de
   pares (pregunta nueva contra pregunta en caché) que indique cuál es el punto
   donde deja de confundir sin dejar de servir.
2. **Incluir contexto en la clave**, no solo el último mensaje — al menos el
   turno anterior, o el identificador de sesión, para que la caché no mezcle
   respuestas entre momentos distintos de una misma conversación.
3. **Desactivarla para solicitudes con historial** hasta que 1 y 2 estén hechos:
   si hay más de un mensaje del usuario, ir al modelo.

Nota: la caché quedó vaciada — las 6 entradas eran las que generó esta prueba.

---

## Arreglo aplicado (18/08/2026)

### 1. Nivel semántico desactivado por defecto

La caché semántica pasó a estar desactivada salvo que se active con una variable
de entorno.

No fue una decisión de gusto: se midió con un banco de 19 pares etiquetados a
mano **antes** de medir. El resultado descartó la solución obvia — subir el
umbral:

| par | coseno |
|---|---:|
| "cómo conecto a postgres" vs "cómo **cierro la conexión** a postgres" | **0,964** |
| "cómo funciona el garbage collector" vs "cómo lo **desactivo**" | **0,971** |
| "instala docker" vs "**desinstala** docker" | **0,874** |
| paráfrasis legítima, la más débil | **0,535** |

Los pares que hay que **rechazar** puntúan más alto que los que hay que
**aceptar**. Ningún umbral los separa. Se probó además exigir parecido léxico
(Jaccard de palabras): toda regla que bloquea los 12 casos peligrosos bloquea
también los 7 reusos legítimos (0/7). No hay punto de corte que sirva.

### 2. El nivel exacto absorbe la puntuación

La normalización de la consulta ahora elimina signos y une espacios (las tildes
se conservan: son parte de la palabra). Así "¿Qué hace git bisect?" y "Que hace
git bisect" dan el mismo hash — lo que antes resolvía el nivel semántico, ahora
lo resuelve el camino seguro. Verificado de extremo a extremo: la variante con
signos devolvió `prompt_tokens: 0` (acierto), y "cómo **desactivo** git bisect"
fue al modelo (40 tokens), que es lo correcto.

### 3. No se guarda en caché lo que depende de la conversación

Una solicitud solo se considera autocontenida si no hubo turno del asistente y
hay un único mensaje del usuario. Si no lo es, la caché no se consulta **y** la
respuesta no se guarda, tanto con streaming como sin él.

El motivo: la clave es el último mensaje del usuario. "y ahora añade pruebas" no
significa nada por sí solo; guardarlo bajo esa clave contamina la caché para
cualquier otra conversación.

### Verificación: la misma prueba que reveló el bug

| | antes | después |
|---|---:|---:|
| turnos que llegaron al modelo | 6 de 12 | **12 de 12** |
| respuestas de otro turno | **6** | **0** |
| consultas a la caché en la conversación | 12 | 1 (solo el turno 1) |

Y la caché sigue sirviendo donde es seguro: la misma pregunta suelta repetida
dio acierto (`prompt_tokens: 0`, respuesta idéntica de 239 caracteres).

Pruebas: **260/260** unitarias, incluidas las 8 de caché del banco de
integración — la de coincidencia semántica cercana ahora pasa por el nivel exacto
con similitud 1,0.

## Bug adicional que la caché estaba ocultando

Al corregir lo anterior, el turno 9 empezó a fallar con **500** del backend:

```
Error: Jinja Exception: System message must be at the beginning.
```

Causa: pasados los 15 mensajes, el manejo de contexto antepone un mensaje
`system` con la nota de historial omitido. Después, el inyector de fragmentos
relevantes insertaba **un segundo** `system` en la posición 1, y la plantilla de
Qwen3.8 rechaza la solicitud entera. El inyector de bloques de memoria ya tenía
resuelto ese problema fusionando en el `system` existente; el otro inyector no.

Se corrigió con la misma fusión.

**Estaba oculto desde siempre**: las conversaciones solo llegan a 15 mensajes en
el turno 8 o 9, y hasta ahora esos turnos los respondía la caché sin consultar el
modelo. Un bug ocultaba al otro.
