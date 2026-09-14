# Modelos 2B: ¿sirven varios pequeños residentes? (19/08/2026)

**Banco**: `pruebas/instrumentos/probar_modelo.py` (nuevo) — descarga el GGUF de HuggingFace,
inicia `llama-server` en un puerto libre, ejecuta `eval_expertos.py`, mide la
VRAM real y apaga. **Modelo**: `empero-ai/Qwen3.8-2B-Distill-GGUF`.
**3 ejecuciones por cuantización**, porque una sola no distingue nada aquí.

## La elección: Q5_K_M

| cuantización | código (media) | rango | razonamiento | tok/s | VRAM | caben en 7,4 GB |
|---|---:|---:|---:|---:|---:|---:|
| Q4_K_M | 24,7/53 | 23-26 | 1/1/1 | 186,5 | 1.476 MiB | 5 |
| **Q5_K_M** | **29,0/53** | 27-32 | 4/2/1 | 175,5 | 1.673 MiB | **4** |
| Q8_0 | 27,3/53 | 26-29 | 0/2/2 | 143,3 | 2.183 MiB | 3 |

- **Q4 pierde de verdad**: su rango (23-26) no toca el de Q5 (27-32). 4,3 puntos
  menos por ahorrar 200 MiB no vale.
- **Q8 no aporta nada**: se solapa con Q5 y cuesta 510 MiB más y 32 tok/s menos.
  En modelos pequeños, subir la cuantización cuesta VRAM y no aporta
  calidad.

## Contra el modelo de producción

| | 2B Q5 | Qwen3.8-9B |
|---|---:|---:|
| código | 29/53 | **49/53** |
| velocidad | **175 tok/s** | 54 tok/s |
| VRAM | **1.673 MiB** | ~6.200 MiB |
| caben en la GPU | **4** | 1 |

**El 2B no reemplaza al 9B para escribir código**: falla la mitad de las tareas.
Lo que ofrece es otra cosa — 3,2x la velocidad en la cuarta parte de la VRAM.

**Cuidado con "puntaje por GB"** (la métrica que calcula el banco): es engañosa.
Cuatro agentes a 29/53 no dan 116 aciertos; dan cuatro agentes que se equivocan
el 45% de las veces, y en un pipeline los errores se **encadenan**. Un modelo
así sirve donde el error es barato y detectable —clasificar, extraer, filtrar,
resumir, votar entre varios— no para escribir código que nadie revisa.

## Hallazgo de método: la batería no medía razonamiento (ARREGLADO el 19/08)

Los puntajes fueron **1/1/1, 4/2/1 y 0/2/2**. La cuantización *mejor* (Q8) obtuvo
0/4 en una ejecución. Con 4 preguntas —una de ellas trampa— el número es una
moneda.

No se había notado antes porque todos los modelos evaluados hasta ahora obtenían
4/4: el techo ocultaba el problema. Con modelos pequeños el techo desaparece y se ve.
**Si se van a seguir evaluando modelos pequeños, la parte de razonamiento hay que
ampliarla** como se amplió la de código (25 → 53 tareas el 18/08).

Además la varianza es mayor que con modelos grandes: desviación **2,4** puntos y
un rango de 23-32 entre ejecuciones idénticas de Q5. Con el 9B era ±1-2. **Tres
ejecuciones son el mínimo aquí, no una recomendación.**

---

## Actualización: batería ampliada y medida de nuevo

La parte de razonamiento pasó de 4 preguntas a **25 (5 trampas)**. Con la batería
nueva:

| | código | razonamiento |
|---|---:|---:|
| Qwen3.8-9B | 49/53 | **22/25** |
| Qwen3.8-2B Q5 | 28/53 | **5/25** |

El 2B no solo escribe peor código: **razona mucho peor**, y eso antes no se veía.
5/25 con cinco trampas significa que acepta casi todas las premisas falsas.

Para el objetivo de varios agentes pequeños residentes, esto refuerza lo que ya se
decía arriba: sirven donde el error es barato y detectable, no donde hay que
decidir.


---

## CORRECCIÓN (misma noche): la cuantización no se distingue

