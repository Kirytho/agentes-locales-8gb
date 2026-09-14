# -*- coding: utf-8 -*-
"""medir_concurrencia.py - Cuanto rinde un backend con varios agentes a la vez.

POR QUE EXISTE (17/08/2026)

Todas las mediciones del proyecto son de UN pedido por vez, pero el intermediario se
concibe como sistema multiagente: varios modelos y varios pedidos conviviendo
en el mismo equipo. Lo que importa ahi no es la velocidad de un pedido sino el
**rendimiento agregado**: cuantos tokens por segundo salen en total cuando hay
N agentes trabajando.

La hipotesis: el backend de razonamiento esta limitado por ancho de banda de
memoria (32,8 GB/s medidos), no por calculo. Leer los pesos cuesta casi lo
mismo para uno que para varios pedidos si se procesan en el mismo lote. Si es
cierto, pasar de 1 a 3 agentes deberia costar bastante menos que 3x.

OJO CON LOS SLOTS: llama-server atiende en paralelo solo hasta `--parallel N`.
Con un solo slot los pedidos se **serializan** y el agregado no sube, por mas
memoria que sobre. Al 17/08 `backends/qwen3/iniciar-linux.sh` no pasa
`--parallel` ni `--cont-batching`; el de GPU si (`--parallel 2`).

Ademas `--ctx-size` es el total y se REPARTE entre los slots: 8192 con 4 slots
deja 2048 por agente. Mas agentes con el mismo ctx = menos contexto cada uno.

Uso:
    python3 pruebas/rendimiento/medir_concurrencia.py <puerto> <etiqueta> [niveles]

Ejemplo:
    ... medir_concurrencia.py 8083 qwen3-1slot 1,2,3,4
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8083"
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "backend"
NIVELES = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "1,2,3,4").split(",")]
# Cuarto argumento: "prefijo" agrega a TODOS los agentes el mismo system prompt
# largo. Es el caso multi-agente real (todos comparten instrucciones) y el unico
# donde un KV unificado puede ahorrar: el prefijo compartido se computa y se
# guarda una vez en lugar de una por slot.
CON_PREFIJO = len(sys.argv) > 4 and sys.argv[4] == "prefijo"
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
MAX_TOKENS = 128

# Prompts distintos a proposito: con el mismo prompt para todos, el cache de
# prefijo del servidor falsearia el resultado hacia arriba.
PROMPTS = [
    "Escribe una funcion Python que valide un email con expresiones regulares.",
    "Explica que es un indice en una base de datos y cuando conviene crearlo.",
    "Escribe una consulta SQL que devuelva los 5 clientes con mas compras.",
    "Explica la diferencia entre un proceso y un hilo del sistema operativo.",
    "Escribe una funcion que convierta un numero romano a entero.",
    "Explica por que un modelo MoE activa solo parte de sus parametros.",
]


# ~420 tokens de instrucciones compartidas, como las que llevaria cada agente
# de un sistema multi-agente.
PREFIJO = (
    "Eres un agente de ingenieria de software dentro de un sistema multi-agente. "
    "Reglas de trabajo que debes respetar siempre:\n"
    + "\n".join(
        f"{i}. Regla {i}: responde de forma directa y verificable, sin adornos; "
        f"si no estas seguro de un dato, decilo en vez de inventarlo; "
        f"preferi codigo funcionando sobre explicaciones largas."
        for i in range(1, 16))
)


def pedir(prompt, salida, idx):
    # Marca unica POR AGENTE. La lista tiene 6 prompts, asi que con 8 o mas
    # agentes se repetian y el cache de prefijo del servidor los servia casi
    # gratis: con 16 agentes la serie medida tardaba MENOS (3,9 s) que con 8
    # (4,5 s) produciendo el doble de tokens, y el agregado saltaba a 8,28x.
    # Puro artefacto (20/08/2026).
    mensajes = [{"role": "user", "content": f"[{idx}-{time.time()}] {prompt}"}]
    if CON_PREFIJO:
        mensajes = [{"role": "system", "content": PREFIJO}, *mensajes]
    cuerpo = json.dumps({
        "model": "concurrencia",
        "messages": mensajes,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        URL, data=cuerpo, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            d = json.loads(r.read())
        tim = d.get("timings", {})
        salida[idx] = {
            "tok_s": float(tim.get("predicted_per_second", 0.0)),
            "n": int(tim.get("predicted_n", 0)),
            "segundos": time.time() - t0,
        }
    except Exception as e:  # noqa: BLE001 - se quiere ver cualquier fallo
        salida[idx] = {"error": str(e)[:120], "segundos": time.time() - t0}


def nivel(n):
    """Dispara n pedidos a la vez y mide el agregado por reloj de pared."""
    salida = [None] * n
    hilos = [threading.Thread(target=pedir, args=(PROMPTS[i % len(PROMPTS)], salida, i))
             for i in range(n)]
    t0 = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    pared = time.time() - t0

    ok = [r for r in salida if r and "tok_s" in r]
    errores = [r for r in salida if r and "error" in r]
    tokens = sum(r["n"] for r in ok)
    # El agregado es lo que importa: tokens totales sobre el tiempo real que
    # tardo la serie completa, no el promedio de las velocidades individuales.
    agregado = tokens / pared if pared else 0
    por_agente = [r["tok_s"] for r in ok]
    media_agente = sum(por_agente) / len(por_agente) if por_agente else 0

    print(f"  {n} agente(s): agregado {agregado:6.1f} tok/s   "
          f"por agente {media_agente:5.1f}   tanda {pared:5.1f}s   "
          f"{tokens} tokens" + (f"   ERRORES {len(errores)}" if errores else ""))
    if errores:
        print(f"      {errores[0]['error']}")
    return {"agentes": n, "agregado": agregado, "media_agente": media_agente,
            "pared": pared, "tokens": tokens, "detalle": salida}


print(f"\n{'='*66}\n  Concurrencia · {ETIQUETA} · puerto {PUERTO} · "
      f"{MAX_TOKENS} tokens por pedido"
      + ("\n  con prefijo comun (system compartido por todos los agentes)" if CON_PREFIJO else "")
      + f"\n{'='*66}")
res = [nivel(n) for n in NIVELES]

base = res[0]["agregado"] if res else 0
print(f"\n  {'agentes':>8s} {'agregado':>10s} {'vs 1 agente':>13s} {'por agente':>12s}")
for r in res:
    esc = f"{r['agregado'] / base:.2f}x" if base else "-"
    print(f"  {r['agentes']:8d} {r['agregado']:10.1f} {esc:>13s} {r['media_agente']:12.1f}")

salida = AQUI / f"resultado_concurrencia_{ETIQUETA}.json"
salida.write_text(json.dumps({"etiqueta": ETIQUETA, "puerto": PUERTO,
                              "max_tokens": MAX_TOKENS, "niveles": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
