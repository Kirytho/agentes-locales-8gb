# -*- coding: utf-8 -*-
"""resumen_bateria.py - Junta los resultado_experto_*.json en una sola tabla.

Cada ejecucion de eval_expertos.py deja su propio archivo. Compararlos a ojo
invita a equivocarse; esto los pone uno al lado del otro con los mismos campos.

Uso:  python resumen_bateria.py [etiqueta ...]     (sin argumentos: todos)
"""
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

pedidas = sys.argv[1:]
archivos = sorted(AQUI.glob("resultado_experto_*.json"))
if pedidas:
    archivos = [a for a in archivos
                if any(p in a.stem.replace("resultado_experto_", "") for p in pedidas)]

filas = []
fallos = {}
for a in archivos:
    d = json.loads(a.read_text(encoding="utf-8"))
    cod = d.get("codigo", {})
    detalle = cod.get("detalle", [])
    etq = d.get("etiqueta", a.stem)
    filas.append((etq, cod.get("aciertos", 0), cod.get("total", len(detalle)),
                  d.get("velocidad_media", 0.0)))
    fallos[etq] = [t.get("id") for t in detalle if not t.get("ok")]

ancho = max((len(f[0]) for f in filas), default=10)
print(f"{'modelo':<{ancho}}  aciertos   %     t/s")
print("-" * (ancho + 26))
for etq, ok, total, vel in sorted(filas, key=lambda f: -f[1]):
    pct = 100 * ok / total if total else 0
    print(f"{etq:<{ancho}}  {ok:>3}/{total:<3}  {pct:5.1f}  {vel:6.1f}")

print("\nTareas falladas por modelo:")
for etq, ids in fallos.items():
    print(f"  {etq:<{ancho}}  {', '.join(ids) if ids else '(ninguna)'}")

if len(fallos) > 1:
    comunes = set.intersection(*(set(v) for v in fallos.values()))
    print(f"\nFalladas por TODOS: {', '.join(sorted(comunes)) if comunes else '(ninguna)'}")
