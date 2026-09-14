# Tres modelos pequeños residentes en VRAM — medido 23/07/2026

Toda la campaña previa midió **un modelo grande en GPU y los pequeños en RAM**. De ahí salió
la tesis de la campaña de medición: *el recurso abundante es la GPU y el escaso el ancho de banda
de RAM, así que repartir trabajo **hacia** la RAM paga el caro para ahorrar el barato*.

Las tres mediciones que la sostienen comparten el mismo montaje. Esta prueba aborda el
supuesto por el lado que faltaba: **qué pasa cuando la RAM no está en el circuito**.

Montaje: los tres con el binario CUDA, `-ngl 99`, `--fit off`, `--parallel 1`, ctx
explícito. Sin Bonsai: no cabe (ver §1).

| Puerto | Modelo | Rol |
|---|---|---|
| 8090 | Qwen3-4B-Q4_K_M | coordinador |
| 8091 | qwen2.5-coder-1.5b-instruct-q6_k | código |
| 8092 | Qwen3.5-2B-Q6_K | texto |

---

## 1. Sí caben los tres, pero por 272 MiB

| Modelo, cargado solo | VRAM que añade |
|---|---:|
| Qwen3-4B | 3395 MiB |
| Qwen3.5-2B | 2193 MiB |
| Coder-1.5B | 1761 MiB |
| Suma | 7349 MiB |

| Los tres a la vez (ctx 4096) | |
|---|---:|
| Escritorio, antes de cargar nada | 915 MiB |
| **VRAM total en uso** | **7920 MiB de 8192** |
| **Libre** | **272 MiB** |

Dos observaciones:

- **Juntos ocupan 344 MiB menos que la suma de sus partes** (7005 contra 7349 de deltas).
  Medido, no explicado: puede ser caché del driver que se cuenta en la carga individual.
  No se apoya ninguna conclusión en ese número.
- **Bonsai-27B queda fuera.*** Con ctx 8192 ocupa 5646 MiB (`resultado_convivencia.md` §1);
  con los pequeños suman ~12,5 GB sobre 8. La elección no es de diseño, la impone la GPU:
  **un cerebro grande o tres pequeños**.

---

## 2. Pasar un modelo pequeño de RAM a VRAM lo acelera entre 5 y 8 veces

Misma herramienta, mismo prompt, `ignore_eos` para que los tres generen **exactamente 400
tokens**, mediana de 3 repeticiones descartando el calentamiento.

| Modelo | En RAM | En VRAM | Factor |
|---|---:|---:|---:|
| Coder-1.5B | 26,5 t/s | **142,9 t/s** | 5,4× |
| Qwen3.5-2B | 17,5 t/s | **106,8 t/s** | 6,1× |
| Qwen3-4B | 11,8 t/s | **91,2 t/s** | 7,7× |

> **La base en RAM se volvió a medir a propósito.** Los números que ya existían no servían:
> `resultado_convivencia.md` daba 27,0 t/s para el Coder y `resultado_expertos.md` 22,6 t/s
> para el mismo modelo, con distinto prompt y distinto arnés. Elegir cualquiera de los dos
> como base habría sido elegir el número que conviene.

**Y la residencia es casi gratis:** el Coder da 142,9 t/s con la GPU vacía y 141,2 t/s con
los otros dos cargados pero ociosos. **−1 %.** Tener expertos esperando no cuesta velocidad;
cuesta VRAM.

---

## 3. El techo del caudal agregado también existe en la GPU

Esta era la pregunta que decidía. En RAM el caudal agregado **no crecía**: sumar un segundo
modelo repartía el trabajo en vez de multiplicarlo. La medición en VRAM, con los tres
generando a la vez y disparo simultáneo por barrera:

| | RAM (22/07) | VRAM (hoy, ctx 2048) |
|---|---:|---:|
| Un modelo solo | 27,0 t/s | 141,2 t/s |
| Dos a la vez | 24,0 t/s (0,89×) | 131,3 t/s (0,93×) |
| Tres a la vez | no se midió | 111,4 t/s (0,79×) |

**Es la misma forma, cinco veces más arriba.** Ejecutar N modelos a la vez nunca suma: en RAM
se pierde 11 % con dos, en VRAM 7 % con dos y 21 % con tres. La GPU no multiplica el caudal
por tener varios modelos cargados — **lo reparte, igual que la RAM**.

