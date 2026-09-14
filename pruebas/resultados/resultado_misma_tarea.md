# Varios agentes sobre la misma tarea no mejoran el resultado (19-22/08/2026)

**Pregunta:** si sobra capacidad para varios agentes, ¿conviene ponerlos a
trabajar **sobre la misma tarea**, planificando, eligiendo o verificando entre
ellos?

**Modelo principal de estas mediciones:** gemma-4-E4B en GPU (salvo donde se
indica).
**Tareas:** las 53 funciones de la batería (`eval_expertos.py`), con sus pruebas
como verdad. Ningún modelo opina sobre si el código es correcto.

Se probaron cinco formas. Todas tienen resultado negativo o neutro.

## 1. Planificar antes de programar (`medir_pipeline.py`, 19/08)

Dos llamadas (plan en prosa y después código guiado por el plan) contra una sola
llamada directa. 12 tareas, mismo backend de GPU (Qwen3.8-9B).

| | pruebas | por tarea | tokens |
|---|---:|---:|---:|
| **directo** | **12/12** | **8,8 s** | 5.430 |
| plan + código | 9/12 | 36,0 s | 22.413 |

4,1× el tiempo y los tokens, con peor resultado. Los fallos no son de sintaxis
sino de sobreingeniería: el plan pedía "manejo de errores, código de producción"
y el código resultante rompía el contrato exacto pedido.
**Crudos:** `resultado_pipeline.json`.

Salvedad del banco: la primera ejecución dio 3/12 y era falso. El tope de 900
tokens cortaba el código a la mitad y los `SyntaxError` eran truncamiento. Ahora
el banco avisa cuando una respuesta termina por límite de longitud.

## 2. Separar planificador y programador (`medir_agentes_separados.py`, 22/08)

53 tareas, temperatura 0,1, tope 2.048 tokens, dos ejecuciones completas.

| modo | qué hace | r1 | r2 | s/tarea | tokens/tarea |
|---|---|---:|---:|---:|---:|
| agentes | plan corto en prosa + instrucción de programador | 52/53 | 51/53 | 8,0 | 561 |
| solo rol | una llamada, solo instrucción de programador | — | 50/53 | **3,5** | **258** |
| directo | una llamada, sin instrucciones | 48/53 | 50/53 | 15,5 | 1.121 |
| pipeline | los prompts de planificar y ejecutar que tenía el intermediario | 42/53 | 38/53 | 33,5 | 2.417 |

McNemar sobre las 53 tareas pareadas (r2):

```
agentes  vs solo rol   p = 1,000
agentes  vs directo    p = 1,000
solo rol vs directo    p = 1,000
directo  vs pipeline   14 contra 2   p = 0,004
```

**Planificar no aporta.** Agentes 51 contra solo rol 50, pagando el doble de
tiempo y tokens por el plan.

**El pipeline anterior era malo por su prompt, no por dividir en dos etapas.** Su
instrucción de ejecución pedía "código listo para producción, manejo de errores
en cada operación", y el modelo entregaba una aplicación en vez de una función:
emojis dentro del código, `input()` donde no correspondía, y 8-9 respuestas
truncadas por ejecución. Las mediciones anteriores del pipeline (12/12 → 9/12
arriba, y las de [atomic](resultado_atomic_ai.md)) usaban ese mismo prompt:
**midieron el prompt, no la arquitectura.**

**Una corrección del mismo día.** La instrucción de programador parecía 4,4× más
barata que "directo". Pero "directo" no lleva ninguna instrucción de sistema, y
el intermediario ya añadía una de brevedad a todas las solicitudes. Medido contra
esa condición real:

| modo | aciertos | tiempo | tokens |
|---|---:|---:|---:|
| **brevedad** (lo que ya se usaba) | **50/53** | **109,8 s** | **7.985** |
| solo rol | 50/53 | 179,2 s | 13.214 |
| directo | 50/53 | 783,7 s | 58.431 |

Mismo acierto en los tres (McNemar p = 1,000). La configuración que ya existía era
la más barata. **Lección:** antes de proponer un cambio, medir el estado actual
como una condición más, no compararlo contra "nada".

**Crudos:** `resultado_agentes_separados_r1.json`, `_r2.json`. La ejecución con
la condición de brevedad quedó en un registro local que no se incluye.

## 3. Mejor de N (`medir_mejor_de_n.py`, 20/08)

