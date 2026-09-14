#!/usr/bin/env python3
"""tabla_5rep.py - El barrido de 5 repeticiones, en una tabla con estadistica.

Lee logs/barrido_5rep.txt (lo escribe barrer_5rep.sh) y compara cada modelo
contra la REFERENCIA medida con el mismo instrumento -- K2 sin razonar -- con
la prueba exacta de Fisher. Una diferencia que no llega a p<0,05 no se reporta
como diferencia: el 09/09 una sola ejecucion dio vuelta la conclusion dos veces.

Ordena por EDICION (lo que el MCP le pide al modelo) y, a igualdad, el mas
pequeño primero. `rompio` se marca con flecha: es un veto, no un punto menos.

Ademas construye los pares del MISMO modelo con y sin imatrix (@ngquocvinh comun,
@miifanboy i1), que es la comparacion que esta carpeta doble permite.

    uso: tabla_5rep.py [ruta.txt] [--ref ETIQUETA]
"""
from __future__ import annotations

import sys
from pathlib import Path

from scipy.stats import fisher_exact

RUTA = Path(__file__).resolve().parent.parent / "logs" / "barrido_5rep.txt"
REF = "K2-Horizon-7B-Q4_K_S"


def frac(s):
    try:
        a, b = s.split("/")
        return int(a), int(b)
    except (ValueError, AttributeError):
        return None


def leer(ruta):
    filas = []
    for l in ruta.read_text().splitlines():
        if not l.startswith("B5|"):
            continue
        p = l.split("|")
        d = {"q": p[1], "gb": float(p[2].split()[0])}
        for c in p[3:]:
            if c.endswith("MiB"):
                d["vram"] = int(c.split()[0])
            elif "=" in c:
                k, v = c.split("=", 1); d[k] = v
            else:
                d["estado"] = c
        filas.append(d)
    return filas


def p_vs(a, b):
    """Fisher entre dos fracciones 'x/n'. None si falta alguna."""
    fa, fb = frac(a), frac(b)
    if not fa or not fb:
        return None
    return fisher_exact([[fa[0], fa[1] - fa[0]], [fb[0], fb[1] - fb[0]]])[1]


def marca(p, a, b):
    if p is None or p >= 0.05:
        return ""
    return " +" if frac(a)[0] / frac(a)[1] > frac(b)[0] / frac(b)[1] else " -"


def main():
    args = sys.argv[1:]
    ref = args[args.index("--ref") + 1] if "--ref" in args else REF
    ruta = Path(next((a for a in args if not a.startswith("-") and a != ref), RUTA))
    filas = leer(ruta)
    if not filas:
        print(f"no hay resultados todavia en {ruta}"); return 1
    r = next((f for f in filas if f["q"] == ref), None)

    buenas = [f for f in filas if "edicion" in f]
    malas = [f for f in filas if "edicion" not in f]
    buenas.sort(key=lambda f: (-(frac(f["edicion"])[0] if frac(f["edicion"]) else 0), f["gb"]))

    w = max(len(f["q"]) for f in filas)
    print(f"\n  {len(filas)} modelos medidos · referencia: {ref if r else ref + ' (TODAVIA NO MEDIDA)'}")
    print("  +/- = distinto de la referencia con p<0,05 (Fisher). Sin marca = no distinguible.\n")
    cab = f"  {'modelo':<{w}} {'GB':>5} {'VRAM':>5}  {'edicion':>8} {'rompio':>7}  {'bloq.PASA':>9} {'b.rompio':>8}  {'entero':>7}  {'funcion':>8} {'scripts':>8}"
    print(cab); print("  " + "-" * (len(cab) - 2))
    for f in buenas:
        def c(k, ancho):
            v = f.get(k, "?")
            m = marca(p_vs(v, r.get(k)), v, r.get(k)) if r and f is not r and k in r else ""
            return f"{v + m:>{ancho}}"
        rom = f.get("rompio", "?"); brom = f.get("bloques_rompio", "?")
        rom_s = rom + (" <-" if rom not in ("0", "?") else "")
        brom_s = brom + (" <-" if brom not in ("0", "?") else "")
        ref_s = "  <- REF" if f is r else ""
        print(f"  {f['q']:<{w}} {f['gb']:>5.2f} {f.get('vram', 0):>5}  {c('edicion', 8)} {rom_s:>7}  "
              f"{c('bloques_pasa', 9)} {brom_s:>8}  {c('entero_pasa', 7)}  "
              f"{c('funciones', 8)} {c('scripts', 8)}{ref_s}")
    if malas:
        print()
        for f in malas:
            print(f"  {f['q']:<{w}} {f['gb']:>5.2f}  {f.get('estado', '?')}  {f.get('criba', '')}")

    # con y sin imatrix: mismo nombre base, distinto origen
    pares = {}
    for f in buenas:
        base, _, origen = f["q"].rpartition("@")
        if origen:
            pares.setdefault(base, {})[origen] = f
    pares = {b: v for b, v in pares.items() if len(v) == 2}
    if pares:
        print("\n  CON Y SIN IMATRIX (mismo modelo, misma cuantizacion)")
        for base, v in sorted(pares.items()):
            com, i1 = v.get("ngquocvinh"), v.get("miifanboy")
            if not (com and i1):
                continue
            for k in ("edicion", "bloques_pasa", "funciones"):
                p = p_vs(i1.get(k), com.get(k))
                print(f"    {base.replace('Spark-X2.5-4B-', ''):<8} {k:<13} comun {com.get(k, '?'):>7}"
                      f"   imatrix {i1.get(k, '?'):>7}   p={p:.3f}" if p is not None else "")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
