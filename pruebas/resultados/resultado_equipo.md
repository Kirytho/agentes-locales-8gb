# ¿Pueden los 3 modelos repartirse el trabajo? — 22/07/2026

Solicitud del autor: que los tres trabajen **juntos**, se repartan la tarea y devuelvan
**una sola respuesta**. Implementado en `chat_3modelos.py` (`/modo equipo`):

1. Bonsai-27B (GPU) descompone la solicitud y reparte por rol.
2. Cada modelo resuelve su subtarea **en paralelo**.
3. Bonsai revisa las partes y redacta una respuesta única.

Solicitud de prueba, con tres partes genuinamente separables: *función Python que lea un CSV
y agrupe por mes + explicación de por qué diccionario y no lista + 4 casos de prueba*.

---

## 1. Dos defectos encontrados en la primera ejecución

| Defecto | Qué pasaba |
|---|---|
| **Subtareas repetidas al mismo modelo** | El coordinador le dio 2 de 3 al Coder. Cada servidor atiende de uno en uno, así que se **encolaron**: 69,1 s idénticos, sin paralelismo real |
| **La GPU ociosa en la fase 2** | El modelo más rápido esperando, mientras los dos lentos competían por el ancho de banda (9,0 t/s cada uno contra 27 en solitario) |

Corregido con `repartir_sin_repetir()`: un modelo, una subtarea, y las repetidas pasan al
primer modelo libre **empezando por la GPU**.

**Mejora: 112,5 s → 84,8 s (−25 %).**

---

## 2. El resultado que decide

| Camino | Tiempo |
|---|---:|
| **Equipo** (repartir + paralelo + unificar) | **84,8 s** |
| **Bonsai solo** (29,0 t/s, 3426 caracteres, cubre las tres partes) | **31,5 s** |

**El equipo tarda 2,7× más y no entrega más.** Bonsai solo respondió las tres partes de la
solicitud en un tercio del tiempo.

### Por qué, en una línea

**El reparto en paralelo termina cuando termina el más lento.** Y aquí los trabajadores no
son comparables:

| | Velocidad |
|---|---:|
| Bonsai (GPU) | 29,0 t/s |
| Modelos de RAM, con dos trabajando a la vez | ~9,0 t/s |

Enviar una subtarea a un modelo de RAM cuesta **3× más por token** que dejársela a la
GPU. Repartir entre trabajadores desiguales no acelera: **arrastra el total al ritmo del
más lento**, y además suma dos llamadas extra al coordinador (repartir y unificar).

---

## 3. El mismo hallazgo, por tercera vez

Es la tercera medición independiente que apunta al mismo lugar:

| Prueba | Conclusión |
|---|---|
| `resultado_convivencia.md` | El caudal agregado de RAM **no crece** al sumar modelos: 24,0 t/s entre dos contra 27,0 t/s con uno solo |
| `resultado_supervisor.md` | La cascada funciona (100 % de detección) pero **ir directo a la GPU es más rápido y acierta igual** |
| **Este** | **Repartir el trabajo entre los tres tarda 2,7× más que preguntarle solo a la GPU** |

> **En este hardware, el recurso abundante es la GPU y el escaso es el ancho de banda de
> RAM.** Toda arquitectura que reparta trabajo *hacia* la RAM paga el recurso caro para
> ahorrar el barato. Es exactamente al revés de lo que suponen las arquitecturas
> multi-agente pensadas para la nube, donde el modelo grande cuesta dinero por token.

---

## 4. Entonces, ¿el equipo no sirve para nada?

Sirve, pero **no para ganar tiempo**. Dónde tiene sentido:

1. **Cuando el modelo grande no cabe o está ocupado.*** Es el mismo caso de la
   supervisión: como coordinador la GPU hace 2 llamadas cortas en vez de 1 larga.
2. **Cuando las subtareas necesitan capacidades distintas** — un modelo de visión, uno de
   código, uno de idioma. Ahí el reparto no es por velocidad sino por **habilidad**, y no
   hay alternativa: ningún modelo solo puede hacerlo todo.
