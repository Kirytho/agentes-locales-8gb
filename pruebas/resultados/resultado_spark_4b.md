# Spark-X2.5-4B para el MCP — medido 09/09/2026

Primer modelo probado con el motor `bin-spark` (upstream 434ddbb), y primer
candidato de menos de 3 GB. Ejecutado con `--reasoning off`: la plantilla trae
thinking encendido y sin apagarlo devuelve **cero** de respuesta.

## El resultado en una línea

**Edita igual que los modelos de 5 GB con la mitad de VRAM, pero no se le puede
confiar el formato de bloques.**

## Editar: empata con los grandes

| modelo | GB | VRAM | edición | rompió |
|---|---:|---:|---:|---:|
| **Spark-X2.5-4B-Q4_K_M** | **2,42** | **3.527** | **58/65** | 2 |
| K2-Horizon-7B-Q4_K_S | 5,00 | 6.142 | 61/65 | 0 |
| Ornith-1.5-9B-MTP | 5,08 | 5.671 | 62/65 | 1 |

`Spark vs K2` p=0,530 · `Spark vs Ornith` p=0,324 — **sin diferencia detectable**.

## Bloques: aquí falla

| | formato | aplica | PASA | rompió | chars |
|---|---:|---:|---:|---:|---:|
| Spark, bloques | 64/65 | 59/65 | 46/65 | **9** | 870 |
| Spark, **entero** | 65/65 | 65/65 | **61/65** | **1** | 2.647 |
| K2, bloques | 62/65 | 60/65 | 56/65 | 3 | 395 |

Emite bloques **mejor que K2** (98% de formato) y sin embargo rompe la regresión
9 veces sobre 65. Los fallos son todos del mismo tipo:

```
ImportError: cannot import name 'TOPE'        omitió una constante
NameError: name 'SEPARADOR' is not defined    omitió otra
IndentationError: unexpected indent           rompió la estructura
ValueError: operacion desconocida: producto   omitió un caso
```

Con **archivo entero casi no falla**: 61/65 y una sola regresión rota, al nivel
de K2. Sabe hacer el cambio; lo que falla es recortar.

## La hipótesis que no era

Sus bloques son **2,2x más grandes** que los de K2 (870 contra 395 chars), así
que se probó pedirle explícitamente bloques pequeños.

| | formato | aplica | PASA | rompió | chars |
|---|---:|---:|---:|---:|---:|
| sin la instrucción | 64/65 | 59/65 | 46/65 | 9 | 870 |
| con «bloque lo más pequeño posible» | 60/65 | 56/65 | 40/65 | **11** | 455 |

**La instrucción funcionó y no sirvió.** Los bloques salieron 1,9x más pequeños —
hizo exactamente lo pedido — y **todo empeoró**. El tamaño no era la causa.

La explicación probable es la contraria: bloques más pequeños ⇒ **más bloques** por
cambio, y cada uno es otra oportunidad de error; y un `SEARCH` corto es menos único y
coincide peor, que es lo que muestra `aplica` bajando de 59 a 56.

Queda como opción desactivada (`EVAL_FORMATO_PEQUENO=1`), documentada para que nadie la
vuelva a proponer sin mirar esto.

## Qué haría falta para usarlo

Spark es viable **con formato entero**, y ahí su techo lo pone `MAX_TOKENS`
(~630 líneas), no el contexto. Deja 2.600 MiB libres de VRAM, que bastan para
subir contexto **y** `MAX_TOKENS`: con 8.000 el techo de entero llegaría a ~1.260
líneas, comparable al de K2 con bloques. **Sin medir.**

Hasta entonces, **K2 sigue siendo el modelo del MCP.**

---

## Pendiente (09/09/2026)

**Faltan 8 de las 9 cuantizaciones.** Solo se midió `Q4_K_M`. La pregunta ya no
es si la familia sirve —respondido, edita como los de 5 GB— sino **cuánto se
puede bajar antes de romperla**.

```sh
PRINCIPAL_EXTRA="--reasoning off" \
  herramientas/barrer_perfiles.sh 'modelos/Spark-X2.5-4B-GGUF-ngquocvinh/*.gguf'
```

Va de la más pequeña a la más grande, omite la ya medida, y se puede detener y retomar.
8 modelos × 4 bancos ≈ 4-5 horas. Sin `--reasoning off` todas marcan cero: se
estaría midiendo el presupuesto de tokens, no los modelos.

