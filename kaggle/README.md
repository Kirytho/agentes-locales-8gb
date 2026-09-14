# Un backend en Kaggle

Ejecutar el modelo en las GPU de Kaggle y consumirlo desde la computadora local,
para que **Hermes maneje el bucle de agente sin depender de un harness de pago**.

## Por qué esto puede funcionar, y qué falló antes

Tres cosas ya medidas en este proyecto:

**opencode no era el modelo, era el harness.** Misma tarea, mismo modelo local:

```
hermes     OK      13 s     5 peticiones
opencode   MAL    231 s    43 peticiones   "Context size has been exceeded"
kimi       MAL    168 s    13 peticiones   "empty response"
```

opencode carga sus herramientas una por una y repetidas veces; cada carga amplía
la conversación y termina llenando el contexto.

**El techo local era la VRAM.** Hermes exige ≥64.000 tokens de contexto y gasta
~22.700 fijos en su prompt y sus 21 herramientas. Ornith a 98k usa ~7.150 MiB de
8.192: cabe el modelo o cabe el contexto, no los dos con margen. **Kaggle rompe
ese empate**: con dos T4 son 30 GB, casi cuatro veces la tarjeta gráfica local.

**Lo que sigue sin saberse.** El barrido de 600 ejecuciones mostró que operar
herramientas resiste la cuantización (78-94% en todas), pero **razonar se
degrada** (4% a 2 bits contra 50% a 5). Un agente autónomo necesita las dos. Esa
es la pregunta que este montaje responde.

## Quién hace qué

```
Hermes                 decide y delega (subagentes)   <- el que reparte
  -> intermediario     clasifica y elige backend      <- el que enruta
     -> Kaggle         el modelo genera
computadora local      ejecuta las pruebas y verifica
```

**Atención:** el reparto del intermediario (dividir una tarea entre modelos)
**no aplica aquí**. Está desactivado y es inalcanzable bajo cualquier harness:
solo se activa en solicitudes sin herramientas y sin streaming, y todo harness
agéntico envía `stream=true` (medido: Hermes 100% en ~200 vueltas, opencode
161/161). El reparto lo hace Hermes con sus subagentes, que aceptan un modelo
distinto por subagente.

## Pasos

1. Sube `backend_kaggle.ipynb` a Kaggle. En el panel derecho:
   **Accelerator = GPU**, **Internet = On**.
2. Ejecuta las celdas. La de compilar tarda 15-25 min **la primera vez**; después
   usa `Save Version` y, en la próxima sesión, añade esa salida como dataset de
   entrada: así inicia en segundos.
3. La última celda imprime la URL del túnel. Esa URL se configura en el
   intermediario como un backend más, compatible con OpenAI; no requiere cambiar
   código.
4. Medir, con el instrumento que ya existe:

```sh
python3 pruebas/calidad/eval_stack_completo.py
```

5 escenarios vía Hermes con oráculo sobre disco; el banco inicia por sí solo el
grabador que registra el tráfico. De ahí salieron las 600 ejecuciones, así que
los números son comparables.

## El control, antes de cambiar nada

El modelo lo elige la celda 3 (`REPO` y `ARCHIVO`). La primera ejecución conviene
hacerla con **un modelo que ya esté medido localmente**, a propósito:

si se cambian el hardware **y** el modelo a la vez y el resultado mejora, no se
sabe a cuál de los dos atribuirlo. Primero hay que comprobar que el mismo modelo
se comporta igual en Kaggle: eso valida el entorno. Solo después, un modelo más
grande.

Para que el control sea limpio hay que ejecutarlo localmente con
`backends/linux/bin-spark` (upstream), que es el mismo motor que compila el
notebook — el de producción es el fork buun, que rinde +45% y sería otra
variable.

## Qué acelerador elegir

Kaggle ofrece tres aceleradores. La cuota de GPU (30 h/semana) es común a las dos
primeras; la de TPU es aparte.

```
GPU T4 x2    2 x 16 GB = 30 GB usables    la que se usó en todas las mediciones
GPU P100     16 GB, ~2x el ancho de banda de una T4, pero sin tensor cores
TPU v5e-8    llama.cpp no la soporta: no sirve para este montaje
```

**T4 x2 es la única que aloja los modelos que dieron mejor resultado** (Qwen3.8 27B,
Gemma 4 26B-A4B y K2-Horizon-MoVA-36B-A4B, de 19 a 26 GB). La P100 solo sirve para
modelos que quepan en 16 GB.

## Lo que hay que aceptar

- **12 h por sesión, 30 h por semana.** Laboratorio, no backend diario.
- **La URL del túnel es pública y sin contraseña.** Por ahí viaja el contenido de
  los archivos. `llama-server` tiene `--api-key`, pero el intermediario todavía no
  envía ninguna cabecera de autorización: es un cambio pequeño y pendiente.
- **El reglamento de Kaggle sobre túneles no se pudo verificar** (su página de
  términos no se puede leer sin navegador). Colab, en cambio, los prohíbe
  explícitamente en el plan gratuito, junto con SSH y "servicios web no
  relacionados con la computación interactiva".
- **No mezclar en una tabla números de Kaggle con números de la GPU local.**
  Distinto hardware y distinto motor.

## Por qué no se eligió Colab

Sus términos prohíben lo que haría falta:

> *"Remote control such as SSH shells and remote desktops are disallowed from
> managed Colab runtimes running free of charge"*
>
> *"file hosting, media serving, or other web service offerings not related to
> interactive compute with Colab"*
