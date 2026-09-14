# Delegar ediciones a un modelo local: el ahorro está en no leer (08-09/09/2026)

**Pregunta:** si un agente con un modelo potente y de pago le pasa trabajo de
código a un modelo local mediante un servidor MCP, ¿ahorra tokens del modelo
caro?

**Cómo funciona la herramienta:** el agente describe el cambio y las pruebas que
debe superar. El servidor le pide el código al modelo local, **ejecuta** las
pruebas y devuelve solo el veredicto ("pasó" o "falló con este error").

**Bancos:** `pruebas/calidad/eval_edicion.py`, `eval_formato_edicion.py` y
`eval_techo_archivo.py`; contabilidad con `herramientas/contabilidad_mcp.py`.
**Crudos:** `resultado_edicion_*.json`, `resultado_formato_*.json` y
`resultado_techo_*.json`. Las mediciones de ahorro se hicieron sobre un proyecto
de ejemplo y quedaron en registros locales.

## 1. Escribir código nuevo delegando pierde tokens

La pregunta "¿esto ahorra?" se respondió cuatro veces con cuatro números
distintos (0,1×, 0,2×, 4,2× y 0,8×), según el tipo de trabajo. La diferencia está
en si hay que leer un archivo o no:

| trabajo | delegando | haciéndolo el agente | resultado |
|---|---:|---:|---|
| construir un proyecto pequeño de ejemplo | 2.331 tokens | 254 tokens de código | **pierde ~9×** (0,1×) |
| construir un módulo desde cero | 5.401 | 1.194 | **pierde 4,5×** |
| editar ese mismo módulo sin leerlo | 334 | 1.408 | **gana 4,2×** |

**Describir una función de 4 líneas cuesta más que escribirla.** Al construir no
hay nada que ahorrar: el agente tampoco tendría que leer nada, solo escribir. Al
editar, en cambio, el agente evita **leer el archivo**, y ese es todo el ahorro.
La ventaja crece con el tamaño del archivo, porque la solicitud cuesta siempre lo
mismo (~334 tokens).

## 2. Por qué la herramienta recibe rutas y no contenido

La primera versión recibía el contenido de los archivos y devolvía los archivos
completos. El agente pagaba el archivo **tres veces**:

```
archivo de 300 líneas (~3.000 tokens)

  enviando contenido     leer 3.000 + enviar 3.000 + recibir 3.000 + solicitud 150 = 9.150
  editando el agente     leer 3.000 + cambio 60                                 = 3.060
  enviando rutas         solicitud 150 + veredicto 50                           =   200
```

Con rutas, el servidor lee y escribe por su cuenta y devuelve el veredicto, nunca
el archivo. Eso solo es defendible porque el servidor **ejecuta pruebas de
regresión**: no hace falta leer el resultado para saber si rompió algo.

## 3. Las pruebas de regresión son obligatorias

`eval_edicion.py` mide 13 cambios sobre código existente, cada uno con pruebas
del cambio y pruebas de lo que ya funcionaba. Detectó que el modelo **a veces
devuelve el archivo sin funciones que estaban**: hace el cambio pedido y borra
código que funcionaba. Las pruebas del cambio pasan igual, así que la pérdida no
se nota. Solo la regresión la detecta.

La regresión puede ser un comando: pasar la batería de pruebas existente del
proyecto (298 pruebas en el caso medido) en lugar de tres asserts improvisados
bajó la solicitud de ~490 a ~340 tokens y cubrió muchísimo más.

## 4. Formato: bloques SEARCH/REPLACE primero, archivo entero si fallan

Medido con `eval_formato_edicion.py` sobre las 13 tareas, 5 repeticiones por
formato alternando el orden:

| formato | formato válido | se aplica | PASA | rompió regresión | generado | tiempo |
|---|---:|---:|---:|---:|---:|---:|
| archivo entero | 65/65 | 65/65 | 62/65 | 1 | 2.651 caracteres | 22 s |
| bloques | 62/65 | 60/65 | 56/65 | 3 | 395 caracteres | 10 s |

Fisher p = 0,127. Los bloques generan 6,7× menos y tardan 2,2× menos, con algo
menos de acierto (86% contra 95%). **Su riesgo propio es el cambio a medias:** en
un renombre, el modelo emite bloques para algunas apariciones y no para todas.
Reescribir el archivo entero es atómico.

Por eso el servidor empieza por bloques y, ante cualquier fallo, reintenta con el
archivo entero. El reintento lento se paga solo cuando ya falló (~14% de las
veces). La comparación entre modelos está en
[Ornith o K2](resultado_modelo_codigo_09-09.md).

## 5. El techo de tamaño de archivo

Los dos formatos tienen límites distintos, por causas distintas:

| formato | techo | lo limita |
|---|---|---|
| bloques | ~28.000 caracteres (~1.470 líneas) | el contexto: el archivo cabe una vez |
| archivo entero | ~12.000 caracteres (~630 líneas) | el máximo de tokens de salida: la respuesta **es** el archivo |

Medido con `eval_techo_archivo.py` sobre Ornith a contexto 16.384
(`resultado_techo_*.json`):

| caracteres | líneas | resultado |
|---:|---:|---|
| 10.033 – 40.019 | 548 – 2.143 | 3/3 en cada tamaño, 12-16 s |
| 44.061 – 60.041 | 2.358 – 3.208 | HTTP 400: no cabe en el contexto |

**Cuidado con cómo se mide.** Esos 40.019 caracteres se midieron contra el
servidor del modelo directamente. A través del intermediario, que añade su propio
prompt de sistema, el límite real fue menor: 32.029 caracteres pasan y 35.037
devuelven `Context size has been exceeded`. Medir contra el backend daba un 25%
de más. El techo de 28.000 deja ~4.000 caracteres de margen para el texto del
cambio.

Pasado el techo, el servidor **se niega antes de gastar la llamada**: truncar en
silencio devolvería el archivo mutilado.

## 6. Cuando falla dos veces igual, el problema es la solicitud

Construyendo un segundo proyecto de ejemplo: de 10 llamadas fallaron 4, y **3 de
esas 4 fueron culpa de la solicitud, no del modelo**. Un parámetro se llamaba `hoy` y
un contador también; el modelo escribía `hoy = 0` y pisaba el parámetro. Subir el
número de intentos nunca lo arregló: da el mismo error otra vez.

Tres reglas para escribir la solicitud, cada una de un fallo medido:

1. **Nombrar el mecanismo, no el síntoma.** "Si el punto está en la posición 0"
   funciona; "como `.gitignore`" no.
2. **Si se espera un diccionario, decir cuántas claves exactas lleva.**
3. **Ningún parámetro puede llamarse igual que una clave o un contador de
   la solicitud.**

El servidor ahora numera las comprobaciones que fallan, se detiene cuando el
mismo error se repite y muestra el diff de lo que intentó escribir.

## Qué queda establecido

- Delegar conviene para **modificar archivos que ya existen**, no para escribir
  código nuevo.
- Sin pruebas de regresión ejecutadas por el servidor, delegar no es seguro: el
  modelo a veces borra código que funcionaba sin que las pruebas del cambio lo
  noten.
- La contabilidad se informa como un rango: incluir o no las pruebas del cambio
  del lado "a mano" depende de si uno las habría escrito igual.

**Límite:** todo lo medido son casos del banco y proyectos de ejemplo, más cortos
y menos ambiguos que el trabajo real.
