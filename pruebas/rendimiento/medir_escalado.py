# -*- coding: utf-8 -*-
"""medir_escalado.py - Cuantos agentes aguanta un modelo, medido en serio.

POR QUE (20/08/2026)

`medir_concurrencia.py` mide un nivel por vez y en orden creciente. Al barrer
hasta 16 agentes aparecio algo que no cierra: 16 agentes terminaban ANTES en
tiempo de reloj (4,2 s) que 8 agentes (5,1-5,8 s) haciendo el doble de trabajo,
y el rendimiento por agente SUBIA de 29 a 36 tok/s.

Este banco existe para explicarlo en vez de suponerlo. Tres diferencias:

  - **repeticiones y orden alternado**: cada nivel se mide N veces y los niveles
    se recorren en orden distinto en cada vuelta, para que un calentamiento o
    una deriva no se le cargue siempre al mismo.
  - **separa generar de coordinar**: ademas del agregado por reloj de pared,
    reporta lo que dice el servidor de cada peticion (`predicted_per_second` y
    `prompt_ms`). Si el agregado cae pero el decode por peticion se mantiene, el
    problema es de planificacion, no del modelo.
  - **prompt unico por agente**, para que el cache de prefijo no regale prefill.

Uso:
    python3 pruebas/rendimiento/medir_escalado.py <puerto> [repeticiones]
"""
import json
import statistics as st
import sys
import threading
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8080"
REPES = int(sys.argv[2]) if len(sys.argv) > 2 else 3
NIVELES = [1, 2, 4, 6, 8, 12, 16]
MAX_TOKENS = 128
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"

BASE = ("Escribe una funcion Python que procese una lista de registros y "
        "devuelva un resumen. Explica brevemente las decisiones de diseno.")


def pedir(idx, salida):
    cuerpo = json.dumps({
        "model": "x",
        "messages": [{"role": "user", "content": f"[agente {idx} · {time.time()}] {BASE}"}],
        "max_tokens": MAX_TOKENS, "temperature": 0,
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read())
        t = d.get("timings", {})
        salida[idx] = {
            "n": t.get("predicted_n", 0),
            "decode": t.get("predicted_per_second", 0.0),   # lo que dice el servidor
            "prefill_ms": t.get("prompt_ms", 0.0),
            "segundos": time.time() - t0,
        }
    except Exception as e:  # noqa: BLE001
        salida[idx] = {"error": str(e)[:80]}


def nivel(n):
    salida = [None] * n
    hilos = [threading.Thread(target=pedir, args=(i, salida)) for i in range(n)]
    t0 = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    pared = time.time() - t0
    ok = [x for x in salida if x and "n" in x]
    if not ok:
        return None
    return {
        "agentes": n,
        "agregado": sum(x["n"] for x in ok) / pared,
        "decode_medio": st.mean(x["decode"] for x in ok),   # velocidad del modelo
        "prefill_ms": st.mean(x["prefill_ms"] for x in ok),
        "pared": pared,
        "errores": n - len(ok),
    }


print(f"\n{'='*78}\n  Escalado por agentes · puerto {PUERTO} · {REPES} repeticiones"
      f"\n  orden alternado en cada vuelta\n{'='*78}")
nivel(2)   # calentamiento, se descarta
crudo = {n: [] for n in NIVELES}
for v in range(REPES):
    orden = NIVELES if v % 2 == 0 else list(reversed(NIVELES))
    for n in orden:
        r = nivel(n)
        if r:
            crudo[n].append(r)
    print(f"  vuelta {v+1} lista")

print(f"\n  {'agentes':>7s} {'agregado':>10s} {'rango':>13s} {'por agente':>11s} "
      f"{'decode servidor':>16s} {'prefill':>9s}")
filas = []
for n in NIVELES:
    rs = crudo[n]
    if not rs:
        continue
    ag = [r["agregado"] for r in rs]
    dec = st.mean(r["decode_medio"] for r in rs)
    pf = st.mean(r["prefill_ms"] for r in rs)
    filas.append({"agentes": n, "agregado": st.mean(ag), "min": min(ag), "max": max(ag),
                  "decode": dec, "prefill_ms": pf})
    print(f"  {n:7d} {st.mean(ag):9.1f} {min(ag):6.0f}-{max(ag):<6.0f} "
          f"{st.mean(ag)/n:10.1f} {dec:15.1f} {pf:8.0f}ms")

(AQUI / "resultado_escalado.json").write_text(
    json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {AQUI / 'resultado_escalado.json'}\n")
