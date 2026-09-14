# Agentes de programación locales en 8 GB de VRAM

Este repositorio contiene **las mediciones, los bancos de prueba y los informes**
de un proyecto personal: ejecutar agentes de programación con modelos locales en
una tarjeta gráfica de consumo, sin depender de un servicio de pago. **No contiene el
programa** que se construyó para eso.

Cómo funciona ese programa, en términos generales, está en
[`docs/como-funciona.md`](docs/como-funciona.md).

## Qué se investigó

La pregunta de fondo: **¿se puede tener un agente de programación útil sin
depender de un servicio de pago, en hardware común?** Y la sub-pregunta práctica:
¿cuál es el modelo más pequeño que programa bien?

```
hardware   RTX 3060 Ti 8 GB · 32 GB RAM · CachyOS Linux
motor      llama.cpp
agente     Hermes, con 21 herramientas y ~22.700 tokens de presupuesto fijo
```

## Hallazgos principales

Todos medidos, con el oráculo sobre el resultado real (disco, ejecución, Selenium)
y no sobre la opinión de un modelo. Los detalles, la metodología y las salvedades
están en cada informe.

**El harness pesa más de lo que parece.** Con el mismo modelo y la misma tarea,
Hermes resolvió en 13 s y 5 solicitudes lo que opencode no resolvió en 231 s y 43
solicitudes.

**El fallo agéntico es de conducta, no de capacidad.** Un Qwen3-30B-A3B obtuvo 5/12
operando el harness, peor que un granite de 3B (10/12). Y quitarle a Hermes
herramientas que la tarea no usaba bajó el acierto de 12/12 a 6/12 (Fisher p = 0,014):
con menos herramientas, el modelo dejó de usar herramientas.

**Bajar bits de cuantización no afecta el uso de herramientas, solo el razonamiento.** En la
familia de Ornith-1.5-9B, IQ4_XS resultó el mejor compromiso.

**Delegar código a un modelo local ahorra tokens solo si evita leer.** Escribir
funciones nuevas por delegación cuesta más que escribirlas (0,1×); editar un
archivo existente sin que entre al contexto ahorra (4,2×).

**Con 30 GB en la nube gratuita, un MoE de 36B con 4B activos fue el mejor
medido.** K2-Horizon-MoVA-36B-A4B obtuvo 5/5 en el banco de stack completo a
40,7 tok/s, igualando a un Qwen3.8-27B denso que iba a 13-15. Con una salvedad:
el motor tuvo un crash (`CLAMP failed / illegal memory access`) que no se
reprodujo después y sigue sin explicación.

**Repartir un proyecto entre cuatro slots no cambia la calidad y reduce el tiempo.**
Sobre las 20 tareas de ProjectEval, el reparto paralelo hizo las mismas 264
llamadas que el secuencial en 2,5 veces menos tiempo, sin diferencia de acierto
(Fisher p = 0,92). El K2-Horizon-7B local dio 0,0927 en la escala del paper, entre
Gemini-1.5-pro y GPT-4o — **número inflado**, porque el prompt incluyó una ayuda
que el leaderboard no da (ver el informe).

**La caché de prompt de llama.cpp funciona a través de todo el stack.** En una
sesión real de Hermes, de 674.208 tokens entrantes solo 187 se recalcularon
estando ya en caché (0,03 %); el ahorro de prellenado estimado es de unas 7,7 veces.

## Metodología y lo que costó aprenderla

- **El oráculo mira el resultado, no la prosa.** Archivos en disco comparados byte
  a byte, código ejecutado, proyectos iniciados y operados con Selenium.
- **Una ejecución no es una medición.** Repeticiones y test exacto de Fisher antes
  de afirmar una diferencia. Dos conclusiones de una sola ejecución se revirtieron
  al repetirlas.