Atajo de ~2 h: solo `Q5_K_M`, `Q3_K_M`, `Q2_K` e `IQ2_XS`. `Q8_0` y `Q6_K` pesan
más que `Q4_K_M` sin margen visible de mejora, y `Q1_0` casi seguro no inicia.

**Predicción registrada antes de medir:*** las i-quants (`IQ2_XS`, `IQ1_M`) y `Q1_0`
se rompen; `Q2_K` de 1,7 GB resiste. Está medido en este proyecto que bajo 4
bits los i-quants colapsan y los K-quants no — **el esquema decide, no los
bits**. Si sale al revés, el hallazgo es ése.

Y sin medir tampoco: subir `MAX_TOKENS` para que el formato entero de Spark
llegue a ~1.260 líneas, que es lo único que lo haría reemplazar a K2.

## Barrido de 5 repeticiones — notas durante la ejecución (11/09/2026)

- **`Q1_0@ngquocvinh` no se midió.** Las 13 tareas de la criba devolvieron
  `HTTPError`: el motor carga el archivo (1.722 MiB) pero el servidor rechaza
  generar. No es que el modelo sea malo — no llegó a producir nada. Pendiente
  reproducirlo aparte para ver el código HTTP exacto.
- **`IQ1_M` e `IQ2_XS` están rotos de verdad**: devuelven código que no compila
  (`SyntaxError: unmatched ')'`, `unterminated triple-quoted string`). Coincide
  con la predicción escrita antes de medir.
- Mejora registrada para `barrer_5rep.sh` (no se modifica mientras se ejecuta, porque bash lee
  el script a medida que avanza): distinguir **error del servidor** de **modelo
  roto** en la criba, en vez de marcar los dos como ROTO.

---

## PENDIENTE: el barrido quedó a mitad (11/09/2026, 20:0x)

Se detuvo a petición del usuario para pasar al camino de Kaggle + Hermes. **12 de 22
modelos medidos**, guardados en `logs/barrido_5rep.txt`.

Para retomar — omite automáticamente los que ya tienen línea:

```sh
PRINCIPAL_EXTRA="--reasoning off" herramientas/barrer_5rep.sh \
  'modelos/Spark-X2.5-4B-*/*.gguf modelos/K2-Horizon-7B-Q4_K_S.gguf' 16384
herramientas/tabla_5rep.py
```

**Faltan los 10 más grandes** (2,3 a 5 GB) — incluida `K2-Horizon-7B-Q4_K_S`,
que iba última y es la **referencia**. Sin ella, las columnas `+/-` de la tabla
no se pueden calcular: hoy el comparador dice «referencia TODAVÍA NO MEDIDA».

### Lo que ya se ve con 12 medidos

- **`Q2_K` desmiente la predicción.** Se había registrado que los K-quants
  resistirían bajo 4 bits y los i-quants no. Salió al revés: `Q2_K` (1,66 GB) da
  3/13 y está roto, mientras `IQ3_XXS` con imatrix (1,68 GB, casi el mismo peso)
  llega a 53/65 editando. La regla venía del barrido de K2 y **no se traslada a
  esta familia**.
- **El imatrix no hizo la diferencia esperada** donde se pudo comparar directamente:
  `Q3_K_M` da 46/65 con y sin, p=1,000. Donde sí parece pesar es bajo 3 bits,
  que es justo donde solo existen versiones con imatrix.
- **El defecto con bloques es de toda la familia, no de una cuantización.** La
  columna `bloques_rompio` da 8, 10, 11, 11, 12 en los que editan bien, contra
  **2** de K2. `Q4_K_S@miifanboy` edita 58/65 —al nivel de K2— y aun así rompe
  la regresión 11 veces.
- **Cuidado con `IQ3_XXS`:*** tiene el mejor `bloques_rompio` (2) pero su
  `bloques_pasa` es 12/65. No es virtud: casi nunca emite un bloque válido, así
  que no llega a romper nada.

### Dos arreglos registrados para `barrer_5rep.sh`

1. **Distinguir error del servidor de modelo roto.** `Q1_0@ngquocvinh` quedó
   marcado igual que los rotos, pero sus 13 tareas devolvieron `HTTPError`: el
   motor carga el archivo y el servidor rechaza generar (probablemente no hay
   núcleo CUDA para ese formato de 1 bit). No se midió el modelo. La línea se
   corrigió a mano en `logs/barrido_5rep.txt`.
2. No se modificó el script mientras se ejecutaba **a propósito**: bash lee el archivo a
   medida que avanza y editarlo en caliente puede romper la ejecución.
