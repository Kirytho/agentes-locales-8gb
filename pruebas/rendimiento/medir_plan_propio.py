# -*- coding: utf-8 -*-
"""medir_plan_propio.py - ¿El plan que escribe gemma reparte tan bien como uno hecho a mano?

POR QUE EXISTE (22/08/2026)

`medir_reparto_piezas.py` mostro que repartir piezas entre agentes en paralelo
funciona: 20/20 de integracion, 3,4x mas rapido que el monolito. Pero ahi las
specs de cada pieza las escribio una persona y eran precisas. Era el TECHO: el
caso de "plan perfecto".

En el uso real uno le pide el plan a la IA. Esta medicion cierra esa brecha:
mismas tareas, mismos tests, pero las piezas salen del plan que escribe el
propio modelo.

  PLAN_MIO    specs escritas a mano (el techo ya medido, se recorre de nuevo
              en la misma sesion para que la comparacion sea limpia)
  PLAN_GEMMA  gemma lee el enunciado, escribe el reparto, y cada agente recibe
              solo la spec que gemma le asigno

Si el resultado baja, el problema esta en el plan y se ataca ahi. Si se
mantiene, el flujo queda validado punta a punta.

Se registran ademas los modos de falla del plan, que son propios de esta etapa:
que no devuelva JSON parseable, que invente nombres de funcion distintos a los
del enunciado, o que cambie la cantidad de piezas.

Uso:
    python3 pruebas/medir_plan_propio.py [repeticiones]
"""
import json
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

URL = "http://127.0.0.1:8080/v1/chat/completions"
REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "r1"
TOPE = 2048
TEMP = 0.1

ROL = (AQUI / "roles" / "corto.txt").read_text(encoding="utf-8").strip()

ROL_PLANIFICADOR = (
    "Eres un arquitecto de software. Vas a repartir el trabajo entre programadores "
    "que trabajan EN PARALELO y que NO van a ver el codigo de los otros. Por cada "
    "funcion del enunciado escribe una especificacion que alcance para "
    "implementarla sola: que recibe, que devuelve, la FORMA EXACTA de las "
    "estructuras de datos que se comparten entre funciones, y los casos borde.\n\n"
    "Usa EXACTAMENTE los nombres de funcion del enunciado.\n\n"
    "Responde SOLO con un JSON, sin texto alrededor:\n"
    '[{"nombre": "...", "spec": "..."}]'
)


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
    return texto, d.get("timings", {}).get("predicted_n", 0)


def extraer(texto):
    bloques = re.findall(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return "\n\n".join(b.strip() for b in bloques) if bloques else texto.strip()


def extraer_json(texto):
    """El plan tiene que venir como lista JSON. Devuelve (piezas, motivo_falla)."""
    crudo = texto.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", crudo, re.S)
    if m:
        crudo = m.group(1).strip()
    i, j = crudo.find("["), crudo.rfind("]")
    if i < 0 or j < 0:
        return None, "sin lista JSON"
    try:
        datos = json.loads(crudo[i:j + 1])
    except json.JSONDecodeError as e:
        return None, f"JSON invalido: {e.msg}"
    if not isinstance(datos, list) or not datos:
        return None, "lista vacia"
    piezas = []
    for d in datos:
        if not isinstance(d, dict) or "nombre" not in d or "spec" not in d:
            return None, "faltan claves nombre/spec"
        piezas.append((str(d["nombre"]), str(d["spec"])))
    return piezas, ""


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


def pedir_pieza(tarea, spec):
    usuario = (f"Contexto del modulo:\n{tarea['descripcion']}\n\n"
               f"Escribe UNICAMENTE esta funcion:\n{spec}")
    return llamar([{"role": "system", "content": ROL},
                   {"role": "user", "content": usuario}])


def paralelo(tarea, piezas):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, len(piezas))) as ex:
        futuros = [ex.submit(pedir_pieza, tarea, s) for _, s in piezas]
        salidas = [f.result() for f in futuros]
    codigo = "\n\n".join(extraer(t) for t, _ in salidas)
    return codigo, time.time() - t0, sum(k for _, k in salidas)


def evaluar(tarea, codigo):
    piezas_ok = {}
    for nombre, tests in tarea["tests_pieza"].items():
        ok, err = correr(codigo + "\n" + tests)
        piezas_ok[nombre] = {"ok": ok, "err": err}
    integ_ok, integ_err = correr(codigo + "\n" + tarea["integracion"])
    return piezas_ok, integ_ok, integ_err


print(f"\n{'=' * 96}\n  ¿El plan que escribe gemma reparte tan bien como uno hecho a mano?"
      f"\n  {len(TAREAS)} tareas · {REPS} repeticiones · gemma-4-E4B\n{'=' * 96}")