- **Verificar el instrumento antes de confiar en él.** Es la lección que más se repite
  en los informes: bancos que devolvían "ok" a comandos desconocidos, que medían el
  backend equivocado, que copiaban plantillas vacías y hacían parecer que el
  modelo no escribía páginas. **Cuando condiciones distintas dan un número
  idéntico al decimal, casi siempre es el medidor que alcanzó un límite.**

## Estructura

```
pruebas/
  calidad/        bancos que puntúan si el trabajo quedó bien
  rendimiento/    velocidad, concurrencia, contexto, caché
  subsistemas/    posición de la memoria en el prompt, reparto entre modelos
  instrumentos/   grabador del tráfico (proxy), baterías, utilidades
  resultados/     32 informes .md y 345 mediciones .json
herramientas/     barridos, tablas, juez envuelto, lector de caché
docs/             cómo funciona, en general; notas del fork de llama.cpp
kaggle/           notebook para servir un modelo en Kaggle y usarlo desde la computadora
```

### Sobre el idioma de los datos

Los informes, los bancos y la documentación están en español neutro. Las
mediciones `.json` son registros crudos: conservan el texto exacto que se envió a
los modelos y lo que respondieron, que en algunos casos está redactado en
lenguaje coloquial regional. No se modificaron para no alterar lo que se midió;
solo se anonimizaron los nombres internos del programa.

### Sobre ejecutar los bancos

**Ninguno está listo para usar**, y conviene saberlo antes de intentarlo. De los 60
scripts (se pueden solapar):

```
35  se comunican por HTTP con un endpoint compatible con OpenAI
18  inician llama-server con los binarios y lanzadores del proyecto
15  se comunican con el intermediario del proyecto
 2  necesitan Hermes
```

Los que solo usan HTTP se pueden dirigir a cualquier `llama-server` cambiando
las variables de entorno de cada script, documentadas en su encabezado. Los que
dependen del intermediario o de los lanzadores no funcionan sin el programa, que
no está en este repositorio: sirven para ver **cómo** se midió cada número. Se
excluyeron además los bancos que importan módulos internos del programa.

## Material de terceros

- **ProjectEval** (ACL 2025 Findings / ACM TOSEM) — tareas y juez del banco de
  reparto. No se incluye: es GPL-3.0 y se debe clonar por separado en `externos/`.
  <https://github.com/RyanLoil/ProjectEval>
- Los modelos citados tienen sus propias licencias en Hugging Face.
- Las cifras de otros trabajos se citan con su fuente en cada informe.

## Índice de informes

