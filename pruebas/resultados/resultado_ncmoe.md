# MoE híbrido (`-ncmoe N`) sobre Qwen3-30B-A3B

**Fecha**: 17/08/2026
**Modelo**: Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL (48 bloques, 128 expertos, 8 activos)
**Hardware**: RTX 3060 Ti 8 GB · Ryzen 5 3600XT · 32 GB DDR4-3000
**Script**: `pruebas/rendimiento/medir_ncmoe.py` · **Crudos**: `resultado_ncmoe.json` (+ `_run1`)
**Método**: 2 repeticiones × 3 prompts, `temperature 0`, ctx 8192, 6 hilos.

## Resultado

| config | gen tok/s | min | max | vs CPU puro | prompt tok/s | VRAM |
|---|---:|---:|---:|---:|---:|---:|
| `cpu-puro` (`-ngl 0`) | 14,4 | 13,3 | 15,5 | — | 27,5 | 783 MiB |
| `autofit` (sin banderas) | 28,2 | 25,9 | 29,6 | **+96%** | 61,6 | 6765 MiB |
| `-ncmoe 34` | 28,6 | 25,1 | 29,8 | **+99%** | 65,7 | 6993 MiB |
| **`-ncmoe 32`** | **30,8** | 28,1 | 31,6 | **+114%** | 68,9 | 7639 MiB |
| `-ncmoe 30` | no inicia — no cabe en VRAM | | | | | |

El barrido completo (`_run1`) mostró la escalera limpia: cuanto más se envía a
la GPU, más rápido. 21,2 tok/s con todos los expertos en RAM (`-ncmoe 48`,
2272 MiB) subiendo ~1 tok/s cada dos bloques hasta 30,8 con `-ncmoe 32`.

**El techo es la VRAM, no otra cosa**: `-ncmoe 32` deja la GPU en 7639 de
8192 MiB y `-ncmoe 30` ya no carga. La curva seguía subiendo cuando se acabó
la memoria.

## Lo que cambia el diagnóstico del proyecto

**El "backend de CPU" nunca fue de CPU.** El lanzador
`backends/qwen3/iniciar-linux.sh` no pasa `--n-gpu-layers`, y sin esa bandera
llama-server **no** se queda en CPU: el ajustador automático envía a la GPU
lo que quepa. Medido aquí: 6765 MiB de VRAM y 28,2 tok/s.

Los 16,7 tok/s que figuraban en el registro de estado del proyecto no son "la velocidad del modelo en
RAM": son la velocidad **cuando el 9B ya ocupaba la GPU*** y el ajustador no
encontró hueco. El número honesto de CPU pura, con `CUDA_VISIBLE_DEVICES=""`
para que ni siquiera reserve buffers, es **14,4 tok/s**.

Es decir, hoy el 30B se ejecuta a una velocidad u otra según si el otro modelo está
cargado, sin que nada en el proyecto lo diga.

## La decisión que esto plantea

No es "comprar más VRAM". Es **elegir entre dos modelos residentes o uno solo**:

| | 9B (código) | 30B (razonamiento) |
|---|---:|---:|
| hoy, los dos cargados | 57 tok/s | 16,7 |
| solo el 30B, con `-ncmoe 32` | no disponible | **30,8** |

El razonamiento tarda **la mitad** si el 9B no está. Con 8 GB no caben los
dos: `-ncmoe 32` pide 6,9 GB para el 30B y el 9B pide 6,1 GB.

Eso convierte el "gestor de carga de modelos" de idea vaga en una pieza con
número: cargar y descargar según el perfil vale +114% en las tareas de
razonamiento. El costo es el tiempo de cambio (recargar 21,6 GB desde disco) y
la complejidad de manejar una solicitud en curso mientras se cambia.

## Pendiente antes de aplicarlo: verificar la calidad

**La salida no es reproducible en este modelo.** Con `temperature 0` y `seed`
fijo, dos solicitudes idénticas al mismo servidor dieron texto distinto (ver los
hashes en `resultado_ncmoe.json`: `autofit` dio `b63873` y `bf04f2` para el
mismo prompt). Pasa en GPU y también, en menor medida, en CPU.

Consecuencia: **el control por hash no sirve aquí***, y no se puede afirmar que
mover expertos a la GPU deje la respuesta igual. Por eso se verificó con la
batería, que mide resultado y no texto exacto.

## Verificación de calidad: la batería, 3 ejecuciones (17/08/2026)

| | código | razonamiento | velocidad |
|---|---:|---:|---:|
| histórico CPU (`base-cpu-qwen3-30b-a3b`, 3 ejecuciones) | 25 · 25 · 25 → **25,0/25** | 4 · 4 · 3 → 3,7/4 | 16,6 tok/s |
| `-ncmoe 32` (3 ejecuciones) | 25 · 25 · 25 → **25,0/25** | 3 · 4 · 4 → 3,7/4 | **30,3** (27,9-33,6) |

**Misma calidad, +82% de velocidad.** Dispersión de 0 puntos en código: las tres
ejecuciones dieron 25/25, igual que el histórico. El razonamiento da la misma media
(3,7/4) y falla en una de tres en ambos casos — es la misma variabilidad de
siempre, no una degradación por mover expertos a la GPU.

Nota: el código está en el techo de la batería (25/25 en las dos
configuraciones), así que este control detecta una degradación, no una mejora.
Para eso haría falta la batería ampliada que sigue pendiente.

**Conclusión: `-ncmoe 32` es seguro de aplicar**, con la única condición de que
la GPU esté libre — es decir, que el 9B no esté cargado.
