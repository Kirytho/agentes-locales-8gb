# Repartir piezas distintas de una tarea sí funciona (22/08/2026)

**Pregunta:** en vez de poner varios agentes sobre la misma tarea (ver
[misma tarea](resultado_misma_tarea.md)), ¿sirve dividir una tarea en **piezas
independientes** y darle una a cada agente en paralelo?

**Modelo:** gemma-4-E4B en GPU, temperatura 0,1.
**Bancos:** `pruebas/calidad/banco_compuesto.py` (4 tareas de 4 piezas) y
`banco_compuesto_grande.py` (2 tareas de 10 y 12 piezas). Cada tarea tiene pruebas
**por pieza** y una prueba de **integración** que solo pasa si las interfaces
coinciden. Ambos bancos se validaron contra implementaciones de referencia con
`pruebas/instrumentos/validar_banco_compuesto.py`.
**Corredores:** `medir_reparto_piezas.py`, `medir_plan_propio.py` y
`medir_plan_roto.py`.

## 1. Tres formas de escribir 4 piezas (5 repeticiones, 20 ejecuciones por modo)

| modo | piezas | integración | tiempo total | tokens |
|---|---:|---:|---:|---:|
| **paralelo** (4 a la vez, cada uno ve solo su pieza) | **80/80** | **20/20** | **92,0 s** | **11.417** |
| secuencial (4 en fila, cada uno ve lo ya escrito) | 80/80 | 20/20 | 193,9 s | 12.754 |
| monolito (una llamada escribe las 4) | 76/80 | 20/20 | 310,2 s | 22.808 |

**Cero fallos de integración en 60 ejecuciones.** La preocupación de diseño —que
un agente devuelva un diccionario donde otro espera una tupla— no apareció ni una
vez. El paralelo gana en los tres ejes: 3,4× más rápido que el monolito, la mitad
de tokens y mejores piezas.

**El monolito degrada las piezas.** Sus 4 fallos son la misma función,
`texto.normalizar`, 4 de 5 veces: pasa a minúsculas pero no quita la coma. Pedida
sola, sale bien 5/5 en los otros dos modos. Escribir 4 funciones en una respuesta
reparte la atención y una sale a medias.

**Crudos:** `resultado_reparto_piezas_r1.json`.

## 2. Con 10 y 12 piezas la integración sigue intacta

Cortar más fino importa por una razón medida: con 9 o más solicitudes
simultáneas, llama.cpp cambia a kernels mucho más eficientes (ver
[escalado](resultado_escalado_capacidad.md)). No estaba dicho que 10-12 agentes
que no se ven entre sí produjeran piezas que encajen. 5 repeticiones, servidor con
16 slots:

| modo | piezas | integración | s/tarea | tokens/tarea |
|---|---:|---:|---:|---:|
| **paralelo** | **110/110** | **10/10** | **8,5** | 1.049 |
| secuencial | 110/110 | 10/10 | 17,1 | 844 |
| monolito | 110/110 | 10/10 | 24,5 | 1.586 |

Por función, el reparto fino rinde mejor:

| tarea | piezas | s/tarea | **s/función** | vs monolito |
|---|---:|---:|---:|---:|
| banco de 4 piezas | 4 | 4,6 | **1,15** | 3,37× |
| biblioteca | 10 | 6,6 | **0,66** | 3,55× |
| notas | 12 | 10,3 | **0,86** | 2,47× |

Salvedades:

- **Los tokens medidos son solo de salida.** El contexto del módulo se repite en
  la solicitud de cada agente (12 veces con 12 piezas) y no aparece en esa
  columna; sí está dentro del tiempo total.
- **Que 12 rinda peor que 10 puede no ser por granularidad:** `notas` tiene
  funciones más complejas que `biblioteca`. Con dos tareas no se separan los dos
  efectos. La lectura correcta es "10 y 12 son mejores que 4".

**Crudos:** `resultado_reparto_piezas_grande.json`.

## 3. Con el plan que escribe el propio modelo

Las mediciones anteriores usaban especificaciones de pieza escritas a mano: son
el techo. En uso real, el plan lo escribe el modelo. Mismas tareas y pruebas, 5
repeticiones:

| | piezas | integración | s/tarea | tokens/tarea | planes ilegibles | nombres cambiados |
|---|---:|---:|---:|---:|---:|---:|
| plan a mano | 80/80 | 20/20 | 5,1 | 616 | — | — |
| **plan del modelo** | **75/80** | **20/20** | 13,8 | 1.258 | **0/20** | **0/20** |

El modelo devolvió JSON válido las 20 veces, respetó los nombres de función del
enunciado las 20 veces, y las piezas encajaron las 20 veces.

**La única pérdida es otra vez `texto.normalizar`, 5/5.** El enunciado pide quitar
`.,;:!?` (seis signos) y el código enumera cinco: dentro de esa lista, la coma se
lee como separador y no como elemento. Con la especificación a mano sale bien 5/5;
con la del modelo, que dice lo mismo reformulado, falla 5/5. No es un problema de
interfaces ni de reparto: es un detalle de transcripción que sobrevive a la
reformulación.

**El plan cuesta tiempo en serie:** los ~9 s de diferencia son la planificación,
y los agentes no empiezan hasta tenerla. Con 4 funciones pequeñas, planificar
cuesta más que ejecutarlas todas. Se amortiza solo si la parte paralela es grande
o si el plan se reutiliza.

**Crudos:** `resultado_plan_propio_r1.json`.

## 4. Los errores del plan se propagan al código

Si uno revisa el plan antes de dejar que se escriba código, ¿ese hábito sirve? Solo
si los errores del plan llegan al código. 12 piezas con un defecto inyectado a
mano en su especificación, 3 repeticiones:

```
plan sano   35/36   97,2%
plan roto    9/36   25,0%

de las 35 piezas que salían bien con el plan sano:
  el defecto SE PROPAGÓ al código   26   74,3%
  el programador lo ABSORBIÓ          9   25,7%
```

| clase de defecto | ejemplo | se propaga |
|---|---|---:|
| **tipo de dato** | "devuelve una TUPLA" donde el enunciado decía diccionario | **11/11 · 100%** |
| **orden** | "ordenada DESCENDENTE" donde decía ascendente | **9/9 · 100%** |
| caso borde omitido | quitar "si queda en 0, elimina el producto" | 6/15 · 40% |

**Cuando el plan contradice al enunciado, gana el plan, siempre**, aunque el
enunciado completo también está en la solicitud. **Cuando el plan omite algo, el
contexto lo corrige el 60% de las veces.**

Regla práctica: al revisar un plan, prestar atención a sus **afirmaciones** (tipos
de dato, estructuras, criterios de orden), más que a sus omisiones.

**Límite:** el fallo de `texto.normalizar` ocurrió con un plan correcto. Revisar
el plan no detecta esa clase de error; para eso hacen falta pruebas.

**Crudos:** `resultado_plan_roto_r1.json`.

## Salvedades generales

- **La prueba de integración de `texto` es más débil que la unitaria:** su texto
  no tiene comas, así que el defecto de `normalizar` no se activa ahí. Los 20/20
  de integración del monolito y del plan del modelo son generosos por eso.
- **Las tareas son pequeñas:** funciones en un mismo archivo. En trabajo real las
  piezas son archivos distintos con dependencias más largas; no se extrapola solo.

## Qué queda establecido

| forma de usar varios agentes | medición | veredicto |
|---|---|---|
| varios sobre la MISMA tarea | ver [misma tarea](resultado_misma_tarea.md) | descartado |
| PIEZAS distintas, plan a mano | 20/20 integración · 3,4× más rápido | sirve |
| PIEZAS distintas, plan del modelo | 20/20 integración · 0 planes rotos | sirve |
| 10-12 piezas en paralelo | 10/10 integración · mejor rendimiento por función | sirve |

Bajo un harness agéntico, en cambio, este reparto interno no llega a activarse:
todas las solicitudes llegan con herramientas y streaming (ver
[el backend en Kaggle](../../kaggle/README.md)). La versión que se midió bajo un harness es
repartir entre los slots de `--parallel` (ver
[reparto de proyecto](resultado_reparto_proyecto.md)).
