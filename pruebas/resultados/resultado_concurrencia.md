# Concurrencia: cuánto rinde el intermediario con varios agentes a la vez (17-18/08/2026)

**Fecha**: 17/08/2026 · **Script**: `pruebas/rendimiento/medir_concurrencia.py`
**Config**: la de producción, sin tocar nada — 9B en GPU (:8080) y 30B (:8083)
cargados a la vez. 128 tokens por solicitud, `temperature 0`, prompts distintos
por agente (con el mismo prompt, el caché de prefijo falsearía el resultado).

**Por qué importa**: todas las mediciones anteriores del proyecto son de **una
solicitud a la vez**, pero el intermediario se concibe como sistema multiagente. Lo que decide
si eso funciona no es la velocidad de una solicitud sino el **rendimiento agregado**.

## Cada backend por separado

| agentes | 9B (GPU) agregado | vs 1 | por agente | | 30B agregado | vs 1 | por agente |
|---:|---:|---:|---:|---|---:|---:|---:|
| 1 | 51,5 | 1,00× | 58,9 | | 12,1 | 1,00× | 13,0 |
| 2 | 83,8 | **1,63×** | 46,3 | | 16,0 | **1,32×** | 8,7 |
| 4 | 88,7 | 1,72× | 48,0 | | 17,6 | **1,45×** | 4,6 |

**Los dos escalan, ninguno linealmente.** Poner un segundo agente en el 9B sube
el total 63% y le cuesta a cada agente bajar de 59 a 46 tok/s. El 30B sube 45%
con cuatro agentes, y cada uno cae de 13 a 4,6.

El 9B se estancó entre 2 y 4 agentes (1,63× a 1,72×) porque **tiene 2 slots**
(`--parallel 2` en su lanzador): la tercera y cuarta solicitud esperan turno. El 30B
tiene 4 slots y por eso sigue subiendo hasta 4.

## Los dos modelos trabajando al mismo tiempo

Ésta es la prueba que faltaba: 2 agentes en el 9B **y** 2 en el 30B, disparados
en simultáneo.

| | solo | conviviendo | costo |
|---|---:|---:|---:|
| 9B con 2 agentes | 83,8 | 77,9 | −7% |
| 30B con 2 agentes | 16,0 | 15,9 | −0,6% |
| **total del equipo** | | **93,8 tok/s** | |

**Convivir sale casi gratis.** Los dos modelos compiten por RAM y por CPU, y aun
así se estorban un 7% y un 0,6%. Con cuatro agentes repartidos entre los dos
modelos el equipo entrega **93,8 tok/s**, contra 51,5 de un solo agente en el
modelo más rápido: **1,8×** el rendimiento del mismo hardware.

Es el respaldo medido de la tesis del proyecto: en hardware limitado, repartir
trabajo entre modelos residentes rinde más que perseguir la velocidad de una
solicitud suelta.

## Corrección a lo que se creía

Se había supuesto que `backends/qwen3/iniciar-linux.sh`, al no declarar
`--parallel` ni `--cont-batching`, dejaba al 30B con un solo slot y serializaba
a los agentes. **Es falso**: `/props` reporta `total_slots: 4`. En este build el
valor por defecto es 4 y, **cuando no se declara `--parallel`**, `--ctx-size` es
**por slot**, no repartido — los cuatro slots tienen 8192 cada uno. Con `--parallel`
declarado, como en el 9B de abajo, `--ctx-size` es el total y se reparte.

## Subir los slots del 9B: de 2 a 4

Medido el mismo día, misma `--ctx-size 16384` total, solo cambiando
`--parallel 2` por `--parallel 4`:

| agentes | 2 slots (hoy) | 4 slots | mejora |
|---:|---:|---:|---:|
| 1 | 51,5 | 57,1 | — |
| 2 | 83,8 | 90,6 | +8% |
| 4 | 88,7 | **119,8** | **+35%** |

| | 2 slots | 4 slots |
|---|---:|---:|
| escalado a 4 agentes | 1,72× | **2,10×** |
| tok/s por agente con 4 | 48,0 | 32,5 |
| contexto por agente | 8192 | **4096** |
| VRAM | ~6900 MiB | 7333 MiB |

**El techo del 9B sube de 88,7 a 119,8 tok/s.** El precio no es VRAM (433 MiB
más) sino **contexto**: `--ctx-size` es el total y se reparte, así que cuatro
slots dan 4096 a cada agente en vez de 8192. Subir el total no cabe en 8 GB.

Con esto, el equipo completo pasa de ~94 a **~136 tok/s** con cuatro agentes en
el 9B y dos en el 30B.

**La decisión es agentes contra contexto**: cuatro agentes con 4096 de contexto
cada uno, o dos con 8192. Depende de cuánto contexto necesiten los agentes del
sistema multiagente — y hay que tener en cuenta que el intermediario les inyecta memoria
recuperada, que consume parte de ese contexto.

## Qué queda por probar

- **Latencia por agente**: aquí se midió rendimiento agregado. Con 4 slots cada
  agente baja a 32,5 tok/s; para un agente interactivo eso puede pesar más que
  el total del equipo.
- **Cuánto contexto usan de verdad los agentes**, para saber si 4096 basta.

---

## `--kv-unified`: un solo buffer KV para todos los slots (18/08/2026)

