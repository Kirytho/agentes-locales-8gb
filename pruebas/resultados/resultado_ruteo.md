# ¿Escala el discernimiento a N expertos? — Resultado (22/07/2026)

Experimento para decidir si tiene sentido una arquitectura de varios cerebros
pequeños: **si el enrutador no escala, tener N expertos no sirve**.

Banco: **100 frases, 10 clases** (`banco_ruteo.json`), escrito **antes** que los
enrutadores. Arnés: `eval_router.py`. No se descargó ningún modelo ni se tocó
producción.

---

## Veredicto: sí escala

Criterio fijado **antes** de medir: cobertura ≥ 50 % con precisión ≥ 90 %.

| Estrategia | Costo | Mejor punto | Precisión cruda (todo enrutado) |
|---|---:|---|---:|
| **A** keywords | **0,14 ms** | 83 % cobertura @ **97,6 %** | 83,0 % |
| **B** semántico | ~8 ms* | **no alcanza** el criterio | 41,0 % |
| **C** híbrido | **1,58 ms** | 84 % cobertura @ **97,6 %** | **93,0 %** |

\* Los 136 ms que reporta el arnés para B incluyen la carga del modelo y la construcción de
centroides; el costo marginal real por petición, ya caliente, es ~8 ms.

**Comparación con la línea base:** el clasificador acierta 96,9 % con **4 clases
anchas**. El híbrido sostiene **97,6 % de precisión con 10 clases angostas** al 84 % de
cobertura. **El discernimiento no se degrada al multiplicar los expertos.**

---

## El hallazgo contraintuitivo

**Una señal débil mejora a una fuerte, si se usa solo donde la fuerte duda.**

El enrutado semántico por sí solo es malo: **41 %**. Sin embargo, usado *únicamente*
para desempatar cuando el margen de keywords es pequeño, eleva la precisión cruda de
**83 % → 93 %**.

La razón es que aporta información **complementaria**, no redundante. Y como solo se
consulta en la zona de duda (~18 % de los casos), el costo medio queda en **1,58 ms**:
el camino rápido sigue siendo rápido.

Mejoras por clase al pasar de A a C:

| Clase | A (keywords) | C (híbrido) |
|---|---:|---:|
| `explain` | 6/10 | **10/10** |
| `writing` | 8/10 | **10/10** |
| `math` | 9/10 | **10/10** |
| `code_review` | 5/10 | **8/10** |

---

## La matriz de confusión: las 10 clases se sostienen

Con **keywords solo**, dos clases fallaban y sugerían fusión:
`code_review` → `code_write` (3 casos) y `explain` → `code_write` (3 casos).

Con el **híbrido**, esas confusiones se resuelven. Las que quedan son pocas y
semánticamente plausibles:

| Clase | Aciertos | Confusiones restantes |
|---|---:|---|
| code_write, devops, explain, writing, math, quick | **10/10** | — |
| reasoning | 9/10 | `data_sql` (1) |
| code_fix | 8/10 | `explain` (2) |
| code_review | 8/10 | `explain` (1), `reasoning` (1) |
| data_sql | 8/10 | `code_write` (1), `quick` (1) |

**Conclusión: no hace falta fusionar clases.** La taxonomía de 10 expertos es viable
tal como está.

---

## Limitaciones honestas

1. **La frecuencia de destino no sirve para decidir quién ocupa la GPU.** El banco
   tiene 10 frases por clase *por construcción*, así que el tráfico sale balanceado por
   diseño, no por realidad. Para la colocación hacen falta **logs reales** — el
   proyecto ya los tiene en el historial y los registros del intermediario.
2. **Los centroides semánticos estaban degradados.** Se construyeron con la descripción y
   las keywords de cada perfil, y `explain` absorbió el 52 % del tráfico en la
   estrategia B: las palabras genéricas de pregunta en español dominan el centroide.
   El 41 % es un **piso**, no un veredicto sobre el enrutado semántico en general; con
   frases de ejemplo reales por clase sería bastante mejor.
3. **El banco lo redactó el asistente.** Quien escribe el banco y quien construye el
   enrutador es el mismo, así que puede haber sesgo inconsciente. Conviene que el autor
   añada frases propias, sobre todo casos ambiguos y mal redactados.
4. **De las heurísticas de producción solo se trasladó la de mensaje corto → `quick`.**
   Las otras apuntan a nombres de perfil que no existen en esta taxonomía, y adaptarlas
   habría sido invención propia.

---

## Qué habilita este resultado

La arquitectura de dos niveles queda validada del lado del discernimiento:

- **T1 · GPU** — generalista capaz como destino por defecto y red de seguridad.
- **T2 · RAM** — N especialistas pequeños (≤2B), a los que el enrutador envía el **84 %
  del tráfico con 97,6 % de acierto**.
- El **16 % restante** cae en el generalista: sin daño, solo oportunidad perdida.

## Próximos pasos sugeridos

1. **Frecuencia real:** extraer la distribución del historial para decidir la
   colocación en GPU (dato que este experimento no puede dar).
2. **Ampliar el banco** con frases propias, en especial ambiguas.
3. **Llevar el híbrido a producción** en el clasificador, con su prueba de regresión —
   solo cuando se vaya a usar más de un experto.
4. **Solo entonces**, probar un experto pequeño real y medir si supera al generalista
   en su especialidad (la pregunta que sigue abierta).
