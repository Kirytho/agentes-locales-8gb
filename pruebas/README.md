# Índice de bancos y herramientas

Qué hace cada script, qué necesita para ejecutarse y dónde quedaron sus resultados.
Cada archivo explica además en su encabezado **por qué existe** y cómo se usa.

Estos scripts se publican para que se pueda ver **cómo se obtuvo cada número**: qué
tareas se dieron, cómo se puntuó y qué se consideró un acierto. No son una
herramienta lista para usar.

## Qué significa la columna «Necesita»

| Código | Significado |
|---|---|
| **HTTP** | Solo un servidor compatible con OpenAI (`llama-server`, vLLM, etc.). Se le pasa el puerto o la URL. Es lo más fácil de reproducir. |
| **LANZA** | Inicia `llama-server` por su cuenta con binarios y modelos en rutas del proyecto original (`backends/`, `modelos/`). Hay que adaptar esas rutas. |
| **INTER** | Habla con el intermediario (puerto 8086), que **no está en este repositorio**. Sin él no funciona; sirve para ver cómo se midió. |
| **HERMES** | Necesita el agente Hermes instalado y configurado. |
| **PEVAL** | Necesita ProjectEval clonado en `externos/ProjectEval` (GPL-3.0, no incluido). |
| **ARCHIVOS** | No usa ningún servidor: lee resultados, logs o grabaciones ya hechos. |
| ⚠️ | **Ejecuta código escrito por un modelo** (o deja que un agente ejecute comandos). Ver la advertencia de seguridad del README principal. |

---

## `calidad/` — bancos que puntúan si el trabajo quedó bien

| Script | Qué mide o hace | Necesita | Resultados |
|---|---|---|---|
| `eval_expertos.py` | Batería principal: 53 funciones de Python verificadas **ejecutándolas**, más 25 preguntas de razonamiento (5 con premisa falsa). | HTTP ⚠️ | `resultado_experto_*.json` · [expertos](resultados/resultado_expertos.md), [2B](resultados/resultado_modelos_2b.md), [candidatos 2B](resultados/resultado_candidatos_2b.md), [GPU](resultados/resultado_gpu_pequenos.md) |
| `eval_edicion.py` | Si el modelo sabe **modificar** código existente sin romper lo que ya funcionaba (pruebas nuevas + pruebas de regresión). | HTTP ⚠️ | `resultado_edicion_*.json` · [Ornith o K2](resultados/resultado_modelo_codigo_09-09.md), [Spark](resultados/resultado_spark_4b.md) |
| `eval_formato_edicion.py` | Si el modelo edita con bloques SEARCH/REPLACE en vez de reescribir el archivo entero. | HTTP ⚠️ | `resultado_formato_*.json` · [Ornith o K2](resultados/resultado_modelo_codigo_09-09.md), [K2 razonar](resultados/resultado_k2_razonar.md) |
| `eval_techo_archivo.py` | Hasta qué tamaño de archivo edita bien el modelo. | HTTP ⚠️ | `resultado_techo_*.json` · [delegación](resultados/resultado_delegacion_mcp.md) |
| `eval_scripts.py` | Si escribe **scripts operativos** (leer directorios, sumar, filtrar) y no solo funciones aisladas; compara la salida con la respuesta calculada. | HTTP ⚠️ | `resultado_scripts_*.json` · [scripts operativos](resultados/resultado_scripts_operativos.md) |
| `eval_agente.py` | Si el modelo sabe **operar**: pedir la herramienta correcta, mirar antes de actuar, no borrar lo que no debe. Usa herramientas simuladas con guion. | HTTP | `resultado_agente_*.json` · [agente y harness](resultados/resultado_agente_harness.md) |
| `eval_stack_completo.py` | El sistema entero: Hermes con sus 21 herramientas → intermediario → modelo, 5 escenarios con oráculo sobre el disco. | HERMES + INTER ⚠️ | [agente y harness](resultados/resultado_agente_harness.md), [cuantización](resultados/resultado_cuantizacion_operar_razonar.md), [Kaggle](resultados/resultado_kaggle_harness.md), [caché de prompt](resultados/resultado_cache_prompt_hermes.md) |
| `eval_fanout.py`, `eval_fanout_pequeno.py` | Escenario de **abanico**: varios análisis independientes que Hermes debe delegar a subagentes y juntar en un archivo. | HERMES + INTER ⚠️ | [abanico](resultados/resultado_abanico.md) (sin JSON publicado) |
| `eval_reparto_proyecto.py` | Repartir un **proyecto Django** entre 1 o 4 trabajadores (slots de `--parallel`) y juzgarlo con Selenium. | HTTP + PEVAL ⚠️ | `resultado_reparto_*.json` · [4 tareas](resultados/resultado_reparto_proyecto.md), [20 tareas](resultados/resultado_reparto_20tareas.md) |
| `eval_supervisor.py` | Si un modelo grande detecta los errores de código de uno pequeño, contra la verdad obtenida por ejecución. | HTTP | [supervisor](resultados/resultado_supervisor.md) |
| `banco_compuesto.py`, `banco_compuesto_grande.py` | Datos: tareas con piezas independientes (4 y 10-12 piezas) para medir reparto. No se ejecutan solos. | — | [reparto de piezas](resultados/resultado_reparto_piezas.md) |

