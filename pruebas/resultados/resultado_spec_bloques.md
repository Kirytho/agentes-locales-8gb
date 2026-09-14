# Especulación con la carga del MCP (bloques SEARCH/REPLACE) — 09/09/2026

**Rehace** `resultado_spec.md` (17/08), que midió otro modelo y otra forma de
trabajo. Script: `pruebas/rendimiento/medir_spec.py`, más comprobaciones
aisladas de una solicitud a la vez.

## Resultado en una línea

**`ngram-cache` da +48% editando, con salida byte a byte idéntica. Las otras
tres devuelven código roto.**

## Lo que casi se reporta mal

El banco marcó `suffix +68,8%`, el número más grande de la tabla. Estaba
**generando basura más rápido**:

```
- resultado.append(item['valor'] + 100)
- return resultado
- >>>>>>> REPLACE
+ resultado.append(item['valor'] + 100:      <- sintaxis rota
+ resultado.append(item['valor']             <- cortado, sin cerrar el bloque
```

Una solicitud a la vez, sobre Ornith, 3 ejecuciones de cada una:

| config | igual al baseline | bloques válidos |
|---|---:|---:|
| baseline | 3/3 | 3/3 |
| **ngram-cache** | **3/3** | **3/3** |
| copyspec | 0/3 | 0/3 |
| suffix | 0/3 | 0/3 |
| recycle | 0/3 | 0/3 |

`copyspec`, `suffix` y `recycle` devuelven **bloques incompletos siempre**. Lo
único que lo delató fue el control de igualdad de salida que el banco traía del
17/08; sin él se habría reportado un +68,8% que rompe todo. En el motor `bin-k2`
`copyspec` ni siquiera inicia el servidor.

## La velocidad, aislada y con 5 ejecuciones

| modelo | carga | baseline | ngram-cache | | salida |
|---|---|---:|---:|---:|---|
| Ornith | editar con bloques | 67,3 | **99,8** | **+48,2%** | idéntica |
| Ornith | generar desde cero | 66,5 | 63,6 | −4,4% | idéntica |
| K2 | editar con bloques | 64,0 | **110,8** | **+73,0%** | 4/5 válidos, igual que su baseline |

Por eso se activa **solo en el modo de código** y no por defecto: ayuda cuando la
respuesta repite texto de la solicitud, y estorba cuando se genera desde cero. El
uso general genera más de lo que edita.

## La hipótesis previa estaba al revés

Se esperaba que los bloques **mataran** la ventaja de la especulación, porque el
archivo ya no vuelve en la respuesta. Es al contrario: el trozo `SEARCH` **es**
una copia literal del archivo que está en la solicitud, así que los bloques son
*más* favorables a adivinar por repetición que reescribir el archivo entero.

## Hallazgo aparte: K2 no es determinista

Con `temperature 0` y `seed` fijo, cinco ejecuciones de K2 dan cinco respuestas
distintas (1/5 iguales). Ornith con las mismas banderas es determinista (5/5).
Además K2 emite un bloque inválido 1 de cada 5 veces **sin especulación**, lo
que encaja con el 95% de cumplimiento de formato medido esa mañana sobre 65
ejecuciones.
