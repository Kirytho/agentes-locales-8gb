# Repartir un proyecto entre N trabajadores: cuesta lo mismo, tarda menos (12/09/2026)

Cuatro trabajadores concurrentes contra UN modelo, usando los slots de
`--parallel` del llama-server. No subagentes de un harness: un subagente de
Hermes arrastra ~5.657 tokens de prompt de sistema propio y por eso el abanico
agotaba la reserva de KV (medido el 28/08 y el 07/09). Un slot cuesta una
fracción.

```
modelo    K2-Horizon-7B-Q4_K_S, ctx 32.768, --parallel 4 --kv-unified
          6.800 MiB de 8.192 · los 4 slots verificados atendiendo a la vez
tareas    ProjectEval (ACL 2025 Findings / ACM TOSEM), 4 proyectos Django
oráculo   el del banco: inicia el proyecto y lo opera con Selenium
```

## El resultado

```
brazo         aciertos      %      segundos   llamadas   fallos de integración
monolito       17/147     11,6        274,7        12           0/12
secuencial     15/147     10,2        335,7        45           0/12
paralelo       14/147      9,5        233,2        45           0/12

Fisher:  monolito vs secuencial  p = 0,852
         monolito vs paralelo    p = 0,705
         secuencial vs paralelo  p = 1,000
```

**Repartir no cambia la calidad.** Ninguna comparación se acerca a ser
significativa. Lo que cambia es el tiempo: el paralelo tarda **31% menos que el
secuencial** haciendo exactamente las mismas 45 llamadas, y 15% menos que el
monolito haciendo cuatro veces más llamadas. Esa diferencia es puro solapamiento
de los cuatro slots.

La integración no se rompió en ningún brazo: 0 de 12 en los tres. El riesgo que
motivaba el experimento —que dos trabajadores que no se ven discrepen en una
firma o en un id de HTML— no se materializó con 3 a 4 piezas por tarea.

## Dónde se sitúa el modelo

El paper publica sus números (`docs/execution.csv`, Direct-Level1):

| modelo | score |
|---|---:|
| Llama-3.1-7B | 0,0014 |
| Gemma-2-9B | 0,0134 |
| Gemma-3-4B | 0,0148 |
| **K2-Horizon-7B (este)** | **0,0176** |
| Phi-4-14B | 0,0176 |
| GPT-3.5-turbo | 0,0197 |
| Gemini-1.5-pro | 0,0528 |
| GPT-4o | 0,1606 |

**TODAVÍA NO ES COMPARABLE, y conviene no citarlo como si lo fuera.** Ellos
ejecutaron las 20 tareas; aquí se ejecutaron 4, y las más pequeñas. El
denominador del score es 284 casos en los dos, pero nuestras oportunidades reales
son 49. Para ponerlo en la tabla hay que ejecutar el banco completo.

## Tres defectos del instrumento, todos propios

Los tres produjeron números con apariencia de resultado. **La señal que los
delató fue siempre la misma: tres brazos distintos dando un valor idéntico al
decimal.** Cuando tres condiciones distintas empatan exactamente, todas están
chocando contra un techo artificial, y ese techo suele ser el medidor.

**1. `piezas_de` buscaba `pass`.** El esqueleto deja el cuerpo VACÍO, sin `pass`.
Daba cero piezas en 4 de las 16 tareas website y las omitía en silencio.

**2. La estructura de parámetros se le pedía al modelo.** El juez busca los
parámetros por nombre de página y de función; el modelo devolvía algo parecido
pero no igual (un objeto donde iba una lista, `parameter` como diccionario en
vez de lista de pares). Resultado: `Parameter(s) finding was failed` cientos de
veces y los tres brazos con 4/48. La solución no fue insistir con el formato
sino **dejar de pedirlo**: la estructura ya está en el `testcode` del banco y
del modelo solo hacen falta los valores.

**3. Las plantillas no se pedían.** Son cáscaras —`<body>` con UN comentario que
indica qué va dentro— y son 88 de las 91 del banco. Como `piezas_de` solo miraba
`def`/`class`, se copiaban vacías: ningún elemento aparecía en la página y
Selenium no encontraba nada. Con los parámetros ya corregidos el número seguía
en 4/48, y la lectura fácil era *"el 7B no escribe Django funcional, repartir no
cambia nada"*. Parece un hallazgo, es publicable, y es falso: **nadie había
escrito las páginas**.

Incluirlas subió las piezas de 1-5 a 2-19 por tarea y solo entonces el
instrumento empezó a discriminar (4, 5 y 6 aciertos según la ejecución, en vez de
4 siempre).

## Una decisión de diseño que conviene recordar

Los ids de HTML no están en ninguna parte del esqueleto. Sin ayuda, cada
trabajador inventa los suyos y el brazo paralelo pierde **por construcción**, no
por lo que se quiere medir. Se añade al prompt la lista de elementos esperados,
extraída de los NOMBRES y descripciones de los parámetros del `testcode` —que son
especificación, no respuesta: el código de las pruebas NO se pasa— y se da igual
a los tres brazos.

## Qué falta

- **Ejecutar las 20 tareas** para que el número entre en la tabla del paper.
- **Tareas con más piezas.** Con 3-4 la integración no se rompe nunca. Las
  tareas 10, 12, 13 y 20 tienen de 11 a 19 piezas: ahí debería aparecer el costo
  del reparto, si existe.
- **Más repeticiones.** 3 por brazo bastan para descartar una diferencia
  grande, no para medir una pequeña.
