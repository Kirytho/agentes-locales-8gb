#!/usr/bin/env python3
# Uso: herramientas/leer_cache_prompt.py logs/backend.log <linea_desde>
# Verificado el 13/09/2026 contra dos pedidos directos con cached_tokens conocido.
"""Lee un tramo del log de llama-server y dice, por pedido, cuanto reuso y cuanto recalculo."""
import re, sys
ruta, desde = sys.argv[1], int(sys.argv[2])
lineas = open(ruta, encoding="utf-8", errors="replace").read().splitlines()[desde:]
tareas = {}
for l in lineas:
    m = re.search(r"task (\d+) \| edit/divergence sample \(cached/incoming/lcp/reusable/rewind/append/cache_prompt\) = \((\d+)/(\d+)/(\d+)/(\d+)/(\d+)/(\d+)/(\d+)\)", l)
    if m:
        t = int(m.group(1)); tareas.setdefault(t, {})
        tareas[t].update(cached=int(m.group(2)), entrante=int(m.group(3)), lcp=int(m.group(4)))
    m = re.search(r"task (\d+) \| prompt eval time = +([\d.]+) ms / +(\d+) tokens", l)
    if m:
        t = int(m.group(1)); tareas.setdefault(t, {})
        tareas[t].update(ms=float(m.group(2)), procesados=int(m.group(3)))
    m = re.search(r"task (\d+) \| restored context checkpoint .*?n_past = (\d+)", l)
    if m:
        t = int(m.group(1)); tareas.setdefault(t, {})
        tareas[t]["restaurado"] = int(m.group(2))
filas = [(t, d) for t, d in sorted(tareas.items()) if "entrante" in d and "procesados" in d]
tot_in = tot_proc = 0
print(f"{'#':>3} {'entrante':>9} {'en comun':>9} {'nuevo':>7} {'recalc':>8} {'desperdicio':>12} {'ms':>8}")
tot_desp = 0
for i, (t, d) in enumerate(filas, 1):
    pct = 100 * d["procesados"] / max(d["entrante"], 1)
    tot_in += d["entrante"]; tot_proc += d["procesados"]
    nuevo = d["entrante"] - d["lcp"]
    # desperdicio: lo que se recalculo AUNQUE estaba en cache (el prefijo coincidia)
    desp = max(0, d["procesados"] - nuevo)
    tot_desp += desp
    print(f"{i:>3} {d['entrante']:>9} {d['lcp']:>9} {nuevo:>7} {d['procesados']:>8} {desp:>12} {d['ms']:>8.0f}")
if filas:
    print(f"\nTOTAL  {len(filas)} pedidos   entrantes {tot_in}   recalculados {tot_proc}   "
          f"= {100*tot_proc/tot_in:.1f}% recalculado")
    print(f"DESPERDICIO  {tot_desp} tokens recalculados que ya estaban en cache "
          f"= {100*tot_desp/tot_in:.2f}% de lo entrante")