**Qué es**: `-kvu, --kv-unified` usa *un único buffer KV compartido entre todas
las secuencias* en vez de darle a cada slot su porción fija. Confirmado en el
log del servidor: `kv_unified = 'false'` sin la bandera, `'true'` con ella.

**Medido** en el backend 9B, `--parallel 4 --ctx-size 16384`, mismos prompts,
128 tokens por solicitud:

| agentes | sin `-kvu` | con `-kvu` |
|---:|---:|---:|
| 1 | 53,9 | 52,3 |
| 2 | 86,0 | 85,7 |
| 4 | **115,0** | **111,0** |
| **contexto por agente** | **4096** | **16384** |
| VRAM | 7727 MiB | 7733 MiB |

### El resultado: no es velocidad, es contexto

La velocidad **no cambia** (111,0 contra 115,0 está dentro del ruido de ±3 tok/s, y
en todo caso es levemente peor). Lo que cambia es el contexto: **de 4096 a 16384
tokens por agente, con 6 MiB más de VRAM**.

Eso resuelve el compromiso que había quedado abierto ayer. La disyuntiva era
"cuatro agentes con 4096 cada uno, o dos con 8192". Con KV unificado no hay que
elegir: cuatro agentes y el contexto entero para cada uno.

Precisión importante: 16384 es lo que **puede** usar cada agente, no lo que
tiene garantizado. Es una reserva única; si un agente consume el contexto, a los
otros les queda menos. Con lo medido en `resultado_contexto.md` (una solicitud real
usa 700-1300 tokens) una reserva de 16384 entre cuatro agentes sobra, y es mucho
mejor que un techo duro de 4096 por cabeza.

### La hipótesis del prefijo compartido era falsa

Se probó también con un `system` común de ~420 tokens para todos los agentes,
esperando que el KV unificado computara ese prefijo una sola vez:

| agentes | sin `-kvu` + prefijo | con `-kvu` + prefijo |
|---:|---:|---:|
| 1 | 42,8 | 40,6 |
| 2 | 72,3 | 72,1 |
| 4 | **98,3** | **90,4** |

**No deduplica el prefijo.** Con cuatro agentes es incluso peor (90,4 contra
98,3). Y el prefijo cuesta en las dos configuraciones: 98,3 contra 115,0 sin
prefijo, es decir, ~15% de rendimiento por enviarles a todos las mismas
instrucciones.

Si se busca ahorrar ese costo, el mecanismo no es éste sino `--cache-reuse`,
que sigue pendiente de medir.

### Recomendación

Añadir `--kv-unified` al lanzador del 9B **junto con** `--parallel 4`. Sin
`-kvu`, subir a 4 slots cuesta bajar el contexto a 4096; con `-kvu`, no cuesta
nada. Las dos banderas juntas dan 4 agentes, contexto completo y ~115 tok/s
agregados contra los 88,7 de la config actual de 2 slots.

---

## Aplicado en producción (18/08/2026)

Decisión tomada: **los agentes trabajan en paralelo**, así que se optimiza el
rendimiento del equipo y no la latencia de una solicitud suelta.

### Cambios

| archivo | cambio |
|---|---|
| `backends/principal/iniciar-linux.sh` | `--parallel 2` a `--parallel 4 --kv-unified` |
| `backends/qwen3/iniciar-linux.sh` | añade `--n-gpu-layers 0` explícito |
| esquemas del intermediario | declaran los parámetros estándar de OpenAI |
| construcción de la solicitud | los reenvía al backend |

En el lanzador del 30B **no** se declaró `--parallel`: sin esa bandera los slots
quedan en modo automático y eso habilita solo el KV unificado (verificado:
`kv_unified = 'true'`, 4 slots de 8192). Declararlo lo habría desactivado.

### Verificación

Estado real de los servidores después del cambio:

| | slots | ctx por agente | kv_unified |
|---|---:|---:|---|
| 9B (:8080) | 4 | **16384** | true |
| 30B (:8083) | 4 | 8192 | true |

VRAM total en uso: 6964 MiB de 8192.

**Concurrencia con la configuración nueva** (`medir_concurrencia.py`):

| agentes | agregado | por agente |
|---:|---:|---:|
| 1 | 45,0 | 53,5 |
| 2 | 89,3 | 47,8 |
| 4 | **118,0** | 32,2 |

118,0 contra los 88,7 de la configuración vieja: **+33%** con cuatro agentes.

**Parámetros del cliente**, probados de extremo a extremo contra el intermediario:

- `stop: ["4"]` sobre "enumera del 1 al 9" devolvió `1,2,3,` — se respeta.
- `seed: 777` con `temperature 1.2`: dos ejecuciones dieron `NexaFlow` las dos.
- `response_format` con `json_schema` devolvió JSON válido con las tres claves
  pedidas.

**Cuidado con `response_format`**: el tipo `json_object` **este build lo ignora** —
devuelve prosa, y se comprobó también consultando el backend directamente, así que no
es cosa del intermediario. El que sí funciona es `json_schema`. Si un cliente
espera modo JSON, tiene que enviar el esquema.

### Lo que se paga

Con los cuatro agentes activos cada uno baja de ~48 a ~32 tok/s. Es el precio
elegido a propósito: el equipo termina antes. Con un solo agente activo la
velocidad no cambia (53,5 contra 51,5 de antes).
