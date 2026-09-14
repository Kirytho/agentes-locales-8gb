# Prueba end-to-end en Linux/CachyOS — 2026-07-27

Primera prueba real (no simulada) del sistema completo ejecutándose de forma
nativa en Linux: backend compilado (`backends/linux/bin/llama-server`, ver
`backends/linux/README-linux-build.md`) + intermediario en Python + un modelo
real descargado por el usuario.

**Modelo**: `nanbeige4.2-3b-Q4_K_M.gguf` (2,57 GB, no es uno de los modelos de
producción de ese momento — se usó por ser pequeño y rápido de probar).
**GPU**: RTX 3060 Ti, backend principal (puerto 8080), cache-type `turbo3`
(mapeo del tipo de caché del fork verificado: el log muestra `TCQ1 decode:
K/V codebooks... baked-in`, `kv_bpv: 3.5` en las respuestas).

> **Nota metodológica**: esta ejecución no llegó a guardarse en las estadísticas
> del intermediario porque el perfilador solo guarda en disco cada 10
> solicitudes, y aquí se enviaron ~4 en total antes de detener el servidor a
> propósito; tampoco hay un guardado al apagar. Los números de abajo se
> reconstruyeron a mano desde el log de depuración, el historial y los
> `timings` que devuelve cada respuesta — reales, no inventados, pero de una
> muestra pequeña (no es un benchmark).

## Velocidad (del propio llama-server, campo `timings`)

| Prueba | prompt tok/s | generación tok/s | kv_bpv |
|---|---:|---:|---:|
| Backend directo (`curl :8080`, 58 prompt / 60 compl. tokens) | 193,8 | 62,1 | 3,5 |
| Vía intermediario, solicitud #1 (65 prompt / 3 compl. tokens — respuesta corta "Modelo") | 282,1 | 79,2 (muestra pequeña, poco confiable) | 3,5 |
| Vía intermediario, solicitud #2 (misma pregunta) | — | — | — (acierto de caché, 0 tokens reales) |

La generación vía intermediario en la solicitud #1 midió más rápido que el
backend directo porque generó solo 3 tokens (el inicio y la parada dominan la
medición) — no es una comparación válida de throughput; hace falta una
respuesta más larga para un número confiable.

## Desglose por paso del intermediario (log de depuración)

**Solicitud #1 (arranque en frío del modelo de embeddings):**

| Paso | Duración |
|---|---:|
| clasificar | 0,004s |
| elegir backend | 0,000s |
| verificar VRAM | 0,000s |
| validar seguridad | 0,000s |
| control de plan | 0,000s |
| **añadir memoria** | **15,656s** |
| construir la solicitud | 0,000s |
| **TOTAL de pasos** | **15,660s** |
| Respuesta del backend | 15,95s (incluye lo anterior) |

Los 15,6s son casi por completo la primera carga de `sentence-transformers`
(carga diferida: ocurre la primera vez que el paso de memoria calcula un
embedding). La inferencia real del LLM en esta solicitud fue de apenas ~0,3s
(15,95 − 15,66).

**Solicitud #2 (modelo de embeddings ya cargado):**

| Paso | Duración |
|---|---:|
| clasificar | 0,000s |
| elegir backend | 0,000s |
| verificar VRAM | 0,035s |
| validar seguridad | 0,000s |
| control de plan | 0,000s |
| añadir memoria | 0,030s |
| construir la solicitud | 0,000s |
| **TOTAL de pasos** | **0,065s** |

240x más rápido que la solicitud #1 — confirma que el costo real es el
arranque en frío del modelo de embeddings, no los pasos en sí (que ya eran de
menos de un milisegundo en casi todos los casos, incluso en frío).

## Memoria y caché (validación de la corrección de la sesión anterior)

- Solicitud #1: fallo de caché → la caché semántica pasó de 0 a 1 entrada.
- Solicitud #2 (misma pregunta): acierto exacto de caché (`similarity: 1.0`),
  0 tokens gastados, respuesta instantánea.
- `session_id=2da4f768e8fa`: 4 entradas en memoria de sesión para 2 turnos =
  exactamente 1 mensaje de usuario + 1 de asistente por turno, sin
  duplicados — confirma que la corrección del guardado de turnos funciona con
  tráfico real.

## Qué falta para un informe completo

Esto fue una prueba de humo (~4 solicitudes), no un benchmark. Para un informe
comparable a `resultado_gpu_pequenos.md` o `resultado_supervisor.md` (que sí
tienen métricas agregadas y varias ejecuciones), faltaría:

1. Enviar varias decenas de solicitudes para que el perfilador llegue al umbral
   de guardado automático (o añadir un guardado forzado al apagar, que hoy no
   existe).
2. Usar uno de los scripts ya existentes en `pruebas/` (p. ej. `medir_gpu.py` o
   el patrón de `resumen_bateria.py`) para generar un informe agregado en vez
   de leer el log de depuración a mano.
3. Probar con los modelos de producción reales (Qwythos-9B / GLM-23B) en vez
   del modelo pequeño usado aquí — este resultado no dice nada sobre el
   rendimiento esperado en producción.
