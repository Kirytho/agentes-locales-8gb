# -*- coding: utf-8 -*-
"""eval_memoria_posicion.py - ¿El modelo usa igual la memoria al final que al inicio?

El 18/08/2026 se movio la memoria recuperada del mensaje `system` (principio del
prompt) al ultimo mensaje del usuario (final), para que el prefijo quedara
estable y el cache del servidor sirviera. El riesgo no es de forma sino de
CALIDAD: el modelo pondera distinto lo que esta al principio y lo que esta
pegado a la pregunta.

Esto lo mide: conversaciones donde la respuesta correcta depende de un dato
dicho varios turnos antes. Se ejecuta con la memoria al final (por defecto) y con
INTERMEDIARIO_MEMORIA_AL_INICIO=1, y se compara cuantas veces el modelo recupera el dato.

Uso: python3 pruebas/subsistemas/eval_memoria_posicion.py [repes]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPES = int(sys.argv[1]) if len(sys.argv) > 1 else 1
URL = "http://127.0.0.1:8086/v1/chat/completions"

# Cada caso: turnos de relleno, la pregunta final, y que debe aparecer.
CASOS = [
    {"id": "puerto",
     "hechos": ["Mi servidor de desarrollo corre en el puerto 7421, anotalo.",
                "Explicame que es un decorador en Python, en dos lineas.",
                "Y que es un generador?",
                "Dame un ejemplo de list comprehension."],
     "pregunta": "En que puerto dije que corre mi servidor de desarrollo?",
     "debe": ["7421"]},
    {"id": "base",
     "hechos": ["Uso PostgreSQL 16 con el esquema 'ventas_2026'. Tenelo presente.",
                "Que hace el comando git stash?",
                "Explicame que es un indice parcial.",
                "Dame un ejemplo de JOIN."],
     "pregunta": "Que esquema de base de datos te dije que uso?",
     "debe": ["ventas_2026", "ventas 2026"]},
    {"id": "libreria",
     "hechos": ["En este proyecto usamos httpx, nunca requests. Importante.",
                "Como se maneja un timeout en Python?",
                "Que es async/await?",
                "Dame un ejemplo de context manager."],
     "pregunta": "Que libreria HTTP dije que usamos en este proyecto?",
     "debe": ["httpx"]},
    {"id": "version",
     "hechos": ["Estoy en Python 3.14 y no puedo cambiar de version.",
                "Que es un dataclass?",
                "Explicame el walrus operator.",
                "Que hace functools.cache?"],
     "pregunta": "Que version de Python te dije que uso?",
     "debe": ["3.14"]},
    {"id": "modelo",
     "hechos": ["Mi modelo de GPU es el Qwen3.8-9B, el de CPU es otro.",
                "Que es la cuantizacion de un modelo?",
                "Que significa Q5_K_M?",
                "Que es el KV cache?"],
     "pregunta": "Que modelo dije que corre en mi GPU?",
     "debe": ["qwen3.8", "qwen 3.8", "qwen3.8-9b"]},
]


def pedir(historial, max_tokens=140):
    cuerpo = json.dumps({"model": "auto", "messages": historial,
                         "max_tokens": max_tokens, "temperature": 0.2}).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return (d["choices"][0]["message"].get("content") or "")


def correr_caso(caso, sufijo):
    hist = []
    for h in caso["hechos"]:
        hist.append({"role": "user", "content": f"{h} (sesion {sufijo})"})
        hist.append({"role": "assistant", "content": pedir(hist, 60)})
    hist.append({"role": "user", "content": caso["pregunta"]})
    resp = pedir(hist)
    ok = any(d.lower() in resp.lower() for d in caso["debe"])
    return ok, resp.strip().replace("\n", " ")[:70]


print(f"\n{'='*72}\n  Memoria al final vs al inicio · {len(CASOS)} casos x {REPES}\n{'='*72}")
aciertos = 0
total = 0
for rep in range(REPES):
    for caso in CASOS:
        ok, resp = correr_caso(caso, f"{int(time.time())}-{rep}")
        aciertos += ok
        total += 1
        print(f"  {'OK ' if ok else 'NO '} {caso['id']:10s} {resp}")
print(f"\n  {aciertos}/{total} recuperaciones correctas\n")