## `rendimiento/` — velocidad, concurrencia, contexto, caché

| Script | Qué mide o hace | Necesita | Resultados |
|---|---|---|---|
| `medir_concurrencia.py` | Rendimiento agregado con 1, 2 y 4 agentes a la vez sobre un backend. | HTTP | [concurrencia](resultados/resultado_concurrencia.md) |
| `medir_escalado.py` | Cuántos agentes soporta un modelo, con repeticiones y niveles en orden alternado. | HTTP | `resultado_escalado.json` · [escalado](resultados/resultado_escalado_capacidad.md) |
| `medir_capacidad.py` | Peticiones por minuto sostenidas en lazo cerrado. | INTER | `resultado_capacidad.json` · [escalado](resultados/resultado_escalado_capacidad.md) |
| `medir_respuesta.py` | Tiempo hasta el primer token y tiempo total, con y sin instrucción de brevedad. | INTER | `resultado_respuesta.json` · [escalado](resultados/resultado_escalado_capacidad.md) |
| `medir_contexto.py` | Cuánto contexto usa de verdad una conversación de trabajo. | INTER | [contexto](resultados/resultado_contexto.md) |
| `medir_flujo_prompt.py` | Qué valor conviene en cada ajuste del prompt (mensajes de historial, cabeza fija). | INTER | `resultado_flujo_*.json` · [escalado](resultados/resultado_escalado_capacidad.md) |
| `medir_reuse_intermediario.py` | Si `--cache-reuse` ayuda cuando el intermediario inyecta memoria. | INTER + LANZA | `resultado_reuse_orq_*.json` · [memoria al final](resultados/resultado_memoria_posicion.md) |
| `medir_cache_reuse.py` | `--cache-reuse` directo contra el backend. | LANZA | [caché](resultados/resultado_cache_reuse.md) |
| `medir_spec.py` | Estrategias de decodificación especulativa sin modelo borrador, con control de salida idéntica. | LANZA | [spec](resultados/resultado_spec.md), [spec con bloques](resultados/resultado_spec_bloques.md) |
| `cribar_flags.py` | Descarte rápido de banderas de `llama-server` que no mueven la velocidad. | LANZA | `resultado_criba_*.json` · [criba de banderas](resultados/resultado_criba_banderas.md) |
| `medir_ncmoe.py` | Barrido de `-ncmoe N` (expertos MoE entre GPU y CPU). | LANZA | [ncmoe](resultados/resultado_ncmoe.md) |
| `medir_gpu.py` | Varios modelos pequeños residentes en VRAM: velocidad, contención y calidad. | LANZA (Windows) ⚠️ | [GPU](resultados/resultado_gpu_pequenos.md) |
| `medir_convivencia_2b.py` | Costo de tener dos modelos 2B/4B cargados a la vez en la misma GPU. | LANZA | [candidatos 2B](resultados/resultado_candidatos_2b.md) |
| `detectar_gguf.py` | Lee un GGUF y dice qué soporta (MTP, arquitectura). Utilidad. | ARCHIVOS | [criba de banderas](resultados/resultado_criba_banderas.md) |
| `medir_pipeline.py` | Planificar antes de programar (dos llamadas) contra una sola llamada directa. | HTTP ⚠️ | `resultado_pipeline.json` · [misma tarea](resultados/resultado_misma_tarea.md) |
| `medir_agentes_separados.py` | Un agente que planifica y otro que programa, con distintos prompts de rol. | HTTP ⚠️ | `resultado_agentes_separados_*.json` · [misma tarea](resultados/resultado_misma_tarea.md) |
| `medir_plan_propio.py` | Si un plan escrito por el modelo reparte tan bien como uno hecho a mano. | HTTP ⚠️ | `resultado_plan_propio_*.json` · [reparto de piezas](resultados/resultado_reparto_piezas.md) |
| `medir_plan_roto.py` | Si los errores del plan se propagan al código. | HTTP ⚠️ | `resultado_plan_roto_*.json` · [reparto de piezas](resultados/resultado_reparto_piezas.md) |
| `medir_reparto_piezas.py` | Si las piezas escritas por agentes distintos encajan entre sí. | HTTP ⚠️ | `resultado_reparto_piezas_*.json` · [reparto de piezas](resultados/resultado_reparto_piezas.md) |
| `medir_mejor_de_n.py` | Varios intentos sobre la misma tarea: cuánto recupera elegir el mejor. | HTTP ⚠️ | `resultado_mejor_*.json` · [misma tarea](resultados/resultado_misma_tarea.md) |
| `medir_juez.py` | Si el modelo sabe elegir la mejor de varias respuestas. | HTTP ⚠️ | `resultado_juez.json` · [misma tarea](resultados/resultado_misma_tarea.md) |
| `medir_tests_generados.py` | Si las pruebas que escribe el modelo sirven para elegir entre soluciones. | HTTP ⚠️ | `resultado_tests_generados_*.json` · [misma tarea](resultados/resultado_misma_tarea.md) |