Los N agentes resuelven la misma tarea y se queda la que pasa las pruebas. Es un
**techo**: usa las pruebas como juez perfecto, que en uso real no se tiene.

| | gemma-4-E4B |
|---|---:|
| un intento (temperatura 0,7) | 18,2/53 |
| al menos uno de 4 (temperatura 0,7) | 23/53 |
| batería normal (temperatura 0,1) | **51,4/53** |

**Falla por un motivo propio:** la temperatura necesaria para que los intentos
difieran destruye la calidad. Pasar de 0,1 a 0,7 costó 33 puntos, y cuatro
intentos recuperaron 4,8. Pérdida neta. 30 tareas fallan siempre, 11 aciertan
siempre y solo 12 dependen del intento.
**Crudos:** `resultado_mejor_de_4.json`.

**Medición dudosa, no usada:** hay una segunda ejecución que busca diversidad
cambiando la redacción de la solicitud a temperatura 0,1
(`resultado_mejor_de_4_prompt.json`). Informa 52/53 con al menos un acierto, pero
también 20,8/53 por intento y **ninguna tarea con los 4 aciertos**, cuando la
misma batería a esa temperatura da ~51/53. Esos números no son coherentes entre
sí; lo más probable es un defecto del instrumento en esa ejecución. No se extrajo
ninguna conclusión de ella.

## 4. Un agente que elige la mejor respuesta (`medir_juez.py`, 20/08)

3 candidatas por tarea a temperatura 0,6. Se ejecutan las pruebas para saber la
verdad y se conservan solo las tareas **mixtas** (alguna pasa y alguna falla), las
únicas donde elegir cambia algo. Se le pide al modelo que elija sin decirle cuál
pasa.

| | |
|---|---:|
| tareas donde elegir importa | 14 de 53 |
| el juez acierta | 7/14 = **50%** |
| elegir al azar | 43% |
| elegir siempre la primera | 36% |

**No sabe elegir:** +7 puntos sobre el azar, una tarea. Y en **39 de 53 tareas**
las tres candidatas eran igual de buenas o igual de malas: tener tres agentes no
cambió nada.
**Crudos:** `resultado_juez.json`.

## 5. Un agente que escribe pruebas para elegir (`medir_tests_generados.py`, 22/08)

La alternativa a un juez que opina es uno que **ejecuta pruebas**. Eso depende de
que el modelo escriba pruebas utilizables. 3 candidatas por tarea a temperatura
0,8 (alta a propósito, para forzar fallos).

```
159 candidatas: 151 buenas y 8 malas según la batería

falsas alarmas    50/151   33,1%   rechaza código correcto
escapes            2/8     25,0%   acepta código incorrecto

eligiendo con las pruebas del modelo : 1/5
quedándose con la primera            : 3/5
```

**Un tercio de las implementaciones correctas son rechazadas.** Tres mecanismos:

- **Inventa otro nombre de función:** el enunciado pide `desde_romano` y la prueba
  llama a `from_romano`.
- **No sabe escribir un assert:** `assert mayor_racha([1, 1, 2, 2, 2], (2, 1))`
  pasa el valor esperado como segundo argumento, y además es incorrecto.
- **Inventa requisitos:** exige manejo de siglas que el enunciado no pide.

Un rescate parcial funciona: si las pruebas rechazan **todas** las candidatas,
sospechar de las pruebas. Pasó en 16 tareas y en las 16 había una candidata
buena; las falsas alarmas bajan a 5,6%. Pero no salva la idea: con 95% de
candidatas buenas, **solo en 5 de 53 tareas** hay algo que elegir.
**Crudos:** `resultado_tests_generados_r1.json`.

## Qué queda establecido

| forma de usar varios agentes | medición | veredicto |
|---|---|---|
| planificar y después programar | 51 contra 50, p = 1,000, al doble de costo | no aporta |
| mejor de N por temperatura | −33 puntos por calidad, +4,8 por intentos | pierde |
| un agente elige opinando | 50% contra 43% del azar | al nivel del azar |
| un agente elige con pruebas propias | 1/5 contra 3/5 sin elegir | peor que no elegir |
| los N aportan variedad | 5/53 tareas con candidatas distintas | casi no hay qué elegir |

Con este modelo y tareas de este tamaño, **el modelo es consistente consigo
mismo**: no hay dispersión que explotar. La forma de usar varios agentes que sí
funcionó fue **repartir piezas distintas** de una tarea (ver
[reparto de piezas](resultado_reparto_piezas.md)).