3. **Con más ancho de banda.** Con DDR5 los modelos de RAM subirían a ~20 t/s y la brecha
   con la GPU se cerraría lo suficiente para que repartir sí acelere.

**Recomendación práctica: usar `/modo comparar` para juzgar modelos y `/modo equipo` para
ver cómo se comporta la orquestación** — pero para trabajo real, preguntarle a la GPU.

---

## 5. Segunda ejecución: el problema era el presupuesto de tokens

La primera ejecución del modo equipo entregó **una de las tres partes pedidas** y
**propagó tal cual** el bug del Coder (`groupby(df['fecha'].dt.month)`, que junta enero de
2023 y enero de 2024 en el mismo grupo). Parecía un fallo del diseño. No lo era.

Con 600 tokens por trabajador y **900 para fusionar tres partes**, el coordinador estaba
obligado a descartar contenido: la compresión garantizaba la pérdida. Subido a 1400/2800 y con
tres reglas explícitas en el prompt de unificación (revisa antes de copiar, no pierdas
partes, no repitas secciones):

| | 1ª ejecución | 2ª ejecución |
|---|---|---|
| Bug `dt.month` | **propagado textual** | **corregido a `dt.to_period('M')`** |
| Partes entregadas | 1 de 3 | **3 de 3** + tabla resumen |
| Secciones repetidas | 3 | ninguna |
| Tiempo | 101,6 s | 160,4 s |

Y no lo ocultó: lo **diagnosticó**. *"`dt.to_period('M')` agrupa por mes en lugar de solo el
número del mes, lo que evita ambigüedades entre años."* Además le añadió una validación de
columnas que el Coder no tenía.

> **Corrección a la conclusión previa.*** La sección 4 decía que el equipo "no entrega más".
> Con presupuesto suficiente **sí entrega más que los modelos pequeños**: corrige sus bugs.
> Lo que sigue en pie es el costo: 160,4 s contra ~31,5 s de Bonsai solo. La comparación
> justa —Bonsai solo con el presupuesto nuevo— **todavía no se hizo**.

### El defecto que nadie detectó

El caso de prueba del **CSV vacío** —el que se pidió explícitamente— dice: *entrada de
0 bytes, resultado esperado DataFrame vacío*. **Es falso:** `pd.read_csv` sobre 0 bytes
lanza `EmptyDataError`. La función falla. Los casos 2 y 4 también tienen resultados
esperados mal (formato de lista contra DataFrame; un `ValueError` con texto que pandas no
emite).

`resultado_supervisor.md` dejó registrado que la prueba pendiente era **"código que pasa la
lectura y falla en un caso borde"**. Aquí hay uno en condiciones reales, y **el supervisor lo
dejó pasar**.

> **Corregido el 23/07.** Este documento afirmaba que la supervisión cubre *errores de
> lógica visible* pero no *errores de conocimiento de la biblioteca*. Esa regla salía de
> **un solo caso**. Medida sobre 18 errores (`resultado_supervisor.md` §6), **no existe
> tal patrón**: escapa alrededor de la mitad en ambas clases, y el mismo enunciado recibe
> veredictos distintos según el código concreto. Lo correcto es: **el supervisor detecta
> algo más de la mitad de los errores y nunca da una falsa alarma**, sin que se pueda
> anticipar cuáles se le escapan.

---

## 6. Lo que falta medir

- **La comparación justa que falta: Bonsai solo con el presupuesto nuevo** (1400 tokens),
  misma solicitud. Los 31,5 s de la sección 2 se midieron con 900 tokens, así que comparar
  contra los 160,4 s del equipo **favorece indebidamente al camino directo**. Sin ese
  número no se puede cerrar el costo-beneficio.
- **Juicio a ciegas de la calidad.** El equipo corrige bugs de los pequeños, pero no se sabe
  si su respuesta supera a la de Bonsai solo — que nunca tuvo el bug.
- **Solicitudes más grandes.*** Con subtareas de 600 tokens el costo fijo del coordinador
  (repartir + unificar) pesa mucho. Con subtareas de 3000 tokens pesaría menos.