Los prompts de rol que usan varios de estos scripts están en [`roles/`](roles/).

## `subsistemas/` — piezas concretas del intermediario

| Script | Qué mide o hace | Necesita | Resultados |
|---|---|---|---|
| `eval_memoria_posicion.py` | Si el modelo recupera igual un dato de la memoria puesto al final del prompt que al inicio. | INTER | [memoria al final](resultados/resultado_memoria_posicion.md) |
| `eval_reparto_codigo.py` | Reparto en equipo con 2 modelos (coordinador + trabajador), una solicitud. | HTTP | [plan vs equipo](resultados/resultado_reparto_pipeline_vs_equipo.md) |
| `eval_reparto_multi.py` | Plan+ejecución del intermediario contra reparto en equipo, 3 solicitudes verificadas. | INTER + HTTP ⚠️ | [plan vs equipo](resultados/resultado_reparto_pipeline_vs_equipo.md) |

## `instrumentos/` — utilidades de medición

| Script | Qué hace | Necesita | Usado en |
|---|---|---|---|
| `grabador_proxy.py` | Proxy que graba el tráfico entre el agente y el intermediario (herramientas ofrecidas, llamadas reales o narradas). | INTER | `eval_stack_completo.py` |
| `bateria_repetida.py` | Ejecuta `eval_expertos.py` N veces y promedia. | HTTP ⚠️ | informes de expertos |
| `resumen_bateria.py` | Junta los `resultado_experto_*.json` en una tabla. | ARCHIVOS | informes de expertos |
| `verificar_bateria.py` | Comprueba que la batería esté bien escrita resolviéndola con implementaciones de referencia (debe dar 25/25). | ARCHIVOS | [expertos](resultados/resultado_expertos.md) |
| `validar_banco_compuesto.py` | Lo mismo para los bancos compuestos. | ARCHIVOS | [reparto de piezas](resultados/resultado_reparto_piezas.md) |
| `probar_modelo.py` | Descarga un modelo de Hugging Face, lo inicia, ejecuta la batería y lo apaga. | LANZA ⚠️ | [2B](resultados/resultado_modelos_2b.md), [candidatos 2B](resultados/resultado_candidatos_2b.md) |
| `chat.py` | Chat de terminal contra el intermediario. | INTER | — |
| `chat_3modelos.py` | Chat con tres modelos: comparar respuestas o trabajar en equipo. | HTTP | [equipo](resultados/resultado_equipo.md) |

## `../herramientas/` — barridos, tablas y envoltorios

| Script | Qué hace | Necesita | Usado en |
|---|---|---|---|
| `perfil_codigo.sh` | Perfil de código de un modelo: los 4 bancos de programación en un comando. | LANZA ⚠️ | [Ornith o K2](resultados/resultado_modelo_codigo_09-09.md) |
| `barrer_perfiles.sh` | `perfil_codigo.sh` sobre varios modelos, del más pequeño al más grande. | LANZA ⚠️ | [Spark](resultados/resultado_spark_4b.md) |
| `barrer_5rep.sh` | Los 4 bancos × 5 repeticiones por modelo. | LANZA ⚠️ | [Spark](resultados/resultado_spark_4b.md) |
| `barrer_codigo.sh` | Barrido de código sobre las cuantizaciones de un modelo. | LANZA ⚠️ | — |
| `duelo_codigo.sh` | Dos modelos, 5 ejecuciones alternadas cada uno. | LANZA ⚠️ | — |
| `tabla_5rep.py`, `tabla_codigo.py` | Tablas con estadística (Fisher, rangos) a partir de los resultados. | ARCHIVOS | [Spark](resultados/resultado_spark_4b.md) |
| `tanda_banco.sh` | Serie corta de `eval_stack_completo.py` con un modelo. | LANZA + INTER + HERMES ⚠️ | [cuantización](resultados/resultado_cuantizacion_operar_razonar.md) |
| `fanout_modelo.sh`, `fanout4_modelo.sh` | Una ejecución del escenario de abanico por modelo. | LANZA + INTER + HERMES ⚠️ | [abanico](resultados/resultado_abanico.md) |
| `medir_reparto.py` | Cuenta delegaciones **útiles** (no llamadas vacías) en una grabación del tráfico. | ARCHIVOS | [abanico](resultados/resultado_abanico.md) |
| `contabilidad_mcp.py` | Cuánto contexto ahorró delegar ediciones a un modelo local, con uso real. | ARCHIVOS | [delegación](resultados/resultado_delegacion_mcp.md) |
| `juzgar_reparto.py` | Ejecuta el juez de ProjectEval y cierra los procesos que deja abiertos. | PEVAL ⚠️ | [20 tareas](resultados/resultado_reparto_20tareas.md) |
| `leer_cache_prompt.py` | Lee el log de `llama-server` y calcula cuánto se recalculó sin necesidad. | ARCHIVOS | [caché de prompt](resultados/resultado_cache_prompt_hermes.md) |