### La consecuencia para la tesis del informe

La tesis **no se derrumba, se corrige**. Lo que se midió en julio no era una propiedad de la RAM:
era la propiedad de **un único dispositivo atendiendo a varios modelos**. La RAM lo hacía
evidente porque su techo está bajo.

Lo que sí cambia es el **nivel absoluto**, y eso sí es una diferencia práctica: repartir
sigue sin multiplicar, pero cada trabajador va 5-8× más rápido. El costo del reparto deja
de estar dominado por el trabajador lento y pasa a estarlo por el coordinador.

---

## 4. El hallazgo que casi arruina la medición: llenar la VRAM al 97 %

La primera ejecución de la contención, con ctx 4096, dio un derrumbe que no encajaba con nada:

| Tres a la vez | VRAM libre | Caudal |
|---|---:|---:|
| ctx 4096 | 272 MiB | **57,9 t/s** |
| ctx 2048 | 641 MiB | **111,4 t/s** |

Tres juntos rendían **menos de la mitad que uno solo** — degradación superlineal, que no es
lo que produce repartir cómputo. **369 MiB más de margen casi duplican el caudal.**

> **Regla práctica: no llenar la VRAM más allá de ~92 %.** El último 5 % de memoria cuesta
> la mitad del rendimiento, y no avisa: los tres servidores inician bien, responden bien,
> y simplemente van lentos. Es exactamente el tipo de defecto que sobrevive a un despliegue
> porque nada falla.

Si esta prueba no se hubiera repetido con más margen, el informe habría publicado 57,9 t/s
como "la contención en GPU" y habría concluido, falsamente, que la GPU se degrada mucho peor
que la RAM.

---

## 5. Calidad: un 4B en VRAM empata con el 27B

Las mismas 25 tareas de `eval_expertos.py`, verificadas **por ejecución**. El banco está
respaldado por `verificar_bateria.py` (25/25 con implementaciones de referencia), así que un
fallo es del modelo.

| Modelo | Dónde | Aciertos | | Velocidad |
|---|---|---:|---:|---:|
| **Bonsai-27B-Q1_0** | VRAM | **22/25** | 88 % | 31,6 t/s |
| **Qwen3-4B-Q4_K_M** | VRAM | **21/25** | 84 % | **91,0 t/s** |
| Coder-1.5B | VRAM | 18/25 | 72 % | 137,9 t/s |
| Coder-1.5B | RAM | 18/25 | 72 % | 22,6 t/s |
| Qwen3.5-2B | VRAM | 16/25 | 64 % | 103,9 t/s |
| Qwen3.5-2B | RAM | 14/25 | 56 % | 16,6 t/s |

### La comparación que el proyecto nunca había hecho

**Bonsai-27B nunca había sido puntuado en el banco.** Ahora lo está, y el resultado es el
más importante de esta medición:

| Bonsai acierta y el 4B no | El 4B acierta y Bonsai no |
|---|---|
| fizzbuzz, duracion, comprimir (3) | aplanar, intervalos (2) |

**McNemar exacto bilateral: p = 1,000.** Los dos modelos son **indistinguibles** en este
banco. Y el 4B va **2,9× más rápido** y deja **3,8 GB de VRAM libres** para otra cosa
(4310 MiB en uso contra los 5646 de Bonsai).

> El 27B tiene casi siete veces más parámetros, pero está cuantizado a Q1_0 para entrar en
> 8 GB. Contra un 4B a Q4_K_M, esa ventaja de tamaño **no aparece en el resultado**. Lo que
> se paga en parámetros se pierde en precisión.

### Control: pasar de RAM a VRAM no cambia la calidad

- **Coder-1.5B: 18/25 en RAM y 18/25 en VRAM, fallando exactamente las mismas 7 tareas.**
  Idéntico. El cambio de ubicación modificó la velocidad 6,1× y nada más — el montaje está bien.
- **Qwen3.5-2B: 14/25 → 16/25** (`transpuesta` y `bytes` pasaron a aprobar).

Ese segundo caso da una medida del **ruido entre ejecuciones: ±2 tareas*** a temperatura
0,1. Vale la pena tenerlo presente: la brecha de 4 tareas entre especialista y control que
`resultado_expertos.md` dejó en p=0,29 es apenas el doble del ruido.

