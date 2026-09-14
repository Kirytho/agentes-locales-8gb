#!/usr/bin/env python3
"""Cuenta delegaciones UTILES, no llamadas a delegate_task.

Por que existe: el 07/09/2026 IQ2_M hizo 4 delegate_task en el abanico de 4
servicios y parecia un reparto perfecto. Mirando los argumentos, las cuatro
apuntaban a rutas inventadas (`service_a/service.py`, `service.py`) y tres
eran identicas entre si. Cero trabajo repartido de verdad.

Contar la herramienta mide la INTENCION; lo que importa es si cada rama apunta
a un servicio real y distinto.

    uso: medir_reparto.py <cable.jsonl> <dir_del_fixture>
"""
import json, sys, re
from pathlib import Path

cable, raiz = Path(sys.argv[1]), Path(sys.argv[2])
# Servicios que existen de verdad en el fixture de esta ejecucion.
reales = {p.parent.name for p in raiz.rglob("servicio.py")}

llamadas, apuntadas, rutas_malas = 0, set(), 0
vistas = []
for ln in cable.read_text().splitlines():
    try: d = json.loads(ln)
    except Exception: continue
    for tc in ((d.get("respuesta") or {}).get("tool_calls") or []):
        if tc.get("nombre") != "delegate_task": continue
        llamadas += 1
        a = tc.get("argumentos", "")
        vistas.append(a)
        tocados = {s for s in reales if s in a}
        if tocados: apuntadas |= tocados
        else: rutas_malas += 1

unicas = len(set(vistas))
print(f"REPARTO|llamadas={llamadas}|unicas={unicas}"
      f"|servicios_reales_apuntados={len(apuntadas)}/{len(reales)}"
      f"|con_ruta_inexistente={rutas_malas}")
if apuntadas: print(f"  apunto a: {sorted(apuntadas)}")
if rutas_malas: print(f"  {rutas_malas} delegaciones a rutas que no existen")
