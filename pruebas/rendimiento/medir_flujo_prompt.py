# -*- coding: utf-8 -*-
"""medir_flujo_prompt.py - Que valor conviene en cada perilla del prompt.

POR QUE (19/08/2026)

El camino que recorre un pedido tiene una decena de numeros escritos a mano que
nadie midio nunca: cuantos mensajes de historial se envian (15 en GPU, 8 en
CPU), cuantos recuerdos se recuperan (5 y 2), con que relevancia minima (0,35),
cuanto presupuesto de tokens tiene la memoria (1000 y 500), cuantos caracteres
por recuerdo (500 y 200), y los dos que se agregaron hoy: la cabeza fija del
prompt (3 mensajes) y cada cuanto salta el punto de corte (max/3).

Cada uno mueve dos cosas en direcciones opuestas:

  - MAS historial y MAS memoria = el modelo sabe mas, pero el prompt es mas
    largo y hay mas que releer.
  - MENOS = mas rapido, pero el modelo se olvida.

Este banco mide la parte que SI se puede medir a maquina: cuanto tarda la
conversacion, cuantos tokens se reutilizan y cuanto ocupa el prompt. Lo que NO
mide es si las respuestas siguen siendo buenas -- eso queda para la bateria.

Uso:
    python3 pruebas/medir_flujo_prompt.py [etiqueta]

La configuracion se pasa por entorno (INTERMEDIARIO_MAX_MSGS, INTERMEDIARIO_CABEZA_FIJA, ...);
el script solo mide lo que se este ejecutando. `pruebas/barrer_flujo.sh` lo llama
una vez por configuracion, reiniciando el intermediario entre una y otra.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "http://127.0.0.1:8086/v1/chat/completions"
ETIQUETA = sys.argv[1] if len(sys.argv) > 1 else "sin-etiqueta"

# Conversacion de trabajo: mezcla planificacion (va a RAM) con pedidos de
# codigo (van a GPU), que es justo el caso donde el prompt rebota entre modelos.
TURNOS = [
    "Quiero armar un lector de recibos de supermercado. Por donde empiezo?",
    "Escribe la funcion que lea el archivo y devuelva las lineas limpias.",
    "Como manejo los recibos donde el total no cuadra con la suma?",
    "Escribe la funcion que valide el total contra la suma de items.",
    "Que estructura de carpetas le pondrias al proyecto?",
    "Escribe el modulo de exportacion a CSV.",
    "Como conviene testear la parte de parseo?",
    "Resumeme el plan que llevamos hasta ahora.",
]


def turno(mensajes, sesion):
    cuerpo = json.dumps({
        "model": "auto", "messages": mensajes, "max_tokens": 110,
        "temperature": 0, "user": sesion,
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    u = d.get("usage", {})
    return {
        "segundos": time.time() - t0,
        "prompt": u.get("prompt_tokens", 0),
        "reusados": u.get("prompt_tokens_details", {}).get("cached_tokens", 0),
        "backend": d.get("_backend"),
        "texto": d["choices"][0]["message"]["content"],
    }


sesion = f"flujo-{int(time.time())}"
mensajes, filas = [], []
for i, q in enumerate(TURNOS, 1):
    mensajes.append({"role": "user", "content": q})
    r = turno(mensajes, sesion)
    filas.append(r)
    mensajes.append({"role": "assistant", "content": r["texto"]})
    time.sleep(2)   # el tiempo que la persona tarda en leer: se ejecuta el precalentado

seg = sum(f["segundos"] for f in filas)
prompt = sum(f["prompt"] for f in filas)
reus = sum(f["reusados"] for f in filas)
cpu = [f for f in filas if f["backend"] != "principal"]
conf = {k: v for k, v in os.environ.items() if k.startswith("INTERMEDIARIO_")}

print(f"  {ETIQUETA:22s} {seg:6.1f}s total · {seg / len(filas):5.1f}s por turno · "
      f"{reus}/{prompt} tokens reusados ({reus * 100 // prompt if prompt else 0}%) · "
      f"turnos en RAM {len(cpu)}")

salida = AQUI / "resultado_flujo_prompt.json"
hist = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else []
hist.append({"etiqueta": ETIQUETA, "config": conf, "segundos": seg,
             "prompt_total": prompt, "reusados": reus,
             "turnos": [{k: v for k, v in f.items() if k != "texto"} for f in filas]})
salida.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
