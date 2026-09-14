# ¿Un experto pequeño supera a un generalista del mismo tamaño? — 22-23/07/2026

> **ACTUALIZACIÓN 23/07/2026 — la batería pasó de 6 a 25 tareas y el resultado se
> invirtió.** Con 6 tareas ganaba el control (4/6 contra 5/6); con 25 gana el especialista
> (**18/25 contra 14/25**). Ver la sección «Segunda ejecución» al final. Lo que sigue a
> continuación es la primera ejecución, que se conserva porque **su conclusión era la
> equivocada y muestra por qué seis tareas no bastaban**.


La pregunta que decide si la arquitectura de "varios cerebros" se sostiene.
Arnés: `eval_expertos.py`. Código verificado **por ejecución**, razonamiento juzgado
**a ciegas**. Ambos modelos en `Q6_K` (mismo nivel de cuantización, para que la
comparación sea de capacidad y no de compresión).

---

## Resultado

| | **Especialista**<br>Qwen2.5-Coder-1.5B | **Control**<br>Qwen3.5-2B |
|---|---:|---:|
| Tamaño | 1,36 GB | 1,47 GB |
| **Código** (ejecutado) | **4/6** | **5/6** ← gana el control |
| Razonamiento | 1 error factual (P4) | 0 errores factuales |
| **Velocidad** | **27,4 t/s** | 19,4 t/s |

### El veredicto sobre la hipótesis

**El especialista NO superó al generalista en su propia especialidad: 4/6 contra 5/6.**

Eso va en contra de la premisa de los expertos, pero **la conclusión se apoya en una sola
tarea de diferencia sobre seis**. Tres salvedades, en orden de peso:

1. **La muestra es demasiado pequeña para decidir.** Una tarea de diferencia sobre 6 no
   distingue una capacidad real de la casualidad.
2. **El control es más grande** (2B vs 1,5B). Puede que la historia real sea
   *"el más grande gana"*, no *"el generalista gana"*.
3. **El razonamiento no cuenta en contra del especialista.** Es un modelo de *código*:
   preguntarle sobre inyección de dependencias o monolitos es **fuera de su
   especialidad**, y en la arquitectura de varios expertos el enrutador nunca le
   enviaría esas preguntas. La prueba justa es código.

Conclusión prudente: **el experimento no respalda la especialización, pero tampoco la
refuta.** Traslada la carga de la prueba hacia ella y deja el asunto abierto.

### Sobre el razonamiento: qué dicen los datos y qué no

De las 4 preguntas de razonamiento, el desglose honesto es:

| | Resultado |
|---|---|
| **P1** (índices) | Ambos **correctos en sustancia**. El especialista es repetitivo; el control, conciso. **Diferencia de estilo, no de corrección.** |
| **P2** (monolito/microservicios) | Ambos **correctos**. Mismo patrón. **Estilo.** |
| **P3** (premisa falsa) | **Fallaron los dos.** El control además derivó al portugués. |
| **P4** (inyección de dependencias) | **Único error factual objetivo**, del especialista. |

> **Advertencia metodológica.** Una primera versión de este documento resumía esto como
> *"el especialista fue peor en 3 de 4"*. Era una sobreafirmación: contaba **un error
> factual junto con dos preferencias de estilo**. El juicio a ciegas del autor —"los
> dos débiles"— estaba **mejor calibrado** que ese resumen. El sentido de juzgar a ciegas
> era evitar el sesgo del que analiza; conviene no anularlo después con la propia lectura.

---

## El hallazgo más importante: fallo con confianza, observado en vivo

La literatura advertía que *"los modelos pequeños fallan con confianza"*. Ocurrió, literalmente:

**Pregunta:** *¿qué problema resuelve la inyección de dependencias?*
**Especialista:** *"Inyección de dependencias es un tipo de **ataque de seguridad** en el
que un atacante introduce código malicioso…"*

Confundió un **patrón de diseño** con un **ataque**. La respuesta es fluida, estructurada
y segura de sí misma — y completamente equivocada. Nada en su forma delata el error.

**Y la pregunta trampa la fallaron los dos.** Ante *"¿por qué Python compila a código
máquina nativo antes de ejecutarse?"* ambos aceptaron la premisa falsa e inventaron una
justificación. **Bonsai-27B sí la había detectado.** Ahí hay una brecha de capacidad real
frente al modelo grande, no una cuestión de estilo.

Detalle adicional: el control mezcló **portugués** dentro de una respuesta en español.

---

## Corrección al modelo físico (otra vez)

La eficiencia sobre el techo de ancho de banda **no es constante**: depende de la
arquitectura, no solo de los bytes.

| Modelo | GB/token | Medido | Techo teórico | Eficiencia |
|---|---:|---:|---:|---:|
| Qwen2.5-Coder-1.5B | 1,36 | 27,4 t/s | 35,3 | **78 %** |
| Qwen3.5-2B | 1,47 | 19,4 t/s | 32,7 | **59 %** |
| GLM-23B-A3B | 2,00 | 12,3 t/s | 24,0 | **51 %** |

