import sys
# -*- coding: utf-8 -*-
"""Ejecuta todos los tests del banco compuesto contra las implementaciones de
referencia. Si algo falla, el banco esta mal y la medicion no valdria."""
import subprocess, sys, tempfile
from pathlib import Path
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# pruebas/ se reorganizo en carpetas el 07/09/2026: los bancos de calidad
# viven en pruebas/calidad/. Sin esta linea el import de abajo no los
# encuentra desde otra subcarpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "calidad"))
from banco_compuesto import TAREAS
from banco_compuesto_grande import TAREAS_GRANDES

TAREAS = TAREAS + TAREAS_GRANDES


def correr(fuente):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(fuente + "\nprint('OK')\n"); ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=15, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:120]
    finally:
        Path(ruta).unlink(missing_ok=True)


fallos = 0
for t in TAREAS:
    ref = t["referencia"]
    print(f"\n{t['id']}")
    for nombre, tests in t["tests_pieza"].items():
        ok, err = correr(ref + "\n" + tests)
        print(f"   pieza {nombre:20s} {'OK' if ok else 'FALLA  ' + err}")
        fallos += not ok
    ok, err = correr(ref + "\n" + t["integracion"])
    print(f"   INTEGRACION{' ':17s} {'OK' if ok else 'FALLA  ' + err}")
    fallos += not ok
    # el test de integracion tiene que usar todas las piezas
    faltan = [n for n in t["tests_pieza"] if n not in t["integracion"]]
    if faltan:
        print(f"   AVISO: la integracion no usa {faltan}")

print(f"\n{'BANCO VALIDO' if not fallos else f'BANCO ROTO: {fallos} fallos'}")
sys.exit(1 if fallos else 0)
