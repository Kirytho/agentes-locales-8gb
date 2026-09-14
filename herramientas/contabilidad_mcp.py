#!/usr/bin/env python3
"""contabilidad_mcp.py - ¿El MCP ahorro contexto, con uso real?

POR QUE EXISTE (09/09/2026)

La pregunta "¿esto ahorra tokens?" se contesto cuatro veces con cuatro
respuestas distintas -- 0,1x, 0,2x, 4,2x, 0,8x -- porque depende del regimen, y
cada medicion se hizo a mano rearmando el transcripto de la sesion. Esto lee lo
que el servidor registra solo en cada llamada y lo contesta con uso real.

LA CUENTA, y por que da un RANGO y no un numero

    delegar     = pedido + comprobaciones + regresion + respuesta
    a mano      = LEER el archivo + tipear el cambio [+ los mismos tests]

El archivo es lo unico que esta herramienta ahorra: no ahorra escribir codigo
--describir una funcion cuesta mas que escribirla-- ahorra LEER.

Lo del corchete es la parte discutible, y por eso se informan las dos:

  ESTRICTA  a mano no se escriben tests. Es la comparacion mas dura contra
            delegar, y es con la que se midio primero.
  PAREJA    a mano se escriben LAS MISMAS comprobaciones del cambio, porque
            programar con tests es lo normal. Contarlas solo del lado de
            delegar inclina la cuenta.

La REGRESION nunca se suma del lado "a mano": existe porque el modelo devuelve
a veces el archivo sin funciones que estaban, y un humano editando no la
necesita. Esa si es costo propio de delegar.

    uso:  contabilidad_mcp.py [ruta.jsonl] [--detalle]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CHARS_POR_TOKEN = 4
# Lo que cuesta tipear el cambio una vez leido el archivo. Estimacion, y por eso
# esta declarada aqui en vez de escondida en una formula.
COSTO_ESCRIBIR = int(os.getenv("BANCO_MCP_COSTO_ESCRIBIR", "150"))
# Que fraccion de las comprobaciones del cambio se escribirian igual sin
# delegar. 1.0 = siempre se programa con tests. 0.0 = nunca.
FRACCION_TESTS = float(os.getenv("BANCO_MCP_FRACCION_TESTS", "1.0"))

RUTA = Path(os.getenv(
    "BANCO_MCP_CONTABILIDAD",
    str(Path(__file__).resolve().parent.parent / "logs" / "mcp_contabilidad.jsonl")))


def tok(chars: float) -> int:
    return round(chars / CHARS_POR_TOKEN)


def contrato(f: dict) -> int:
    return (f.get("chars_pedido", 0) + f.get("chars_comprobaciones", 0)
            + f.get("chars_regresion", 0))


def main() -> int:
    ruta = Path(next((a for a in sys.argv[1:] if not a.startswith("-")), RUTA))
    if not ruta.is_file():
        print(f"no hay nada anotado todavia en {ruta}", file=sys.stderr)
        return 1
    filas = [json.loads(l) for l in ruta.read_text().splitlines() if l.strip()]
    if not filas:
        print("el archivo esta vacio", file=sys.stderr)
        return 1

    print(f"\n{'='*78}\n  CONTABILIDAD DEL MCP  ({len(filas)} llamadas, {ruta})\n{'='*78}\n")

    por_res: dict[str, list] = {}
    for f in filas:
        por_res.setdefault(f["resultado"], []).append(f)
    print(f"  {'resultado':<14}{'n':>4}{'pedido':>9}{'compr.':>9}{'regres.':>9}"
          f"{'respu.':>9}{'gastado':>10}")
    gastado = 0
    for res, fs in sorted(por_res.items(), key=lambda kv: -len(kv[1])):
        cols = [sum(x.get(k, 0) for x in fs) for k in
                ("chars_pedido", "chars_comprobaciones", "chars_regresion",
                 "chars_respuesta")]
        gastado += sum(cols)
        print(f"  {res:<14}{len(fs):>4}" + "".join(f"{tok(c):>9}" for c in cols)
              + f"{tok(sum(cols)):>10}")
    print(f"  {'TOTAL':<14}{len(filas):>4}{'':>36}{tok(gastado):>10}")

    exitosas = por_res.get("paso", [])
    if not exitosas:
        print("\n  todavia no hay ninguna llamada que haya pasado: nada que comparar\n")
        return 0

    # Solo las que pasaron produjeron ahorro; las fallidas son costo puro y por
    # eso entran en `gastado` pero no aqui.
    leer = sum(tok(x["chars_archivo"]) for x in exitosas)
    tipeo = COSTO_ESCRIBIR * len(exitosas)
    tests = tok(sum(x.get("chars_comprobaciones", 0) for x in exitosas) * FRACCION_TESTS)
    d = tok(gastado)
    estricta, pareja = leer + tipeo, leer + tipeo + tests

    print(f"\n  {'-'*74}")
    print(f"  delegando                       {d:>7} tokens   (las {len(filas)} llamadas, "
          f"incluidas las {len(filas)-len(exitosas)} que no sirvieron)")
    print(f"  a mano, sin escribir tests      {estricta:>7} tokens   -> "
          f"{'AHORRA' if estricta > d else 'PIERDE'} {estricta/d:.1f}x")
    print(f"  a mano, con los mismos tests    {pareja:>7} tokens   -> "
          f"{'AHORRA' if pareja > d else 'PIERDE'} {pareja/d:.1f}x")
    print(f"\n  (leer {leer} + tipear {tipeo}"
          f"{f' + {tests} de tests que se escribirian igual' if tests else ''})")

    con_lineas = [x for x in filas if x["lineas_archivo"]]
    ancho = (sum(x["chars_archivo"] for x in con_lineas)
             / sum(x["lineas_archivo"] for x in con_lineas)) if con_lineas else 40
    medio = tok(gastado / len(filas))
    tests_medio = tok(sum(x.get("chars_comprobaciones", 0)
                          for x in filas) * FRACCION_TESTS / len(filas))
    print(f"\n  costo medio por llamada: {medio} tokens"
          f"   (linea media del proyecto: {ancho:.0f} chars)")
    # Se igualan cuando leer el archivo vale lo que sobra del contrato despues
    # de descontar lo que se pagaria igual a mano.
    neto = medio - COSTO_ESCRIBIR - tests_medio
    if neto <= 0:
        print("  -> el contrato sale mas barato que hacerlo a mano: conviene con "
              "cualquier tamano de archivo")
    else:
        print(f"  -> conviene delegar desde archivos de "
              f"~{round(neto * CHARS_POR_TOKEN / ancho)} lineas para arriba")

    formatos: dict[str, int] = {}
    for x in exitosas:
        formatos[x["formato"] or "-"] = formatos.get(x["formato"] or "-", 0) + 1
    rein = sum(1 for x in exitosas if x["intentos"] > 1)
    print("  formato usado: " + ", ".join(f"{k} {v}" for k, v in formatos.items())
          + f"  ·  {rein}/{len(exitosas)} necesitaron reintento")

    if "--detalle" in sys.argv:
        print(f"\n  {'archivo':<32}{'lineas':>7}{'delegar':>9}{'a mano':>8}{'razon':>8}")
        for x in exitosas:
            dd = tok(contrato(x) + x["chars_respuesta"])
            yy = (tok(x["chars_archivo"]) + COSTO_ESCRIBIR
                  + tok(x.get("chars_comprobaciones", 0) * FRACCION_TESTS))
            print(f"  {', '.join(x['archivos'])[:31]:<32}{x['lineas_archivo']:>7}"
                  f"{dd:>9}{yy:>8}{yy/dd:>7.1f}x")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
