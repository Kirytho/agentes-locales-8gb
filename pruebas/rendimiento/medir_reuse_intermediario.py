# -*- coding: utf-8 -*-
"""medir_reuse_intermediario.py - ¿Sirve --cache-reuse EN PRODUCCION?

La medicion directa contra el backend dio -6%: llama-server ya reaprovecha el
prefijo del slot cuando el historial solo CRECE. Pero el intermediario inyecta memoria
recuperada en el mensaje `system`, es decir al PRINCIPIO del prompt, y eso cambia
el prefijo en cada turno. Ese es el caso donde --cache-reuse deberia servir, y
solo se ve consultando al intermediario (:8086), no al backend.

Uso: python3 pruebas/medir_reuse_intermediario.py [repes]
"""
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPES = int(sys.argv[1]) if len(sys.argv) > 1 else 2
URL = "http://127.0.0.1:8086/v1/chat/completions"

TURNOS = [
    "Estoy escribiendo un scraper en Python, por donde empiezo?",
    "Ahora la funcion que baja la pagina con requests.",
    "Y la que parsea la tabla con BeautifulSoup.",
    "Que pasa si la tabla tiene colspan?",
    "Agregale manejo de errores y timeout.",
    "Escribe los tests de pytest.",
    "Como reintento con espera creciente?",
    "Guardalo en SQLite: dame el esquema.",
]


def pedir(historial):
    cuerpo = json.dumps({"model": "auto", "messages": historial,
                         "max_tokens": 60, "temperature": 0.3}).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    t = d.get("timings", {})
    u = d.get("usage", {}) or {}
    return {
        "prompt_ms": t.get("prompt_ms", 0),
        "prompt_n": t.get("prompt_n", 0),          # tokens que SI hubo que procesar
        "cache_n": t.get("cache_n", 0),            # tokens recuperados del cache
        "prompt_tokens": u.get("prompt_tokens", 0),  # prompt completo
        "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        "pared": time.time() - t0,
        "contenido": (d["choices"][0]["message"].get("content") or "")[:20],
    }


def conversacion(sufijo):
    hist, filas = [], []
    for i, texto in enumerate(TURNOS):
        # El sufijo hace unica la conversacion: si no, el cache del intermediario
        # respondería el turno 1 desde disco y no se mediria nada.
        hist.append({"role": "user", "content": f"{texto} (caso {sufijo})"})
        r = pedir(hist)
        hist.append({"role": "assistant", "content": r["contenido"] or "ok"})
        filas.append(r)
    return filas


print(f"\n{'='*70}\n  Prefijo con memoria inyectada · {REPES} conversaciones de "
      f"{len(TURNOS)} turnos\n{'='*70}")
todas = [conversacion(f"{int(time.time())}-{k}") for k in range(REPES)]
por_turno = list(zip(*todas, strict=True))

print(f"  {'turno':>5s} {'prompt total':>13s} {'procesado':>10s} {'del cache':>10s} {'ms':>8s}")
for i, turno in enumerate(por_turno, 1):
    pt = statistics.mean(t["prompt_tokens"] for t in turno)
    pn = statistics.mean(t["prompt_n"] for t in turno)
    cn = statistics.mean(t["cache_n"] for t in turno)
    ms = statistics.mean(t["prompt_ms"] for t in turno)
    print(f"  {i:5d} {pt:13.0f} {pn:10.0f} {cn:10.0f} {ms:8.1f}")

tot_ms = sum(statistics.mean(t["prompt_ms"] for t in turno) for turno in por_turno)
tot_pn = sum(statistics.mean(t["prompt_n"] for t in turno) for turno in por_turno)
tot_pt = sum(statistics.mean(t["prompt_tokens"] for t in turno) for turno in por_turno)
print(f"\n  tokens de prompt en total : {tot_pt:.0f}")
print(f"  de esos, procesados       : {tot_pn:.0f}  ({tot_pn/tot_pt*100:.1f}%)")
print(f"  tiempo total de prompt    : {tot_ms:.0f} ms")

salida = AQUI / f"resultado_reuse_orq_{sys.argv[2] if len(sys.argv) > 2 else 'base'}.json"
salida.write_text(json.dumps(
    {"turnos": [[dict(t) for t in turno] for turno in por_turno]},
    ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  crudos en {salida.name}\n")
