# Hermes contra modelos en Kaggle — medido 11/09/2026

La idea del usuario: **que los modelos hagan todo, sin harness de pago**. Hermes
maneja el bucle desde la computadora local, el intermediario enruta y el modelo
se ejecuta en una GPU de Kaggle.

Instrumento: `pruebas/calidad/eval_stack_completo.py` — 5 escenarios con oráculo
sobre disco y el grabador registrando el tráfico. El mismo del que salieron las
600 ejecuciones del barrido de cuantizaciones.

## Resultado

```
                    total  activos  cuant  VRAM     tok/s   informe invent. reparto exacto contexto  total
Ornith 1.5 9B (PC)    9B     9B      IQ4    7,2 GB   41,4     MAL     MAL      OK     OK      OK      3/5
Gemma 4 12B          12B    12B      Q8      14 GB   17,7     MAL     OK       OK     OK     MAL      3/5
Qwen3.8 27B          27B    27B      Q5      25 GB   13-15    OK      OK       OK     OK      OK      5/5
Gemma 4 26B-A4B      26B     4B      Q5    22,2 GB   46,7     OK      OK       OK     OK     MAL      4/5
```

**La cadena funciona.** Hermes → intermediario → túnel → Kaggle resolvió los 5
escenarios con Qwen3.8-27B, sin intervención del harness de pago. Cero
herramientas narradas, cero corrupción de los datos de entrada.

## Lo que se aprendió

**El problema de Ornith era TAMAÑO, no cuantización.** Gemma 12B a **8 bits**
—sin pérdida de cuantización— también falla `informe`. Si fuera precisión, ese
lo resolvería.

**El MoE rompe la relación tamaño/velocidad.** Gemma 26B-A4B es el más grande y
el **más rápido** (46,7 tok/s, por encima del 9B denso), porque activa 4B de 26B
por token. Resuelve los 4 primeros escenarios en un tercio del tiempo que Qwen.

**`contexto` separa por familia, no por tamaño.** Las dos Gemma nombran **0 de
8**; Ornith 9B y Qwen 27B nombran 8/8. Un modelo de 9B lo resuelve y uno de 26B
no. No parece capacidad — parece algo propio de Gemma con contextos largos.
Pendiente de investigar con la grabación del tráfico.

**El bug de tool calls de Gemma 4 está CORREGIDO.** El proyecto lo tenía
registrado como bloqueante desde agosto ("narra en vez de llamar"). Con el
llama.cpp de hoy emite la llamada nativa correctamente, verificado en las dos
Gemma.

**El borrador MTP da +50% con salida idéntica.** Medido en Qwen3.8-27B: 10,2 →
15,3 tok/s, hashes iguales en repeticiones. Contrasta con `ngram-cache`, que el
09/09 daba +48% y bloqueaba el backend. Este resistió los 37 intercambios del
banco.

## Lo que hay que aceptar

- **12 h por sesión, 30 h por semana.** Laboratorio, no backend diario.
- **Los túneles rápidos de cloudflared se caen.** Pasó dos veces. La primera
  contaminó una ejecución entera: los tres escenarios que faltaban dieron MAL con
  0 llamadas, y parecía culpa del modelo. Eran 6 respuestas HTTP 530.
- **La URL es pública y sin contraseña**, y por ahí viaja el contenido de los
  archivos.
- **No mezclar estos números con los de la GPU local:** otro hardware, otro
  motor (upstream contra el fork buun, que rinde +45%).

## Trampas de Kaggle, para no repetirlas

**Dos rutas distintas de `libcuda`, y confundirlas cuesta la tarde:**

```
para COMPILAR   /usr/local/cuda/compat/libcuda.so     570.124.06 (vieja)
para EJECUTAR   /usr/local/nvidia/lib64/libcuda.so.1  580.159.04 (el driver real)
```

Con la de `compat` al iniciar, CUDA no se inicializa y el modelo se ejecuta **en
CPU a 3 tok/s con la GPU vacía**, indicando "servidor activo" como si nada. Lo
delató medir la velocidad, no comprobar si respondía.

**`cmake` no encuentra `CUDA::cuda_driver`** porque `libcuda.so` no está en
`lib64` ni en `stubs`. Se soluciona con un enlace a `compat/` y
`-DCMAKE_LIBRARY_PATH`.

**`/kaggle/working` tiene 20 GB de tope** y `hf_hub_download(local_dir=...)`
guarda el archivo **por duplicado**: un modelo de 5 GB ocupaba 19 y el disco
quedó al 100% sin dar ningún error. Los modelos van a la caché por defecto, en
el overlay con 1 TB.

