#!/usr/bin/env python3
"""tabla_codigo.py - Los modelos perfilados, ordenados por lo que decide.

POR QUE ESTA ORDENADA ASI (09/09/2026)

El objetivo es el modelo mas PEQUEÑO que programe bien, para que el MCP le
delegue. De los cuatro bancos, el que decide es EDICION: es literalmente lo que
la herramienta le pide al modelo -- modificar codigo que ya existe sin romper
lo que funcionaba. `funciones` y `scripts` miden escribir desde cero, que el MCP
casi no usa.

Y hay un VETO: `rompio` cuenta las veces que entrego el archivo sin funciones
que estaban. Un modelo que rompe la regresion no es un modelo un poco peor: es
uno que mete bugs silenciosos, y solo los tests lo atajan.

`formato` es cuantas veces emitio bloques SEARCH/REPLACE bien. El que no sabe
edita archivos de la MITAD de tamano, porque tiene que reescribirlos enteros.

No se calcula un puntaje unico a proposito: promediar cuatro bancos distintos
esconde justo lo que hay que mirar.

    uso:  tabla_codigo.py [ruta.txt]
"""
from __future__ import annotations

import sys
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "logs" / "perfil_codigo.txt"


def frac(s: str) -> float:
    """'11/13' -> 0.846. Devuelve -1 si no es una fraccion."""
    try:
        a, b = s.split("/")
        return int(a) / int(b) if int(b) else -1
    except (ValueError, AttributeError):
        return -1


def main() -> int:
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else RUTA
    if not ruta.is_file():
        print(f"no hay perfiles todavia en {ruta}", file=sys.stderr)
        return 1

    filas = []
    for linea in ruta.read_text().splitlines():
        if not linea.startswith("PERFIL|"):
            continue
        p = linea.split("|")
        d = {"modelo": p[1], "gb": p[2]}
        for campo in p[3:]:
            if "=" in campo:
                k, v = campo.split("=", 1)
                d[k] = v
            elif campo.endswith("MiB"):
                d["vram"] = campo
            else:
                d.setdefault("nota", campo)
        filas.append(d)
    if not filas:
        print("el archivo no tiene lineas PERFIL|", file=sys.stderr)
        return 1

    # Por edicion, que es lo que hace el MCP; a igualdad, el mas pequeño gana.
    filas.sort(key=lambda d: (-frac(d.get("edicion", "")),
                              float(d["gb"].split()[0] or 99)))

    anchos = max(len(f["modelo"]) for f in filas)
    print(f"\n  {'modelo':<{anchos}} {'GB':>6} {'VRAM':>9} {'edicion':>8} "
          f"{'rompio':>7} {'formato':>8} {'funcion':>8} {'scripts':>8}")
    print(f"  {'-'*(anchos+58)}")
    for f in filas:
        if "nota" in f and "edicion" not in f:
            print(f"  {f['modelo']:<{anchos}} {f['gb'].split()[0]:>6} "
                  f"{'':>9} {f['nota'][:40]}")
            continue
        rompio = f.get("rompio_regresion", "?")
        aviso = " <-" if rompio not in ("0", "?") else ""
        print(f"  {f['modelo']:<{anchos}} {f['gb'].split()[0]:>6} "
              f"{f.get('vram','?').replace(' MiB',''):>9} "
              f"{f.get('edicion','?'):>8} {rompio + aviso:>7} "
              f"{f.get('formato_bloques','-'):>8} "
              f"{f.get('funciones','?'):>8} {f.get('scripts','?'):>8}")
    print(f"\n  ordenado por EDICION, que es lo que el MCP le pide al modelo.")
    print(f"  `rompio` = entrego el archivo sin funciones que estaban: es un veto,")
    print(f"  no un punto menos. `formato` = supo emitir bloques SEARCH/REPLACE;")
    print(f"  el que no sabe edita archivos de la mitad de tamano.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
