# -*- coding: utf-8 -*-
"""medir_reparto_piezas.py - Repartir piezas entre agentes, ¿las piezas encajan?

POR QUE EXISTE (22/08/2026)

Ya se midio y se descarto el bloque "3 agentes hacen la MISMA tarea y uno
elige": no hay dispersion que explotar (5/53 tareas con candidatas mixtas) y ni
el juez ni los tests generados eligen bien.

Esto es lo otro, y es lo que se hace de verdad al programar: UNA tarea, un plan,
K pasos independientes, en paralelo. No hay que elegir nada; hay que repartir e
integrar. Nunca se midio porque la bateria son funciones de 20 lineas y no hay
nada que repartir. Por eso existe `banco_compuesto.py`.

La pregunta es UNA y es la de integracion. Cuando un solo agente escribe todo,
las interfaces le salen coherentes gratis. Cuando cuatro agentes escriben en
paralelo viendo solo su pieza, el riesgo real es que uno devuelva un dict donde
el otro espera una tupla. Los tests por pieza NO detectan eso.

Tres condiciones sobre las mismas tareas:

  MONOLITO    una llamada, escribe las cuatro piezas de una
  SECUENCIAL  cuatro llamadas, cada una VE el codigo ya escrito
  PARALELO    cuatro llamadas a la vez, cada una ve SOLO su pieza

PARALELO usa las specs del banco, que son precisas: es el TECHO, el caso de
"plan perfecto". Si aun asi las piezas no encajan, la idea se cae sin importar
que tan bueno sea el plan que escriba el modelo. Por eso se mide el techo
primero.

Uso:
    python3 pruebas/rendimiento/medir_reparto_piezas.py [repeticiones]
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# pruebas/ se reorganizo en carpetas el 07/09/2026: los bancos de calidad
# viven en pruebas/calidad/. Sin esta linea el import de abajo no los
# encuentra desde otra subcarpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "calidad"))
from banco_compuesto import TAREAS  # noqa: E402

# Con BANCO=grande se usan las tareas de 10 y 12 piezas, para cruzar el umbral
# de kernel (9 pedidos simultaneos). Ver banco_compuesto_grande.py.
if os.getenv("BANCO", "chico") == "grande":
    from banco_compuesto_grande import TAREAS_GRANDES
    TAREAS = TAREAS_GRANDES

URL = "http://127.0.0.1:8080/v1/chat/completions"
REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "r1"
# 2048 alcanza para una pieza, pero el MONOLITO con 12 funciones se corta ahi y
# el fallo seria del limite, no del modelo (ya paso una vez en este proyecto).
TOPE = int(os.getenv("BANCO_TOPE", "4096"))
TEMP = 0.1

ROL = (AQUI.parent / "roles" / "corto.txt").read_text(encoding="utf-8").strip()


def llamar(mensajes, max_tokens=TOPE):
    cuerpo = json.dumps({
        "model": "x", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": TEMP, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    texto = (d["choices"][0]["message"].get("content") or "").strip()
    corte = d["choices"][0].get("finish_reason") == "length"
    return texto, d.get("timings", {}).get("predicted_n", 0), corte


def extraer(texto):
    bloques = re.findall(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return "\n\n".join(b.strip() for b in bloques) if bloques else texto.strip()


def correr(fuente):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(fuente + "\nprint('OK')\n")
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=20, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:110]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        Path(ruta).unlink(missing_ok=True)


def pedir_pieza(tarea, nombre, spec, contexto=""):
    """Un agente escribe UNA pieza. `contexto` es el codigo ya escrito (o nada)."""
    usuario = (f"Contexto del modulo:\n{tarea['descripcion']}\n\n"
               f"Escribe UNICAMENTE esta funcion:\n{spec}")
    if contexto:
        usuario += (f"\n\nCodigo ya escrito por otros (no lo repitas, usalo si "
                    f"lo necesitas):\n```python\n{contexto}\n```")
    return llamar([{"role": "system", "content": ROL},
                   {"role": "user", "content": usuario}])


# ---------------- condiciones ----------------

def monolito(tarea):
    t0 = time.time()
    texto, tok, corte = llamar([{"role": "system", "content": ROL},
                                {"role": "user", "content": tarea["descripcion"]}])
    return extraer(texto), time.time() - t0, tok, corte


def secuencial(tarea):
    t0 = time.time()
    partes, tok, cortes = [], 0, False
    for nombre, spec in tarea["piezas"]:
        texto, k, c = pedir_pieza(tarea, nombre, spec, "\n\n".join(partes))
        partes.append(extraer(texto))
        tok += k
        cortes = cortes or c
    return "\n\n".join(partes), time.time() - t0, tok, cortes


def paralelo(tarea):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(tarea["piezas"])) as ex:
        futuros = [ex.submit(pedir_pieza, tarea, n, s) for n, s in tarea["piezas"]]
        salidas = [f.result() for f in futuros]
    partes = [extraer(t) for t, _, _ in salidas]
    return ("\n\n".join(partes), time.time() - t0, sum(k for _, k, _ in salidas),
            any(c for _, _, c in salidas))


MODOS = {"monolito": monolito, "secuencial": secuencial, "paralelo": paralelo}

print(f"\n{'=' * 92}\n  Repartir piezas entre agentes · {len(TAREAS)} tareas · "
      f"{REPS} repeticiones · gemma-4-E4B\n"
      f"  la pregunta es la INTEGRACION: ¿encajan las piezas escritas por separado?"
      f"\n{'=' * 92}")

res = []
for rep in range(1, REPS + 1):
    for tarea in TAREAS:
        for modo, fn in MODOS.items():
            codigo, seg, tok, corte = fn(tarea)
            piezas = {}
            for nombre, tests in tarea["tests_pieza"].items():
                ok, err = correr(codigo + "\n" + tests)
                piezas[nombre] = {"ok": ok, "err": err}
            integ_ok, integ_err = correr(codigo + "\n" + tarea["integracion"])
            n_ok = sum(1 for v in piezas.values() if v["ok"])
            res.append({"rep": rep, "tarea": tarea["id"], "modo": modo,
                        "piezas_ok": n_ok, "piezas_de": len(piezas),
                        "integracion": integ_ok, "integracion_err": integ_err,
                        "segundos": seg, "tokens": tok, "detalle": piezas,
                        "truncado": corte, "codigo": codigo})
            print(f"  r{rep} {tarea['id']:12s} {modo:11s} piezas {n_ok}/{len(piezas)}  "
                  f"integracion {'OK   ' if integ_ok else 'FALLA'}  "
                  f"{seg:5.1f}s {tok:5d}tok  {'TRUNCADO ' if corte else ''}"
                  f"{'' if integ_ok else integ_err[:55]}",
                  flush=True)

print(f"\n{'=' * 92}")
resumen = {}
n_tareas = len(TAREAS) * REPS
for modo in MODOS:
    filas = [r for r in res if r["modo"] == modo]
    pz = sum(r["piezas_ok"] for r in filas)
    pz_de = sum(r["piezas_de"] for r in filas)
    integ = sum(1 for r in filas if r["integracion"])
    seg = sum(r["segundos"] for r in filas)
    tok = sum(r["tokens"] for r in filas)
    trunc = sum(1 for r in filas if r.get("truncado"))
    resumen[modo] = {"piezas": pz, "piezas_de": pz_de, "integracion": integ,
                     "de": len(filas), "segundos": seg, "tokens": tok,
                     "truncadas": trunc}
    print(f"  {modo:11s} piezas {pz:3d}/{pz_de}  ({100*pz/pz_de:5.1f}%)   "
          f"INTEGRACION {integ:2d}/{len(filas)} ({100*integ/len(filas):5.1f}%)   "
          f"{seg/len(filas):5.1f}s/tarea  {tok//len(filas):5d}tok/tarea"
          + (f"  TRUNCADAS {trunc} (no vale)" if trunc else ""))

print("\n  Lo que importa: si PARALELO tiene las piezas bien pero la integracion"
      "\n  mal, el problema son las interfaces, no la capacidad de programar.")

salida = AQUI / f"resultado_reparto_piezas_{ETIQUETA}.json"
salida.write_text(json.dumps({"reps": REPS, "resumen": resumen, "detalle": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