**`pkill -f llama-server` mató el túnel.** `cloudflared` tenía esa cadena en su
línea de comandos. Es la regla que el proyecto tiene escrita desde el 08/09 y se
volvió a incumplir. Se usa `pkill -x`, que compara el nombre exacto del proceso.

---

## Qué pasó realmente en `contexto` (revisado con la grabación del tráfico)

El escenario da ocho `servicio.py` de ~540 líneas (4.301 en total). Cada uno
tiene decenas de funciones de relleno —generadas como `nombre_N`, con firma
larga idéntica— y **exactamente una defectuosa, con nombre propio sin sufijo**.

**Gemma 26B-A4B respondió las ocho**, con formato perfecto:

```
inventario: contar_items_13
facturacion: dividir_lotes_0
envios: leer_config_5
...
```

**Las ocho son nombres de relleno.** No fue "no respondió": fue responder con
seguridad ocho respuestas equivocadas.

### Por qué

No leyó el código. Escribió **cinco programas con regex** (`execute_code` ×5)
para detectar el defecto automáticamente, buscando patrones en las firmas. Como
todas las de relleno comparten la misma firma, su heurística tomó cualquiera.

El defecto es **semántico**: hay que entender qué hace la función. Ninguna regex
lo encuentra.

Pista de por qué eligió ese camino: sus dos `read_file` fueron sobre
`~/.hermes/cache/spillover/…`, el mecanismo de Hermes para salidas demasiado
grandes. **El contenido no le cabía**, y optó por el atajo.

### Lo que corrige

**No es un fallo de contexto largo**, como parecía por el nombre del escenario.
Es una **decisión de estrategia**: resolver con herramientas en vez de leyendo.
Las dos Gemma la tomaron igual; Ornith 9B y Qwen 27B leyeron y razonaron, y
obtuvieron 8/8.

**Y es la advertencia más útil del día para el proyecto:** un agente que resuelve
*programando la respuesta* en vez de mirando el material es rápido, convincente,
y se equivoca con total seguridad. El oráculo que ejecuta y verifica lo detectó;
una revisión por lectura no lo habría hecho.

---

## K2-Horizon-MoVA-36B-A4B: prometedor, pero el motor falla (11/09/2026)

El miembro **disperso** de la familia K2 — la misma que el 7B del MCP.

```
36B totales · 4B activos por token · 48 capas · contexto 524.288 nativo
MoE:   100 expertos por capa, 8 activos + 1 compartido
MoVA:  64 expertos de VALOR por capa de atención, 4 activos
```

**Qué es MoVA.** Mixture-of-Values aplica el enrutado disperso **dentro de la
atención**: las proyecciones de valor se reemplazan por un banco de expertos y
solo se activan unos pocos por token. Es ortogonal al MoE del feed-forward — el
7B que usamos en el MCP tiene MoVA y `expert_count: 0`, es decir, atención
dispersa y feed-forward denso.

### Lo que llegó a mostrar, y es bueno

| | |
|---|---|
| tool calls | nativas y bien formadas |
| velocidad | **40,7 tok/s** con 36B de capacidad |
| VRAM | 25,9 GB de 30,7 (Q4_K_M; Q5 no habría cabido) |
| código | la **única** solución correcta de `mayores` entre todos los probados: `sorted(pares, key=lambda x: (-x[1], x[0]))[:n]` |

Gemma 26B-A4B y Spark cayeron los dos en `len(x)` sobre una tupla, que siempre
vale 2.

### Por qué no se pudo medir

```
ggml_cuda_compute_forward: CLAMP failed
CUDA error: an illegal memory access was encountered
  en ggml-cuda.cu:2412
```

**Acceso fuera de rango dentro de un kernel CUDA** — un bug, no falta de memoria
(sería `cudaMalloc failed`). Las primeras tareas se ejecutan perfectamente y falla
a los pocos minutos.

Se probó `--parallel 1` sin `--kv-unified`, sospechando del camino de slots
concurrentes: **mismo fallo, al minuto y medio**. No es la concurrencia.

La rama `model/K2Horizon` del fork MBZUAI-IFM es del **1 de septiembre**, y el
propio README del modelo dice *"PR in progress as of September 2026"*. El soporte
de MoVA tiene diez días.

### Qué hacer

**Esperar.** Es el mejor candidato que se vio —familia que ya sabemos que
programa bien, 36B de capacidad, 4B de velocidad, 512K de contexto— pero no es
medible ni usable con el motor de hoy.