### `camel`: la fallan los 6 modelos, y no es culpa del banco

Sospeché del enunciado y lo revisé. Los cuatro códigos son **cuatro errores distintos**:

| Modelo | Qué hizo mal |
|---|---|
| Bonsai-27B | `s[0].lower()` — confunde el primer **carácter** con la primera **palabra** |
| Qwen3-4B | quita los guiones bajos pero **nunca capitaliza** |
| Coder-1.5B | capitaliza **todas** las palabras, incluida la primera |
| Qwen3.5-2B | parte por **espacios** en vez de guiones bajos |

Ninguno cae en un caso borde no declarado: los cuatro entienden mal la consigna de una forma
diferente. Es capacidad, no ambigüedad.

---

## 6. Modo equipo en VRAM: 5× más rápido, mismo veredicto

Misma solicitud de tres partes que en `resultado_equipo.md`, mismo presupuesto (1400 por
trabajador, 2800 para unificar). **Sustitución declarada:** coordina **Qwen3-4B**, no
Bonsai-27B, porque Bonsai no cabe junto a los trabajadores. El equipo baja de capacidad en
el rol más exigente, así que esto compara *montajes completos*, no *ubicaciones de memoria*.

Montaje: coordinador ctx 8192 con KV en q8_0, trabajadores ctx 2048. VRAM 7877 MiB.

| Camino | Tiempo |
|---|---:|
| Equipo, trabajadores en RAM (`resultado_equipo.md` §5) | 160,4 s |
| **Equipo, trabajadores en VRAM** | **30,2 s** (y 28,6 s en la otra ejecución) |
| **Directo: el coordinador solo, mismo presupuesto** | **11,0 s** |

Desglose del equipo: repartir 1,2 s · trabajo en paralelo 17,3 s · unificar 11,8 s.

**Pasar el equipo a VRAM lo aceleró 5,3×.*** Pero el camino directo se aceleró lo mismo, así
que **la proporción no se movió: el equipo sigue costando 2,7× el camino directo** — el
mismo 2,7× que dio en RAM (84,8 s contra 31,5 s).

> **Esta es la comparación justa que quedó pendiente desde julio.** `resultado_equipo.md` §6
> registraba que los 31,5 s del camino directo se habían medido con 900 tokens contra 2800 del
> equipo, y que sin igualar presupuestos no se podía cerrar el costo-beneficio. Ahora los dos
> caminos se ejecutaron con **el mismo presupuesto**: 30,2 s contra 11,0 s.

### Por qué el reparto no gana aunque los trabajadores sean muy rápidos

Los dos costos que lo perjudican **no dependen de dónde residan los modelos**:

1. **El paralelo termina con el más lento** (17,3 s de los 30,2).
2. **El coordinador paga dos llamadas extra** (1,2 s de reparto + 11,8 s de unificación =
   13,0 s, es decir, **43 % del total**), y esas son secuenciales por definición.

Acelerar 5× a los trabajadores acelera 5× las dos partes por igual. La estructura del costo
es la misma.

### El defecto estructural del reparto: subtareas que no se bastan solas

El coordinador le pasó al tercer trabajador:

> *"Crear 4 casos de prueba para verificar el funcionamiento correcto de **la función**."*

**Sin decir cuál función.** Su propio prompt (`P_REPARTIR`) exige descripciones
"autocontenidas", y aun así lo incumplió. El trabajador avisó que le faltaba contexto e
inventó una función `sumar(a, b)`; entregó cuatro casos de prueba de una suma de dos números.

Esto **no es un accidente, es la restricción del paralelismo**: las tres subtareas se lanzan
a la vez, así que "escribe casos de prueba para la función" no puede ver la función que
todavía se está escribiendo. En ejecución secuencial el problema no existiría.

**La unificación lo detectó:*** la respuesta final descartó los casos de `sumar(a, b)` y
escribió cuatro sobre el CSV. Pero eso significa que **un tercio del trabajo paralelo se descartó
y el coordinador lo rehízo solo*** — pagando el reparto para después no usarlo.

### Y sin embargo el equipo entregó mejor código

| | Equipo (30,2 s) | Directo (11,0 s) |
|---|---|---|
| Agrupa por | `dt.to_period('M')` | `fecha.split('-')[1]` |
| Enero 2023 + enero 2024 | separados | **fusionados** |
| Casos de prueba | incluye uno para el borde de año | ninguno lo prueba |
| Coherencia | explica el diccionario pero **usa un DataFrame** | usa diccionario, como pidió el enunciado |