res = []
for rep in range(1, REPS + 1):
    for tarea in TAREAS:
        esperados = [n for n, _ in tarea["piezas"]]

        # ---- PLAN_MIO: el techo ----
        cod, seg, tok = paralelo(tarea, tarea["piezas"])
        pz, integ, ierr = evaluar(tarea, cod)
        n_ok = sum(1 for v in pz.values() if v["ok"])
        res.append({"rep": rep, "tarea": tarea["id"], "modo": "plan_mio",
                    "piezas_ok": n_ok, "piezas_de": len(pz), "integracion": integ,
                    "integracion_err": ierr, "segundos": seg, "tokens": tok,
                    "plan_ok": True, "plan_falla": "", "n_piezas": len(tarea["piezas"]),
                    "nombres_ok": True})
        print(f"  r{rep} {tarea['id']:12s} plan_mio    piezas {n_ok}/{len(pz)}  "
              f"integracion {'OK   ' if integ else 'FALLA'}  {seg:5.1f}s {tok:5d}tok",
              flush=True)

        # ---- PLAN_GEMMA: el plan lo escribe el modelo ----
        t0 = time.time()
        texto, tok_plan = llamar([{"role": "system", "content": ROL_PLANIFICADOR},
                                  {"role": "user", "content": tarea["descripcion"]}])
        seg_plan = time.time() - t0
        piezas, falla = extraer_json(texto)
        if piezas is None:
            res.append({"rep": rep, "tarea": tarea["id"], "modo": "plan_gemma",
                        "piezas_ok": 0, "piezas_de": len(tarea["tests_pieza"]),
                        "integracion": False, "integracion_err": "plan ilegible",
                        "segundos": seg_plan, "tokens": tok_plan,
                        "plan_ok": False, "plan_falla": falla, "n_piezas": 0,
                        "nombres_ok": False, "plan_crudo": texto[:800]})
            print(f"  r{rep} {tarea['id']:12s} plan_gemma  PLAN ILEGIBLE: {falla}",
                  flush=True)
            continue
        nombres = [n for n, _ in piezas]
        nombres_ok = set(nombres) == set(esperados)
        cod, seg, tok = paralelo(tarea, piezas)
        pz, integ, ierr = evaluar(tarea, cod)
        n_ok = sum(1 for v in pz.values() if v["ok"])
        res.append({"rep": rep, "tarea": tarea["id"], "modo": "plan_gemma",
                    "piezas_ok": n_ok, "piezas_de": len(pz), "integracion": integ,
                    "integracion_err": ierr, "segundos": seg_plan + seg,
                    "tokens": tok_plan + tok, "plan_ok": True, "plan_falla": "",
                    "n_piezas": len(piezas), "nombres_ok": nombres_ok,
                    "nombres": nombres, "plan": piezas})
        aviso = "" if nombres_ok else f" NOMBRES: {nombres}"
        print(f"  r{rep} {tarea['id']:12s} plan_gemma  piezas {n_ok}/{len(pz)}  "
              f"integracion {'OK   ' if integ else 'FALLA'}  "
              f"{seg_plan + seg:5.1f}s {tok_plan + tok:5d}tok  "
              f"({len(piezas)} piezas){aviso}", flush=True)

print(f"\n{'=' * 96}")
resumen = {}
for modo in ("plan_mio", "plan_gemma"):
    f = [r for r in res if r["modo"] == modo]
    pz = sum(r["piezas_ok"] for r in f)
    pzde = sum(r["piezas_de"] for r in f)
    integ = sum(1 for r in f if r["integracion"])
    seg = sum(r["segundos"] for r in f)
    tok = sum(r["tokens"] for r in f)
    ilegibles = sum(1 for r in f if not r["plan_ok"])
    mal_nombre = sum(1 for r in f if r["plan_ok"] and not r["nombres_ok"])
    resumen[modo] = {"piezas": pz, "piezas_de": pzde, "integracion": integ,
                     "de": len(f), "segundos": seg, "tokens": tok,
                     "planes_ilegibles": ilegibles, "nombres_cambiados": mal_nombre}
    extra = ""
    if modo == "plan_gemma":
        extra = f"   planes ilegibles {ilegibles}/{len(f)} · nombres cambiados {mal_nombre}/{len(f)}"
    print(f"  {modo:11s} piezas {pz:3d}/{pzde} ({100*pz/pzde:5.1f}%)   "
          f"INTEGRACION {integ:2d}/{len(f)} ({100*integ/len(f):5.1f}%)   "
          f"{seg/len(f):5.1f}s/tarea  {tok//len(f):5d}tok/tarea{extra}")

salida = AQUI / f"resultado_plan_propio_{ETIQUETA}.json"
salida.write_text(json.dumps({"reps": REPS, "resumen": resumen, "detalle": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