Lo de arriba —"Q4 pierde de verdad, su rango no toca el de Q5"— **se midió con 3
ejecuciones por cuantización y no se sostuvo**. Al medir de nuevo con la batería completa
(código + los 25 de razonamiento) y juntar las dos series, con 6-8 ejecuciones cada
una:

| cuantización | n | código media | rango | desv | razonamiento |
|---|---:|---:|---:|---:|---:|
| Q4_K_M | 6 | 25,8/53 | 23-29 | 1,9 | 7,3/25 |
| Q5_K_M | 8 | 28,0/53 | 26-32 | 1,7 | 6,3/25 |
| Q8_0 | 6 | 28,7/53 | 26-32 | 1,9 | 6,3/25 |

La columna de razonamiento promedia solo las 3 ejecuciones con la batería de 25
preguntas de cada cuantización; las anteriores usaban 4 preguntas.

**Los tres rangos se solapan.** Las diferencias son de 0,7 a 2,8 puntos con una
desviación de 1,9: no hay nada que afirmar. Hay una tendencia monótona (a más
bits, más puntaje) que es lo esperable, pero no está establecida.

**El razonamiento no lo mueve la cuantización**: 7,3 / 6,3 / 6,3, indistinguibles
y los tres malos (25% de acierto con 5 trampas).

**Decisión práctica, ahora por costo y no por calidad**: si la calidad no se
distingue, gana la más barata. Q8 cuesta **576 MiB más y 43 tok/s menos** que Q5
por una diferencia de 0,7 puntos que no se puede afirmar. Entre Q4 y Q5, Q4
ahorra 118 MiB y permite un modelo más en la GPU (5 contra 4).

**La lección de método, que es lo que hay que llevarse**: tres ejecuciones no
bastaron. La primera serie daba Q5 > Q8 > Q4; la segunda dio Q8 > Q5 = Q4. La
varianza ENTRE series es mayor que la dispersión DENTRO de cada serie, y eso no
se ve mirando una sola serie por ordenada que sea.

---

## ¿Alguna bandera del servidor mejora el razonamiento? (19/08, noche)

**No, y hay una razón estructural**: la decodificación especulativa (MTP, ngram,
suffix) es *neutra por construcción* — el modelo verifica cada token propuesto,
así que la salida es la misma, solo llega antes. Medido: con MTP el 2B dio 25/53
y 8/25 contra 28/53 y 5/25 sin él, ruido en las dos direcciones.

Las perillas que **sí** pueden mover el razonamiento son de otra familia:
muestreo (`--temp`, `--top-p`, `--top-k`, `--min-p`), cuantización del caché KV
(que resta, no suma) y el **modo pensante**, que la batería enviaba desactivado desde
siempre y nunca se había medido.

### Modo pensante: empeora el código y no ayuda al razonamiento

`Qwen3.8-2B-Q5_K_M`, batería completa, una ejecución por rama:

| | pensamiento off | pensamiento on |
|---|---:|---:|
| código | **27/53** | **18/53** |
| razonamiento | 7/25 | 9/25 |
| velocidad | 174,3 tok/s | 170,3 tok/s |

**−9 puntos en código**, muy por encima de la desviación medida (1,9). El +2 en
razonamiento está dentro del ruido.

**No es truncamiento**: la rama pensante tuvo 1400 tokens de tope contra 400 de
la otra, y ninguna tarea quedó con código vacío.

**Validez de la medición** — dos cosas que hubo que verificar antes de confiar en el
número:

1. El puntuador busca conceptos en todo el texto. Si el pensamiento viniera
   mezclado en la respuesta, habría medido que el modelo *pensó* lo correcto, no
   que lo *respondió*. Se añadió `_sin_pensamiento()` para recortarlo; en este
   build resultó innecesario porque llama-server devuelve el razonamiento en un
   campo aparte (`reasoning_content`), pero queda como protección.
2. Se confirmó que el modo realmente se activaba antes de interpretar la caída:
   con `enable_thinking: true` aparece `reasoning_content`, con `false` no.

**Conclusión práctica**: para trabajo de código, pensamiento apagado. Y como
palanca de razonamiento tampoco sirve en este modelo.
