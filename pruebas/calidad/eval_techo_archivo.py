#!/usr/bin/env python3
"""eval_techo_archivo.py - ¿Hasta que tamano de archivo edita bien el modelo?

POR QUE EXISTE (09/09/2026)

El servidor MCP corta las ediciones con `INTERMEDIARIO_MCP_CUPO_CHARS = 24000`, es decir
~500 lineas. Ese numero NUNCA SE MIDIO: se puso a ojo cuando el modelo tenia que
reescribir el archivo entero, y quedo igual despues de que empezara a devolver
bloques SEARCH/REPLACE, que es cuando el archivo dejo de volver en la respuesta.
A ctx 16384 la cuenta da entre 43.000 y 59.000 caracteres, es decir 2x-3x mas.

Un cupo de menos no rompe nada, pero envia a `entero` -- o directamente rechaza
-- archivos que el modelo editaria bien, y son justo los archivos grandes donde
delegar conviene mas.

QUE SE MIDE

Archivos sinteticos de tamano creciente con una funcion objetivo escondida
dentro, y un cambio pequeño que tocarla. Por cada tamano:

  formato   emitio bloques parseables
  aplica    el SEARCH calzo (aqui es donde deberia empezar a fallar: cuando el
            archivo no entra, el modelo copia mal el trozo a buscar)
  pasa      regresion + cambio, ejecutados

La REGRESION mira funciones del principio Y del final del archivo: si el
contexto se desborda, lo primero que se pierde es un extremo, y con asserts de
un solo lado no se veria.

    uso:  eval_techo_archivo.py [puerto] [etiqueta] [repeticiones]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_edicion import _correr                                  # noqa: E402

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8080"
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "modelo"
REPES = int(sys.argv[3]) if len(sys.argv) > 3 else 3
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
MAX_TOKENS = int(os.getenv("TECHO_MAX_TOKENS", "3000"))
TIMEOUT = int(os.getenv("TECHO_TIMEOUT", "600"))
TAMANOS = [int(x) for x in os.getenv(
    "TECHO_TAMANOS", "10000,20000,30000,40000,60000").split(",")]

SR_INI, SR_MED, SR_FIN = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"
_RE_SR = re.compile(
    r"^[ \t]*([\w./-]+\.py)[ \t]*\n[ \t]*" + re.escape(SR_INI) +
    r"[ \t]*\n(.*?)\n[ \t]*" + re.escape(SR_MED) +
    r"[ \t]*\n(.*?)\n[ \t]*" + re.escape(SR_FIN), re.S | re.M)


def fabricar(chars: int) -> str:
    """Relleno realista con la funcion objetivo al MEDIO y centinelas en los
    dos extremos. Al medio porque es el peor caso: si el modelo mira solo el
    principio o solo el final, la pierde."""
    cab = "def primera(x):\n    # centinela del principio\n    return x + 1\n\n\n"
    obj = "def objetivo(a, b):\n    # la que hay que cambiar\n    return a + b\n\n\n"
    pie = "def ultima(x):\n    # centinela del final\n    return x - 1\n"
    relleno = ""
    i = 0
    while len(cab) + len(relleno) + len(obj) + len(pie) < chars:
        relleno += (f"def relleno_{i}(v):\n    # linea de relleno para llegar "
                    f"al tamano buscado\n    return v * {i + 2}\n\n\n")
        i += 1
    mitad = len(relleno) // 2
    corte = relleno.find("\ndef ", mitad)
    corte = corte + 1 if corte > 0 else mitad
    return cab + relleno[:corte] + obj + relleno[corte:] + pie


def pedir(prompt: str) -> tuple[str, float]:
    cuerpo = json.dumps({"model": "local", "stream": False,
                         "max_tokens": MAX_TOKENS,
                         "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read())
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return (msg.get("content") or ""), time.time() - t0


def una(fuente: str) -> dict:
    prompt = (
        "Modifica el codigo Python que ya existe. Responde SOLO con bloques de "
        "busqueda y reemplazo, sin explicaciones. Cada bloque asi:\n\n"
        f"m.py\n{SR_INI}\nlas lineas EXACTAS que hay hoy\n{SR_MED}\n"
        f"las que las reemplazan\n{SR_FIN}\n\n"
        "Lo que va entre SEARCH y ======= tiene que ser copia LITERAL del "
        "archivo y aparecer UNA SOLA VEZ. No reescribas el archivo entero.\n\n"
        f"Archivo `m.py`:\n```python\n{fuente}\n```\n\n"
        "Cambio pedido: la funcion objetivo(a, b) tiene que devolver a * b en "
        "vez de a + b. No toques nada mas.")
    try:
        texto, seg = pedir(prompt)
    except Exception as e:
        return {"formato": 0, "aplica": 0, "pasa": 0, "seg": 0,
                "motivo": f"{type(e).__name__}: {e}"}

    limpio = re.sub(r"```(?:python|diff)?\s*\n", "", texto).replace("```", "")
    bloques = [b for b in _RE_SR.findall(limpio) if b[0] == "m.py"]
    if not bloques:
        return {"formato": 0, "aplica": 0, "pasa": 0, "seg": seg,
                "motivo": "sin bloques parseables"}

    nuevo = fuente
    for _, buscar, reemplazar in bloques:
        if nuevo.count(buscar) != 1:
            return {"formato": 1, "aplica": 0, "pasa": 0, "seg": seg,
                    "motivo": f"SEARCH aparece {nuevo.count(buscar)} veces"}
        nuevo = nuevo.replace(buscar, reemplazar, 1)

    # Los centinelas van a los DOS extremos: si el contexto se desborda, lo
    # primero que se pierde es una punta.
    reg = ["import m; assert m.primera(1) == 2, 'centinela del principio'",
           "import m; assert m.ultima(1) == 0, 'centinela del final'"]
    cam = ["import m; assert m.objetivo(3, 4) == 12, 'el cambio pedido'"]
    ok_r, err = _correr({"m.py": nuevo}, reg)
    ok_c, _ = _correr({"m.py": nuevo}, cam)
    return {"formato": 1, "aplica": 1, "pasa": int(ok_r == 2 and ok_c == 1),
            "seg": seg,
            "motivo": "" if ok_r == 2 and ok_c == 1
                      else (f"regresion: {err}" if ok_r != 2 else "no hizo el cambio")}


def main() -> int:
    print(f"\n{'='*70}\n  TECHO DE ARCHIVO: {ETIQUETA}  (puerto {PUERTO})\n{'='*70}")
    print(f"  {len(TAMANOS)} tamanos x {REPES} repeticiones\n")
    print(f"  {'chars':>7}{'lineas':>8}{'formato':>9}{'aplica':>8}{'PASA':>7}{'seg':>7}")
    filas = []
    for chars in TAMANOS:
        fuente = fabricar(chars)
        acu = {"formato": 0, "aplica": 0, "pasa": 0, "seg": 0.0}
        motivos = []
        for _ in range(REPES):
            d = una(fuente)
            for k in acu:
                acu[k] += d[k]
            if d["motivo"]:
                motivos.append(d["motivo"])
        n = len(fuente.splitlines())
        print(f"  {len(fuente):>7}{n:>8}{acu['formato']:>6}/{REPES:<2}"
              f"{acu['aplica']:>5}/{REPES:<2}{acu['pasa']:>4}/{REPES:<2}"
              f"{acu['seg']/REPES:>7.0f}", flush=True)
        if motivos:
            print(f"          {motivos[0][:60]}")
        filas.append({"chars": len(fuente), "lineas": n, **acu,
                      "motivos": motivos})
    salida = (Path(__file__).resolve().parent.parent / "resultados" /
              f"resultado_techo_{ETIQUETA}.json")
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps({"etiqueta": ETIQUETA, "repes": REPES,
                                  "filas": filas}, indent=2, ensure_ascii=False))
    print(f"\n  guardado en {salida}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
