# -*- coding: utf-8 -*-
"""medir_pipeline.py - Planificar antes de programar, ¿sirve o solo cuesta?

POR QUE EXISTE (19/08/2026)

El intermediario tiene un pipeline de dos etapas para tareas de codigo: primero un
PLANIFICADOR escribe un plan de arquitectura, despues un EJECUTOR escribe el
codigo siguiendo ese plan. La idea es que pensar antes mejore el resultado.

Nunca se midio. Y al revisarlo el 19/08 se descubrio que **jamas habia
terminado una ejecucion**: el planificador apuntaba al modelo de CPU con
max_tokens 4096 y timeout 60 s, es decir 256 s de generacion contra 60 de plazo.
6 activaciones, 6 fracasos, 0 exitos: quemaba 60 s y despues hacia el trabajo
por el camino normal.

Antes de arreglarlo hay que responder si vale la pena arreglarlo. Este banco
compara, sobre las MISMAS tareas y con los MISMOS tests de la bateria como
juez:

  DIRECTO   una sola llamada: "escribe el codigo"
  PIPELINE  dos llamadas: plan (sin codigo) y despues codigo guiado por el plan

Se reportan las dos cosas que importan para decidir: cuanto CUESTA cada modo
(segundos y tokens) y cuanto ACIERTA (tests que pasan). Los dos modos se ejecutan
contra el mismo backend de GPU, asi que la comparacion es limpia.

Uso:
    python3 pruebas/medir_pipeline.py [n_tareas]
"""
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# pruebas/ se reorganizo en carpetas el 07/09/2026: los bancos de calidad
# viven en pruebas/calidad/. Sin esta linea el import de abajo no los
# encuentra desde otra subcarpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "calidad"))
from eval_expertos import TAREAS  # noqa: E402  (mismas tareas, mismos tests)

URL = "http://127.0.0.1:8080/v1/chat/completions"   # GPU, sin intermediario
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
# El mismo tope para los dos modos. La primera ejecucion uso 900 y arruino la
# medicion: el ejecutor del pipeline, al que se le pide codigo "de produccion",
# escribe mucho mas largo y se cortaba a la mitad. Los 9 fallos eran
# SyntaxError por truncamiento, no codigo malo. Ahora ademas se REPORTA si la
# respuesta se corto, para que no vuelva a pasar sin que se note.
TOPE = 2048

# El prompt de planificacion es el que usa el intermediario en produccion.
PLANNING_PROMPT = (
    "Eres un arquitecto de software experto. Crea un plan detallado para implementar "
    "el codigo que el usuario solicita.\n\n"
    "Responde SOLO con el plan, sin codigo. Incluye:\n"
    "1. Analisis del problema y requisitos\n"
    "2. Estructura de archivos/components necesarios\n"
    "3. Logica principal, algoritmos y flujo de datos\n"
    "4. Consideraciones tecnicas (async, errores, performance, seguridad)\n"
    "5. Pasos de implementacion ordenados\n\n"
    "Maximo 500 palabras. Se conciso pero completo."
)
EXECUTION_PROMPT = (
    "A continuacion tienes un plan de arquitectura. Genera el codigo COMPLETO y FUNCIONAL "
    "siguiendo este plan.\n\n"
    "IMPORTANTE:\n"
    "- Incluye TODOS los imports necesarios\n"
    "- Manejo de errores en cada operacion\n"
    "- Codigo listo para produccion\n"
    "- No omitas secciones ni uses '...' como placeholder"
)


def llamar(mensajes, max_tokens):
    cuerpo = json.dumps({
        "model": "x", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": 0.1, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    texto = (d["choices"][0]["message"].get("content") or "").strip()
    corte = d["choices"][0].get("finish_reason") == "length"
    tim = d.get("timings", {})
    return texto, time.time() - t0, tim.get("predicted_n", 0), corte


def extraer_codigo(texto):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return (m.group(1) if m else texto).strip()


def probar(codigo, tests):
    fuente = codigo + "\n\n" + tests + "\nprint('OK')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(fuente)
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=15, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:80]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        Path(ruta).unlink(missing_ok=True)


def directo(tarea):
    texto, seg, tok, corte = llamar(
        [{"role": "user", "content": tarea["prompt"]}], TOPE)
    ok, err = probar(extraer_codigo(texto), tarea["tests"])
    return {"ok": ok, "err": err, "segundos": seg, "tokens": tok, "plan_tok": 0,
            "truncado": corte}


def pipeline(tarea):
    plan, seg1, tok1, _ = llamar(
        [{"role": "system", "content": PLANNING_PROMPT},
         {"role": "user", "content": tarea["prompt"]}], 1024)
    texto, seg2, tok2, corte = llamar(
        [{"role": "system", "content": EXECUTION_PROMPT},
         {"role": "user", "content": f"{tarea['prompt']}\n\n[PLAN]\n{plan}"}], TOPE)
    ok, err = probar(extraer_codigo(texto), tarea["tests"])
    return {"ok": ok, "err": err, "segundos": seg1 + seg2, "tokens": tok1 + tok2,
            "plan_tok": tok1, "plan_seg": seg1, "code_seg": seg2, "truncado": corte}


tareas = TAREAS[:N]
print(f"\n{'=' * 78}\n  Planificar antes de programar · {len(tareas)} tareas de la bateria"
      f"\n  los dos modos contra el mismo backend de GPU\n{'=' * 78}")
print(f"  {'tarea':22s} {'DIRECTO':>18s}   {'PIPELINE (plan+codigo)':>24s}")

res = []
for t in tareas:
    d = directo(t)
    p = pipeline(t)
    res.append({"id": t["id"], "directo": d, "pipeline": p})
    md = "PASA" if d["ok"] else "falla"
    mp = "PASA" if p["ok"] else "falla"
    print(f"  {t['id']:22s} {md:>5s} {d['segundos']:5.1f}s {d['tokens']:4d}tok   "
          f"{mp:>5s} {p['segundos']:5.1f}s {p['tokens']:4d}tok "
          f"(plan {p['plan_tok']:4d})")

for modo in ("directo", "pipeline"):
    ok = sum(1 for r in res if r[modo]["ok"])
    seg = sum(r[modo]["segundos"] for r in res)
    tok = sum(r[modo]["tokens"] for r in res)
    cortadas = sum(1 for r in res if r[modo].get("truncado"))
    print(f"\n  {modo.upper():9s} {ok}/{len(res)} tests · {seg:6.1f}s totales "
          f"({seg / len(res):5.1f}s por tarea) · {tok} tokens"
          + (f" · TRUNCADAS {cortadas} (la medicion NO vale)" if cortadas else ""))

sd = sum(r["directo"]["segundos"] for r in res)
sp = sum(r["pipeline"]["segundos"] for r in res)
od = sum(1 for r in res if r["directo"]["ok"])
op = sum(1 for r in res if r["pipeline"]["ok"])
print(f"\n  El pipeline cuesta {sp / sd:.2f}x el tiempo y acierta "
      f"{op - od:+d} tareas sobre {len(res)}.")

salida = AQUI / "resultado_pipeline.json"
salida.write_text(json.dumps({"tareas": len(res), "detalle": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