**Verificado ejecutando** el código del camino directo con enero de 2023 (100) y enero de
2024 (200): devuelve `{'01': 300.0}`. **Es el mismo bug de colapso de años que la primera
ejecución del equipo propagó en julio*** — ahora aparece en el camino directo, y el equipo es el
que lo evita.

Así que el balance no es limpio en ninguna dirección: **el equipo tarda 2,7× más y entrega
código correcto donde el directo entrega código con un bug real; y el directo responde el
enunciado con más fidelidad** (le pidieron un diccionario y usó un diccionario).

---

## 7. Conclusión: qué cambia y qué no

**Lo que cambia — y es mucho:**

Un modelo pequeño en VRAM va **5 a 8 veces más rápido*** que el mismo modelo en RAM, con
**calidad idéntica** (el Coder falló exactamente las mismas 7 tareas en los dos lugares). Y
un **Qwen3-4B en VRAM empata con Bonsai-27B** en el banco de 25 tareas (21/25 contra 22/25,
McNemar p=1,000) yendo **2,9× más rápido**. Eso vuelve discutible la decisión de fondo del
proyecto: dedicar los 8 GB a un 27B cuantizado a Q1_0 no compra capacidad medible frente a
un 4B a Q4_K_M que deja 3,8 GB libres.

**Lo que no cambia:**

El techo del caudal agregado. Ejecutar varios modelos a la vez **nunca suma**, ni en RAM ni en
VRAM: 27,0→24,0 t/s en RAM, 141,2→131,3→111,4 t/s en VRAM. La tesis de la campaña de medición no se
derrumba, **se corrige**: lo que se midió en julio no era una propiedad de la RAM sino de **un
único dispositivo atendiendo a varios modelos**. La RAM lo hacía evidente porque su techo
está bajo.

Y el reparto de trabajo sigue sin convenir por la misma razón que antes, pero ahora medido
con presupuestos iguales: **2,7× el costo del camino directo**, con el **43 % del tiempo**
gastado en las dos llamadas del coordinador, que son secuenciales por definición.

> **La recomendación práctica se invierte respecto de lo que venía haciendo el proyecto.**
> No "un cerebro grande en GPU y expertos pequeños en RAM", sino **los expertos pequeños en VRAM
> y turnándose*** — que es exactamente lo que hace el enrutador. La residencia simultánea
> cuesta 1 % de velocidad; el paralelismo cuesta 21 %. Cargarlos todos y usarlos de uno en uno es
> la configuración que gana.

---

## 8. Lo que este experimento NO resuelve

- **No decide "grande contra pequeños" en general.*** Decide en 8 GB, con estos cinco modelos y
  este banco de 25 tareas. La comparación Bonsai-vs-4B dio p=1,000: eso significa
  *indistinguibles en esta muestra*, no *equivalentes*. Con 50-60 tareas —lo que ya estaba
  pendiente para cerrar el caso especialista-vs-control— podría separarse.
- **El ruido entre ejecuciones es ±2 tareas*** (medido: Qwen3.5-2B dio 14/25 y 16/25 con el
  mismo modelo y el mismo banco). Cualquier brecha menor a eso no significa nada.
- **La sustitución del coordinador ensucia la fase 4.** El equipo de julio lo coordinaba
  Bonsai-27B; este lo coordina Qwen3-4B. Un resultado peor no probaría que el reparto en VRAM
  falla, y uno mejor tampoco probaría lo contrario.
- **Una sola ejecución del modo equipo por montaje.*** Los 30,2 s y los 28,6 s dan una idea de la
  dispersión, pero la comparación de calidad (bug de años sí/no) se apoya en **un caso**. Es
  exactamente el tamaño de muestra que ya engañó una vez en este proyecto, cuando 3/3 parecía
  100 % de detección del supervisor y con 18 errores resultó 56 %.
- **No se probó la supervisión en este montaje.** Sin Bonsai residente el supervisor tendría
  que ser un modelo pequeño, y eso es otro experimento.
- **No se midió el inicio en frío.*** Si cargar un experto en VRAM tarda pocos segundos,
  quizá no haga falta tenerlos los tres residentes — y ahí cabrían modelos más grandes.