Vale la pena volver a probarlo cuando el soporte llegue a upstream o el fork
avance.

---

## K2-MoVA 36B-A4B, segunda ronda: 5/5, sin fallos (12/09/2026)

La sesión siguiente de Kaggle, **con la configuración exactamente igual**, ejecutó
el banco entero sin un solo `CLAMP`.

```
informe      44,5s   2 vueltas    1 llamada    OK
inventario   18,7s   3 vueltas    2 llamadas   OK
reparto      19,6s   2 vueltas    1 llamada    OK
exacto       18,2s   3 vueltas    2 llamadas   OK
contexto    626,1s  18 vueltas   29 llamadas   OK -- nombró 8/8

ACIERTOS 5/5 · 45 llamadas reales · 0 narradas · 0 firmas del bug 22786
```

### Es el mejor resultado de toda la serie

| modelo | activos | VRAM | tok/s | aciertos |
|---|---:|---:|---:|---:|
| Ornith 1.5 9B (local) | 9B | 7,2 GB | 41,4 | 3/5 |
| Gemma 4 12B | 12B | 14 GB | 17,7 | 3/5 |
| Gemma 4 26B-A4B | 4B | 22,2 GB | 46,7 | 4/5 |
| Qwen3.8 27B + MTP | 27B | 25 GB | 13-15 | 5/5 |
| **K2-Horizon-MoVA 36B-A4B** | **4B** | 25,9 GB | **40,7** | **5/5** |

Iguala a Qwen3.8 en aciertos yendo casi 3x más rápido, porque activa 4B por
token en vez de 27B.

### `contexto` no fallaba: se le acababa el tiempo

En la primera ejecución dio MAL con `NO TERMINO (300s de tope)` y `0/8 nombradas`.
Repetido con `BANCO_LIMITE=900` lo resolvió **entero** en 626 s.

Los otros cuatro escenarios terminan en 18-45 s. Este modelo resuelve la lectura
larga, pero tarda diez minutos: el tope de 300 s que sirve para los demás lo
detenía injustamente. **Un "no terminó" no es un fallo de capacidad** — hay que
repetirlo con un tope más amplio antes de registrarlo.

### Por qué no falló: no se sabe

Se comparó contra la transcripción de la sesión anterior. Idéntico en todo:

```
anoche (crash)   CTX 65536  cache q4_0/q4_0  --parallel 1 --flash-attn auto --cont-batching
hoy   (5/5 OK)   CTX 65536  cache q4_0/q4_0  --parallel 1 --flash-attn auto --cont-batching
```

Mismo GGUF, mismas banderas, **binario sin recompilar**. Quedan tres causas
posibles y ninguna está descartada:

1. **Otra máquina.** Kaggle asigna un nodo distinto por sesión; dos T4 no son la
   misma T4.
2. **La descarga anterior estaba dañada.** La celda hace `rmtree` de la caché y
   vuelve a descargar el GGUF, y la noche anterior el disco se había llenado al
   100% por las copias dobles de `hf_hub_download`. Un GGUF truncado produce
   exactamente un acceso fuera de rango.
3. **El bug es intermitente**, dependiente de longitudes de secuencia concretas.

**No está corregido: no se manifestó.** No se modificó nada, así que no hay motivo
para creer que no vuelva. Para descartar la causa 2 basta guardar el `sha256` del
GGUF en la celda de descarga y compararlo el día que vuelva a fallar.

### Dos trampas del instrumento, encontradas de paso

**El banco pide `-m principal` por defecto** (`BANCO_MODELO`). Con el backend
primario en otro lugar mide el modelo equivocado. Esta vez se notó solo porque el
backend principal local está a ctx 16.384 y Hermes lo rechaza:

```
Model principal has a context window of 16,384 tokens, which is below the
minimum 64,000 required by Hermes Agent.
```

Con un backend local de contexto grande habría medido en silencio el backend
equivocado.

**Y `backend_vivo()` no lo detectó**, porque el transporte estaba perfecto: el
túnel devolvía 200. El fallo estaba un nivel más arriba. El banco informó `0/5`
con apariencia de resultado válido, y la única señal era el tráfico en cero:

```
CABLE     vueltas=0 llamadas_reales=0
CONTEXTO  herramientas ofrecidas=0  prompt de sistema=0 chars
```

**Un 0/5 con `peticiones=0` nunca es un resultado, siempre es el instrumento.**
Conviene que el banco se detenga por sí solo cuando no registró ni una petición.
