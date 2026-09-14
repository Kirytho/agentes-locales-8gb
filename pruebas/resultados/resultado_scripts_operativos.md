# Scripts operativos: el modelo calcula bien y falla al relatar (24-25/08/2026)

**Pregunta:** ¿el modelo escribe bien un **script operativo** (recorrer archivos,
filtrar, acumular) y no solo una función aislada?

**Banco:** `pruebas/calidad/eval_scripts.py`. Cuatro tareas que exigen un script
real sobre un directorio de trabajo:

- `cadena_enlazada`: seguir punteros entre archivos, en un orden distinto del
  alfabético;
- `dir_mas_profundo`: recorrer un árbol y comparar profundidades;
- `suma_con_dos_filtros`: filtrar por dos condiciones y acumular;
- `archivo_con_mas_lineas`: leer varios archivos, ordenar y obtener un dato.

**Oráculo:** la respuesta correcta se calcula aparte con un script independiente,
y se compara con lo que imprime el script del modelo.
**Crudos:** `resultado_scripts_*.json`.

## Cómo empezó: una conclusión equivocada

El 24/08, a través de Hermes, gemma-4-E4B resolvía la cadena de 15 archivos
enlazados solo **7 de 12** veces. La primera lectura fue que "escribe mal la mitad
de los scripts de ~30 líneas". Se construyó este banco para medirlo antes de
descargar un modelo menos cuantizado.

## Resultado por un camino limpio

| condición | aciertos |
|---|---:|
| gemma-4-E4B Q4_K_M, sin prompt de sistema | **12/12** |
| la misma, con el prompt de sistema de Hermes (25.679 caracteres) | **12/12** |
| la cadena de 15 nodos exacta del 24/08, 5 ejecuciones | **5/5** |

**17/17 por el camino limpio contra 7/12 por Hermes** (Fisher p = 0,0067). Mismo
modelo, misma tarea, misma respuesta esperada.

## Cinco causas descartadas, una parcial

| hipótesis | prueba | resultado |
|---|---|---|
| cantidad de herramientas (Hermes ofrece 21) | 1 contra 18 herramientas | 6/6 y 6/6 |
| el envoltorio JSON del resultado de la herramienta | salida cruda contra JSON | 6/6 y 6/6 |
| el directorio de trabajo | directorio de la tarea contra el del usuario | 6/6 y 6/6 |
| el prompt de sistema largo | con y sin él | 12/12 y 12/12 |
| la temperatura (Hermes usa 0,7; el banco 0,1) | 0,1 contra 0,7 | 6/6 y 6/6 |

**Parcial: el largo de la ruta.** Por Hermes, con una ruta de 91 caracteres que
contenía un UUID, acertó 1/6; con una ruta corta, 3/6. En el código generado se
ve el mecanismo: el modelo **perdió el último componente de la ruta al copiarla**,
el script no encontró el archivo y todo lo demás falló.

## La causa real: cambiar solo el oráculo

Con opencode la misma tarea dio 0/6, pero el script que escribía era correcto. En
los eventos crudos se veía que, después de ejecutar la herramienta, el modelo
**respondía repitiendo el comando** en vez de su salida.

Se repitieron las mismas ejecuciones cambiando únicamente qué mira el oráculo:

| qué mira el oráculo | resultado |
|---|---|
| lo que **imprime el script** | 6/6 · 6/6 · 12/12 · 17/17 · 12/12 → ~100% |
| lo que el **modelo dice** al final | 3/6 · 5/6 · 9/12 → ~67-75% |

Guardado en el banco como dos vistas sobre las mismas tareas
(`resultado_scripts_vista-script.json` y `_vista-prosa.json`):

```
vista-script: 12/12 = 100%
vista-prosa :  9/12 =  75%
```

**Esa es toda la brecha.** El modelo calcula bien casi siempre y **relata mal el
resultado una de cada tres o cuatro veces**. No es escribir código, ni razonar, ni
el contexto, ni el harness: es el último paso.

## Por qué solo se veía con Hermes

Toda la investigación inicial usó `hermes -z`, el modo de una sola pasada que
imprime **solo** el texto final del modelo, sin la salida de las herramientas. En
uso interactivo la salida cruda sí se muestra y el mal relato es una molestia, no
una pérdida de información.

**Regla que queda:** no medir con un modo que solo devuelve el resumen del
modelo. El oráculo tiene que mirar la salida de la herramienta, o la tarea tiene
que escribir el resultado en un archivo que se lee aparte.

## Uso posterior: criba de cuantizaciones de K2-Horizon-7B (07-08/09)

El mismo banco se usó como detector rápido de modelos rotos, con **una sola
ejecución por cuantización** (4 tareas):

| grupo | resultado |
|---|---|
| i-quants de 3 bits o menos (`IQ1_*`, `IQ2_*`, `IQ3_*`) y `Q1_0`, `Q2_0` | **0/4** en las 12 |
| `IQ4_NL`, `IQ4_XS` | 3/4 |
| K-quants de 2 a 5 bits (`Q2_K` … `Q5_K_M`) y `Q4_0`/`Q4_1`/`Q5_0`/`Q5_1` | entre 2/4 y 4/4 |

Con una ejecución por cuantización, las diferencias entre 2/4 y 4/4 son ruido. Lo
único que se lee es la separación entre "no produce nada utilizable" (0/4) y "sí
produce". El modelo elegido después (K2-Horizon-7B-Q4_K_S) salió de un barrido
más completo (ver [Ornith o K2](resultado_modelo_codigo_09-09.md)).