El especialista es **8 % más pequeño pero 41 % más rápido** que el control. Eso no lo
explica el tamaño: lo explica la arquitectura. Qwen2.5 es un denso clásico; Qwen3.5 usa
*Gated Delta Networks* con MoE dispersa, que en CPU rinde peor por byte.

> **Corolario incómodo: más nuevo no es más rápido en CPU.** Las extrapolaciones previas
> (que usaban 51 % fijo) subestimaban a los modelos pequeños y simples.

---

## La tensión de fondo de la visión

Juntando todo lo medido, aparece una contradicción que no se resuelve con software:

- **Para ser rápido en RAM hay que bajar de ~2B** (el ancho de banda es el límite).
- **Pero a ≤2B los modelos fallan con confianza** y no detectan premisas falsas.

**Las dos exigencias apuntan en direcciones opuestas.** En este hardware, "muchos
cerebros pequeños" choca contra el hecho de que los cerebros pequeños no son lo bastante
buenos para que se les confíe una respuesta sin supervisión.

Esto **no invalida la visión** — la ubica en el tiempo. Se vuelve viable con más ancho de
banda (DDR5 duplica el techo) o más VRAM. Hoy, la arquitectura de dos niveles con un
**generalista capaz en GPU como destino por defecto** es lo más cercano al óptimo, y es
justo lo que la evidencia externa (CARGO, cascadas por incertidumbre) recomienda.

---

## Nanbeige4.2-3B: no se pudo probar

```
error loading model: unknown model architecture: 'nanbeige'
```

**llama.cpp todavía no soporta el Looped Transformer.** La hipótesis de la doble lectura
(que en RAM leería 2× por token y sería más lento que el GLM) **queda sin verificar**.

Era el riesgo señalado antes de descargarlo: los 4 repos GGUF se habían creado el día
anterior con 0 descargas. Una arquitectura nueva necesita soporte del runtime, no solo
un archivo convertido.

---

## Segunda ejecución: 25 tareas — 23/07/2026

Ampliada la batería a **25 tareas**, todas con biblioteca estándar (importar `pandas`
mediría que esté instalado, no la capacidad del modelo) y verificadas antes de usarlas:
`verificar_bateria.py` resuelve las 25 con implementaciones de referencia y da **25/25**,
así que un fallo es del modelo y no del banco.

| | **Especialista**<br>Qwen2.5-Coder-1.5B | **Control**<br>Qwen3.5-2B |
|---|---:|---:|
| Con 6 tareas | 4/6 | **5/6** |
| **Con 25 tareas** | **18/25 (72 %)** | 14/25 (56 %) |
| Velocidad | **22,6 t/s** | 16,6 t/s |

**El resultado se invirtió.** El especialista gana por 4 tareas y además es **36 % más
rápido**. La conclusión de la primera ejecución —«el experimento no respalda la
especialización»— **se apoyaba en ruido**.

### Pero todavía no basta para afirmarlo

Comparadas tarea por tarea, las **discordancias son 6 a 2** a favor del especialista.
Prueba de McNemar exacta sobre esos 8 casos: **p = 0,29**.

> **No es significativo.** Con 25 tareas la dirección cambió y ahora favorece a la
> especialización, pero un p de 0,29 significa que un resultado así saldría por azar casi
> una de cada tres veces. Lo honesto: **la evidencia pasó de "en contra" a "a favor pero
> no concluyente"**. Para cerrarlo harían falta unas 50-60 tareas.

Lo que sí quedó firme es la **velocidad**: 36 % de diferencia sostenida sobre 25 tareas no
es casualidad, y confirma lo ya visto — la arquitectura densa clásica rinde más por byte
en CPU que la de expertos dispersos.

### Las 5 tareas que fallaron los dos

`bytes`, `camel`, `duracion`, `intervalos`, `parentesis`.

No son tareas exóticas: son las que tienen **una regla explícita fácil de pasar por alto**
(el formato de decimales según la unidad, el guion bajo que no debe quedar al principio,
los intervalos que se tocan en un extremo). Es el mismo modo de falla de siempre: los
modelos pequeños resuelven la forma general y omiten la condición de borde.

---

## Qué hacer con esto

1. **La especialización queda respaldada de forma provisional**, y con un argumento extra
   que no depende de la estadística: el especialista es **más rápido**, así que aun
   empatando en calidad convendría.
2. **Cerrar la cuestión pide 50-60 tareas.** El banco y su verificador ya están hechos;
   añadir tareas es mecánico.
3. **El límite de la supervisión cambió con la muestra grande** — ver
   `resultado_supervisor.md`: la detección cae de 100 % a **56 %**.
3. **La arquitectura de dos niveles sigue en pie** y ya está validada por el lado del
   enrutado (97,6 % de precisión al 84 % de cobertura).
4. **Revisar Nanbeige cuando llama.cpp incorpore la arquitectura** — la idea de cambiar memoria
   por cómputo sigue siendo interesante, sobre todo para GPU.