| Informe |
|---|
| [Benchmark base (20/07/2026)](pruebas/resultados/benchmark_base.md) |
| [Candidatos de modelo para la GPU de 8 GB — Fase 2 (22/07/2026)](pruebas/resultados/candidatos_modelos.md) |
| [Atomic AI (proxy de descomposición de tareas) — probado y DESCARTADO](pruebas/resultados/resultado_atomic_ai.md) |
| [Bonsai-27B-Q1_0 como candidato de GPU (T1) — medido 22/07/2026](pruebas/resultados/resultado_bonsai_t1.md) |
| [Caché de prompt con Hermes: el intermediario no la rompe (13/09/2026)](pruebas/resultados/resultado_cache_prompt_hermes.md) |
| [Medición contra el intermediario (el caso que faltaba)](pruebas/resultados/resultado_cache_reuse.md) |
| [El mejor 2B para agentes residentes (19-20/08/2026)](pruebas/resultados/resultado_candidatos_2b.md) |
| [Concurrencia: cuánto rinde el intermediario con varios agentes a la vez](pruebas/resultados/resultado_concurrencia.md) |
| [Cuánto contexto usa una solicitud real (y un bug que apareció al medirlo)](pruebas/resultados/resultado_contexto.md) |
| [¿Pueden convivir varios cerebros? — medido 22/07/2026](pruebas/resultados/resultado_convivencia.md) |
| [¿Pueden los 3 modelos repartirse el trabajo? — 22/07/2026](pruebas/resultados/resultado_equipo.md) |
| [nanbeige4.2-3b-Q4_K_M — primera ejecución en Linux/CachyOS (27/07/2026)](pruebas/resultados/resultado_experto_nanbeige3b_linux.md) |
| [Qwen3-4B-Q4_K_M — ejecución en Linux/CachyOS junto a nanbeige (27/07/2026)](pruebas/resultados/resultado_experto_qwen3-4b_linux.md) |
| [Qwen3.5-4B-Q4_K_M — confirma la hipótesis de compatibilidad con `turbo3` (27/07/2026)](pruebas/resultados/resultado_experto_qwen35-4b_linux.md) |
| [¿Un experto pequeño supera a un generalista del mismo tamaño? — 22-23/07/2026](pruebas/resultados/resultado_expertos.md) |
| [Tres modelos pequeños residentes en VRAM — medido 23/07/2026](pruebas/resultados/resultado_gpu_pequenos.md) |
| [¿Le sirve a K2 razonar para programar? — medido 11/09/2026](pruebas/resultados/resultado_k2_razonar.md) |
| [Hermes contra modelos en Kaggle — medido 11/09/2026](pruebas/resultados/resultado_kaggle_harness.md) |
| [Memoria híbrida (BM25 + vector + RRF) vs similitud plana](pruebas/resultados/resultado_memoria_hibrida.md) |
| [Mover la memoria al final del prompt](pruebas/resultados/resultado_memoria_posicion.md) |
| [¿Ornith o K2 para el MCP? — medido 09/09/2026](pruebas/resultados/resultado_modelo_codigo_09-09.md) |
| [Modelos 2B: ¿sirven varios pequeños residentes? (19/08/2026)](pruebas/resultados/resultado_modelos_2b.md) |
| [MoE híbrido (`-ncmoe N`) sobre Qwen3-30B-A3B](pruebas/resultados/resultado_ncmoe.md) |
| [Prueba end-to-end en Linux/CachyOS — 2026-07-27](pruebas/resultados/resultado_prueba_linux_20260727.md) |
| [Reparto entre slots, las 20 tareas: la calidad no cambia, el tiempo se reduce a la mitad (12/09/2026)](pruebas/resultados/resultado_reparto_20tareas.md) |
| [Plan+ejecución vs. reparto en equipo — 4 solicitudes, 2 modelos (27/07/2026)](pruebas/resultados/resultado_reparto_pipeline_vs_equipo.md) |
| [Repartir un proyecto entre N trabajadores: cuesta lo mismo, tarda menos (12/09/2026)](pruebas/resultados/resultado_reparto_proyecto.md) |
| [¿Escala el discernimiento a N expertos? — Resultado (22/07/2026)](pruebas/resultados/resultado_ruteo.md) |
| [Spark-X2.5-4B para el MCP — medido 09/09/2026](pruebas/resultados/resultado_spark_4b.md) |
| [Decodificación especulativa sin modelo borrador (`--spec-type`) — backend GPU](pruebas/resultados/resultado_spec.md) |
| [Especulación con la carga del MCP (bloques SEARCH/REPLACE) — 09/09/2026](pruebas/resultados/resultado_spec_bloques.md) |
| [¿Sirve que la GPU supervise a los modelos pequeños? — 22/07/2026](pruebas/resultados/resultado_supervisor.md) |

## Licencia

- **Código** (`pruebas/**/*.py`, `herramientas/`, `kaggle/*.ipynb`, scripts `.sh`):
  MIT — ver [`LICENSE`](LICENSE).
- **Informes, documentación y mediciones** (`*.md`, `pruebas/resultados/*.json`):
  Creative Commons Atribución 4.0 Internacional (CC BY 4.0) — ver
  [`LICENSE-INFORMES`](LICENSE-INFORMES).
- El material de terceros citado conserva su propia licencia.
