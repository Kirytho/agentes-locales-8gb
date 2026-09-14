# Bajar bits no afecta operar herramientas, solo razonar (06-07/09/2026)

**Pregunta:** ¿cuánto se pierde al cuantizar más fuerte un mismo modelo para que
entre con más contexto en 8 GB?

**Modelo:** cuantizaciones del **mismo** Ornith-1.5-9B-MTP, más una versión
ternaria (TB-8B). No son modelos de distinto tamaño.
**Banco:** `pruebas/calidad/eval_stack_completo.py` a través de Hermes: 5
escenarios con oráculo sobre disco.
**Volumen:** 600 ejecuciones (10 brazos × 60).
**Crudos:** registros locales, no incluidos en este repositorio; aquí se
reproducen las tablas.

## Diseño

- **Diseño A:** todas las cuantizaciones con el mismo contexto (65.536 tokens, el
  máximo común a todas).
- **Diseño B:** cada una con el mayor contexto que le cabe en la GPU.

Los escenarios se agrupan en dos tipos:

- **Disco** (36 intentos por modelo): leer, contar, sumar y escribir con formato
  exacto, verificado en el disco.
- **Razonar** (24 intentos por modelo): encontrar un defecto semántico o resumir
  contenido, que exige entender el texto.

## Resultado del diseño A

| cuantización | bits | VRAM | disco | razonar |
|---|---|---:|---:|---:|
| IQ2_M | 2 | 3,87 GB | 30/36 · 83% | 1/24 · 4% |
| IQ3_M | 3 | 4,67 GB | 28/36 · 78% | 6/24 · 25% |
| **IQ4_XS** | 4 | 5,45 GB | **34/36 · 94%** | 9/24 · 38% |
| Q4_K_M | 4 | 5,78 GB | 28/36 · 78% | 10/24 · 42% |
| Q5_K_M | 5 | 6,64 GB | 31/36 · 86% | 12/24 · 50% |
| TB-8B | ternario | 2,18 GB | 13/36 · 36% | 1/24 · 4% |

**El desempeño se parte en dos mitades:**

- **Operar sobre disco no depende de los bits.** Todas las cuantizaciones de
  Ornith están entre 78% y 94% **sin orden**: 2 bits obtiene 83% y 5 bits 86%
  (p = 1,0).
- **Razonar sube con los bits:** 4%, 25%, 38-42%, 50%. 2 bits obtiene 1/24 contra
  12/24 de 5 bits (p = 0,0007). Tendencia global de 4,3 aciertos por bit
  (p = 0,0244).

**El total esconde los efectos.** Juntando todos los escenarios, ampliar el
contexto pasó de 146/240 a 158/240 (p = 0,30), como si no tuviera efecto, mientras
adentro había uno real (ver abajo). Hay que desagregar por tipo de escenario
siempre.

## El ternario se descarta

TB-8B es el **más rápido** (99,9 tok/s) y el **más pequeño** (2,18 GB), y obtiene
14/60 en total: pierde incluso la capacidad de operar (13/36 en disco contra
28/36 de Q4_K_M, p = 0,00073). La versión ternaria de 27B no carga en 8 GB.

**Velocidad y calidad van en direcciones opuestas.** Elegir solo por VRAM y
velocidad habría coronado justo al peor.

## Más contexto ayuda solo a la tarea que lo necesita

Juntando 4 modelos del diseño B, el escenario `contexto` (leer ocho archivos
largos) pasa de 12/48 a 29/48 con el contexto ampliado (p = 0,00086). Los otros
cuatro escenarios no se mueven (134/192 → 129/192, p = 0,66).

## Decisión que salió de esto

**IQ4_XS reemplazó a Q4_K_M** como modelo principal (07/09/2026):

- en calidad **empatan**: juntando ambos diseños, IQ4_XS obtiene 89/120 (43 + 46)
  y Q4_K_M 82/120 (38 + 44), p = 0,392; ningún escenario es significativo por
  separado;
- decidieron los números que no son estadísticos: 0,33 GB menos, +17% de
  velocidad y más reserva de KV con menos VRAM (7.161 contra 7.230 MiB). Con eso
  el contexto subió de 81.920 a 98.304.

**Reparo registrado:** en `contexto`, Q4_K_M obtiene 11/24 contra 8/24 de IQ4_XS.
No es significativo (p = 0,556), pero es el único eje donde gana la versión
anterior y es justo el de contexto largo. Es el primer sospechoso si aparecen
problemas en sesiones muy extensas.

## Salvedades

- Los 6 brazos del diseño A se ejecutaron 60 veces seguidas. Dos brazos del
  diseño B se ejecutaron en series de 10 con reinicio del backend entre series.
  El backend crece ~83 MB por ejecución, así que esos brazos vieron un servidor
  más "fresco". No invalida nada, pero se declara.
- Todo es sobre una familia de modelo. Otra arquitectura puede comportarse
  distinto: en la familia Spark-X2.5, por ejemplo, `Q2_K` quedó roto para
  editar código (ver [Spark](resultado_spark_4b.md)).

## Cómo usar este resultado

Para elegir cuantización hay que mirar **qué tipo de tarea** va a hacer el
modelo, no el puntaje total:

- automatizar operaciones de archivos tolera 2 bits;
- razonar sobre texto o sostener contexto largo, no.
