# -*- coding: utf-8 -*-
"""medir_respuesta.py - Cuanto se tarda en GENERAR, y cuanto en empezar.

POR QUE (19/08/2026)

El barrido del camino del prompt mostro que leer el historial ya no es el
problema: en una charla de 8 turnos, 85% del tiempo se va en generar y solo 15%
en el modelo de GPU entero. Generar es lineal en tokens de salida, y
`profiles.json` deja `max_tokens` en 4096 para codigo y razonamiento. Nadie
midio cuanto escriben realmente las respuestas ni si hace falta que escriban
tanto.

Este banco mide dos cosas que atacan ese 85%:

  LARGO   cuantos tokens genera cada respuesta con los topes de hoy, y cuanto
          bajaria el tiempo pidiendo respuestas mas cortas.

  ARRANQUE  cuanto tarda el PRIMER token con streaming. No cambia el total,
            cambia la espera: ver salir palabras a los 2 s no es lo mismo que
            mirar la pantalla quieta 17 s.

Uso:
    python3 pruebas/medir_respuesta.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
URL = "http://127.0.0.1:8086/v1/chat/completions"

# Dos que van a GPU (codigo) y dos que van a RAM (analisis), para ver los dos
# regimenes por separado.
# El backend va fijado en cada caso, no se deja clasificar.
CASOS = [
    ("codigo GPU", "principal", "Escribe una funcion Python que valide un RUT chileno con su digito verificador."),
    ("codigo GPU", "principal", "Escribe una funcion que agrupe una lista de diccionarios por una clave."),
    ("analisis RAM", "qwen3", "Analiza que ventajas y desventajas tiene guardar sesiones en memoria contra guardarlas en SQLite."),
    ("analisis RAM", "qwen3", "Explica por que conviene separar el clasificador del ruteo en un orquestador de modelos."),
]

BREVE = ("Responde de forma directa y compacta. Si es codigo, solo el codigo con "
         "un comentario por bloque. Sin introduccion ni resumen final.")


def pedir(prompt, sistema=None, tope=None, marca="", modelo="auto"):
    # El backend se FUERZA. La primera version dejaba clasificar (`model:
    # auto`) y el mensaje `system` con la instruccion de brevedad hacia que el
    # clasificador cambiara de modelo: la variante normal se iba a la GPU y la
    # breve a RAM, asi que la comparacion mezclaba brevedad con backend
    # (19/08/2026).
    msgs = ([{"role": "system", "content": sistema}] if sistema else [])
    msgs.append({"role": "user", "content": f"{prompt} {marca}"})
    cuerpo = {"model": modelo, "messages": msgs, "temperature": 0}
    if tope:
        cuerpo["max_tokens"] = tope
    req = urllib.request.Request(URL, data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    u = d.get("usage", {})
    return {"segundos": time.time() - t0, "salida": u.get("completion_tokens", 0),
            "backend": d.get("_backend"), "texto": d["choices"][0]["message"]["content"]}


def pedir_stream(prompt, marca="", modelo="auto"):
    """Mide cuanto tarda el PRIMER token frente al total."""
    cuerpo = {"model": modelo, "temperature": 0, "stream": True,
              "messages": [{"role": "user", "content": f"{prompt} {marca}"}]}
    req = urllib.request.Request(URL, data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    primero = None
    trozos = 0
    with urllib.request.urlopen(req, timeout=900) as r:
        for linea in r:
            if not linea.startswith(b"data: "):
                continue
            crudo = linea[6:].strip()
            if crudo == b"[DONE]":
                break
            try:
                delta = json.loads(crudo)["choices"][0].get("delta", {})
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta.get("content"):
                trozos += 1
                if primero is None:
                    primero = time.time() - t0
    return {"primer_token": primero or 0, "total": time.time() - t0, "trozos": trozos}


sello = str(int(time.time()))
print(f"\n{'=' * 78}\n  1. LARGO DE RESPUESTA · con los topes de hoy contra pidiendo brevedad"
      f"\n{'=' * 78}")
print(f"  {'caso':10s} {'':28s} {'normal':>18s}   {'breve':>18s}")
filas = []
for i, (clase, modelo, prompt) in enumerate(CASOS):
    a = pedir(prompt, marca=f"[{sello}-a{i}]", modelo=modelo)
    b = pedir(prompt, sistema=BREVE, marca=f"[{sello}-b{i}]", modelo=modelo)
    filas.append({"clase": clase, "prompt": prompt[:40], "normal": a, "breve": b})
    print(f"  {clase:10s} {prompt[:28]:28s} "
          f"{a['salida']:5d} tok {a['segundos']:6.1f}s   "
          f"{b['salida']:5d} tok {b['segundos']:6.1f}s   ({a['backend']}"
          + ("" if a['backend'] == b['backend'] else f"/{b['backend']} OJO") + ")")

for k in ("normal", "breve"):
    tok = sum(f[k]["salida"] for f in filas)
    seg = sum(f[k]["segundos"] for f in filas)
    print(f"\n  {k.upper():7s} {tok:5d} tokens · {seg:6.1f}s")
ahorro = 1 - sum(f["breve"]["segundos"] for f in filas) / sum(f["normal"]["segundos"] for f in filas)
print(f"\n  Pedir brevedad ahorra {ahorro * 100:.0f}% del tiempo.")

print(f"\n{'=' * 78}\n  2. ARRANQUE · cuanto tarda el primer token con streaming\n{'=' * 78}")
print(f"  {'caso':10s} {'':28s} {'1er token':>11s} {'total':>9s} {'espera evitada':>16s}")
for i, (clase, modelo, prompt) in enumerate(CASOS):
    s = pedir_stream(prompt, marca=f"[{sello}-s{i}]", modelo=modelo)
    print(f"  {clase:10s} {prompt[:28]:28s} {s['primer_token']:9.1f}s {s['total']:8.1f}s "
          f"{s['total'] - s['primer_token']:14.1f}s")

salida = AQUI / "resultado_respuesta.json"
salida.write_text(json.dumps({"largo": [{k: (v if not isinstance(v, dict) else
                                             {kk: vv for kk, vv in v.items() if kk != "texto"})
                                         for k, v in f.items()} for f in filas]},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
