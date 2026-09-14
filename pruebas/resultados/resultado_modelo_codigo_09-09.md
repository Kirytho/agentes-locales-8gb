# ¿Ornith o K2 para el MCP? — medido 09/09/2026

Cada número sale de **65 ejecuciones** (13 tareas × 5 repeticiones), mismo banco,
mismo oráculo por ejecución, sin especulación en ninguno.

```
modelo                       GB   VRAM  edicion  rompio  formato  funcion  scripts
Ornith-1.5-9B-MTP-IQ4_XS   5.08   5671    62/65     1      50/65    47/53      4/4
K2-Horizon-7B-Q4_K_S       5.00   6142    61/65     0      62/65    48/53      3/4
```

## Decisión: se queda K2

|  | Ornith | K2 | Fisher p | |
|---|---:|---:|---:|---|
| edición | 62/65 | 61/65 | 1,000 | empatan |
| **formato con bloques** | **50/65** | **62/65** | **0,0041** | **K2 mejor** |
| aplica | 50/65 | 60/65 | 0,0268 | K2 mejor |
| rompió regresión (con bloques) | 1 | 3 | 0,619 | empatan |

**Editando son indistinguibles. Emitiendo bloques SEARCH/REPLACE no: 95% contra
76%.**

Eso pesa porque decide el tamaño de archivo que el modelo puede tocar. Un modelo
que falla el formato 24% de las veces cae a reescribir entero en 1 de cada 4
llamadas, y ahí el techo baja de ~1.470 líneas a ~630.

## Lo que Ornith tiene a favor, y no alcanzó

- **471 MiB menos de VRAM** (5.671 contra 6.142). Real, pero solo sirve si se
  traduce en un escalón más de contexto, y a ctx 16.384 caben los dos.
- **Es determinista.** Cinco ejecuciones a `temperature 0` con `seed` fijo dan la
  misma respuesta; K2 da cinco distintas. Para una herramienta cuya premisa es
  "no leo el resultado, confío en los tests", la reproducibilidad no es un
  detalle — pero no compensa 19 puntos de formato.

## Dos veces me equivoqué leyendo una sola ejecución

| | 1 repetición | 5 repeticiones |
|---|---|---|
| edición | Ornith 13/13 vs K2 11/13 → "Ornith gana por buen margen" | 62/65 vs 61/65, p=1,0 → **empatan** |
| formato | Ornith 12/13 = 92% → "parecido a K2" | 50/65 = 76% vs 95% → **K2 mejor, p=0,004** |

La primera vez el ruido favoreció a Ornith; la segunda lo perjudicó al revés de
lo que yo había reportado. **Una ejecución no es una medición** — y el error no es
sistemático, así que no se puede corregir "a ojo" en ninguna dirección.
