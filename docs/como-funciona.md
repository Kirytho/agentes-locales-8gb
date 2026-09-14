# Cómo funciona el sistema

Esta es una explicación general de qué hace el sistema que se midió en esta
investigación y por qué está construido así. Es deliberadamente conceptual:
describe el funcionamiento, no la implementación.

## El problema que resuelve

Un **agente de programación** es un programa que recibe una solicitud ("agrega
pruebas a este módulo"), decide qué herramientas usar —leer archivos, ejecutar
comandos, editar código— y encadena pasos hasta terminar. Para funcionar necesita
un modelo de lenguaje detrás, y lo habitual es alquilarlo: pagar por cada llamada
a un servicio en la nube.

La pregunta de fondo fue si se puede tener un agente útil **sin pagar un servicio
externo**, con modelos que se ejecutan en una computadora común. La restricción
que ordena todo lo demás es la tarjeta gráfica: **8 GB de memoria**. Ahí deben
caber el modelo y, además, todo lo que el modelo "recuerda" de la conversación en
curso.

## Las tres piezas

```
  agente de programación        decide qué hacer y usa las herramientas
          │
          ▼
  intermediario local           recibe cada solicitud y decide qué modelo la atiende
          │
          ▼
  uno o varios modelos          generan la respuesta, en la computadora o en una GPU remota
```

**El agente** es un programa existente, de código abierto. No se modificó: se
conecta al intermediario como si fuera cualquier servicio compatible con el
formato estándar de la industria.

**El intermediario** es la parte propia. Para el agente es un servicio de modelos
más, así que cualquier agente que use ese formato estándar funciona sin cambios.

**Los modelos** se ejecutan en un servidor de inferencia de código abierto. Pueden
ser uno o varios, en la tarjeta gráfica local o en una GPU gratuita en la nube
conectada mediante un túnel. Cambiar de modelo, o añadir uno, es cuestión de
configuración: no requiere modificar código.

## Qué pasa con cada solicitud

Cuando el agente envía una solicitud, el intermediario la hace pasar por una serie
de pasos cortos, uno tras otro. Cada paso hace una sola cosa y puede dejar pasar
la solicitud o detenerla:

1. **Validar.** Que la solicitud tenga la forma correcta y no contenga material
   peligroso.
2. **Clasificar.** Estimar qué tipo de trabajo es —escribir código, razonar sobre
   un diseño, una respuesta rápida— a partir del texto.
3. **Elegir el modelo.** Según el tipo de trabajo y los recursos disponibles en
   ese momento. Si un modelo no responde o la tarjeta gráfica no tiene margen, la
   solicitud se deriva a otro.
4. **Añadir contexto del proyecto.** Datos que el usuario indicó que se deben
   recordar ("en este equipo los paquetes se instalan de tal forma") y soluciones
   que ya funcionaron antes.
5. **Enviar y devolver.** La respuesta vuelve al agente en el mismo formato,
   incluso cuando llega por partes mientras se genera.

Si algo falla en el camino, el error se informa con su motivo real en lugar de
devolver una respuesta vacía y, cuando tiene sentido, se reintenta con otro
modelo.

Que cada paso sea independiente permite medir, desactivar o reemplazar uno sin
tocar los demás. Buena parte de esta investigación consistió precisamente en eso:
activar y desactivar piezas, y medir qué cambiaba.

## Dos decisiones que surgieron de medir

**Dónde se añade el contexto importa más que qué contexto se añade.** El servidor
de modelos puede reutilizar el cálculo ya hecho sobre el inicio de una solicitud
si ese inicio no cambió desde la solicitud anterior. Un agente reenvía casi toda
la conversación en cada paso, así que eso ahorra la mayor parte del trabajo. En la
primera versión, el contexto del proyecto se añadía al inicio, cambiaba en cada
paso y obligaba a recalcular el 97 % de la solicitud cada vez. Moverlo al final lo
resolvió: medido con un agente real, de 674.208 tokens de entrada solo 187 se
recalcularon sin necesidad.

**Repartir el trabajo entre modelos sirve para ganar tiempo, no calidad.** Se
probaron varias formas de poner a varios modelos a trabajar juntos: uno que
planifica y otro que ejecuta, varios que resuelven lo mismo y uno que elige,
varios que escriben partes distintas. Las que piden al modelo que planifique o que
juzgue dieron peores resultados que consultar a un solo modelo. La que funcionó es
la más simple: dividir la tarea en piezas y asignar una a cada trabajador al mismo
tiempo. Hace el mismo trabajo en menos de la mitad del tiempo, con la misma
calidad.

## Delegar ediciones de código

Además del intermediario, se construyó una herramienta para que un agente
**externo** —uno que usa un modelo potente y de pago— delegue en un modelo local
las ediciones de archivos. El agente describe el cambio y las pruebas que debe
superar; el modelo local lo realiza y lo verifica.

Lo que se aprendió al medirla: el ahorro no está en escribir código (describir un
cambio cuesta casi lo mismo que hacerlo), sino en **no tener que leer el
archivo**. Por eso solo conviene para modificar archivos que ya existen, no para
escribir código nuevo.

## Qué no hace

- **No vuelve más inteligente al modelo.** Elige a cuál consultar y le da mejor
  contexto; la calidad de la respuesta sigue siendo la del modelo.
- **No evita el límite de la tarjeta gráfica.** Lo que más restringe no es la
  velocidad, sino cuánta conversación cabe en memoria a la vez.
- **No reemplaza la verificación.** Los modelos pequeños a veces entregan
  resultados con forma perfecta y contenido inventado. Por eso todas las
  mediciones de este repositorio comprueban el resultado —ejecutando el código,
  comparando archivos, usando la aplicación— en lugar de confiar en lo que el
  modelo dice que hizo.
