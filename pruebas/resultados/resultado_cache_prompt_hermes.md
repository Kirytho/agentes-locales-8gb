# Caché de prompt con Hermes: el intermediario no la rompe (13/09/2026)

Disparado por un video sobre LMCache ("¿La capa de CACHÉ que hace que los agentes
de IA sean 10 VECES más rápidos?", Cognix). Su tesis: un agente de código reenvía
casi todo el contexto en cada turno, y si algo cambia al principio del mensaje, la
GPU recalcula todo.

LMCache es para vLLM/SGLang, no aplica. Pero llama.cpp ya incluye la versión pequeña,
activa por defecto: `--cache-prompt`, `--cache-ram 8192` (caché de prompts en RAM)
y selección de slot por prefijo común (`selected slot by LCP similarity`).

La duda concreta: el intermediario añade la memoria "esencial" al mensaje del usuario, que en
una sesión agéntica está justo después del prompt de ~21.000 tokens. Si cambiara
entre vueltas, cada llamada a herramienta recalcularía todo el historial.

## Instrumento

`herramientas/leer_cache_prompt.py` lee el log de llama-server: por solicitud,
tokens entrantes, prefijo en común con lo cacheado y tokens recalculados.
**Desperdicio** = recalculados − (entrantes − en común): lo que se recalculó
aunque ya estaba en caché. Verificado contra dos solicitudes directas cuyo
`cached_tokens` devolvió el propio servidor (2.817/0 y 12/2.805).

## Resultado: Hermes → intermediario → Ornith-1.5-9B IQ4_XS @ 98.304, escenario `contexto`

```
14 solicitudes · 674.208 tokens entrantes · 87.157 recalculados (12,9%)
DESPERDICIO: 187 tokens = 0,03%
```

Todo lo recalculado es contenido genuinamente nuevo: los archivos que el agente
lee (vueltas de 11.000-20.000 tokens). El prefijo --prompt de sistema,
herramientas, memoria esencial e historial-- se reusa entero en cada vuelta.
**El intermediario no rompe la caché.*** El arreglo del 18/08 (memoria al final, cuando al
principio hacía recalcular el 97%) sigue funcionando.

Estimación del ahorro, a la tasa de prellenado observada (1.360 tok/s): sin
caché serían ~496 s de prellenado contra 64 s reales, **unas 7,7 veces**. Es
optimista para el caso sin caché: el prellenado se vuelve más lento con contexto
largo, así que el ahorro real es mayor.

## Detalle de arquitectura que importa

Ornith (qwen35, con capas recurrentes) no reusa hasta el último token común sino
hasta el último **punto de control** guardado (`restored context checkpoint`).
Los puntos de control se crean cerca del final de cada prompt. Si un mensaje
cambiara en la parte intermedia, lejos de todo punto de control, recalcularía desde cero
aunque el 99% coincida. Por eso importa más en este modelo que en uno denso
mantener estable todo lo anterior al final.

## Lo que no se pudo medir

El control sin intermediario (Hermes → llama-server directo) no se inicia: Hermes detecta
mal el contexto del servidor sin intermediario (`Context length exceeded (108 tokens)`) y
aborta. No hizo falta, porque el desperdicio se mide contra el ideal y no contra
ese control.

## Pendiente

`--cache-ram 8192` llenó 8 GB de RAM durante el banco de reparto, donde cada
solicitud es distinta y no hay prefijo que reusar (el log mostraba entradas
desalojándose sin parar). Para bancos así, conviene iniciar con `--cache-ram` bajo.
