# -*- coding: utf-8 -*-
"""medir_contexto.py - Cuanto contexto consume de verdad un pedido al intermediario.

POR QUE (17/08/2026)

Subir `--parallel` de 2 a 4 en el backend GPU sube el rendimiento agregado de
88,7 a 119,8 tok/s, pero parte el contexto: `--ctx-size` es el total y se
reparte entre slots, asi que cada agente pasa de 8192 a 4096 tokens.

La pregunta que decide el cambio es: **cuanto contexto usa un pedido real**.
Y "real" en el intermediario no es lo que envia el cliente: el intermediario le agrega
memoria recuperada de conversaciones anteriores antes de enviarlo al modelo.
Ese agregado no se ve desde fuera.

COMO SE MIDE

Se envia una conversacion completa contra el intermediario (:8086), como la
enviaria un cliente: en cada turno el historial entero mas el mensaje nuevo.
El `usage.prompt_tokens` que devuelve la respuesta es el conteo del modelo
sobre el prompt YA construido -- es decir, con la memoria inyectada dentro.

LIMITES QUE PONE EL INTERMEDIARIO (para leer el resultado en contexto):
  - historial recortado a 15 mensajes (GPU) / 8 (CPU)
  - 1000 (GPU) / 500 (CPU) caracteres de bloques de memoria, y ademas
    comprimidos al 50%
  - k=5 fragmentos relevantes, relevancia minima 0.35

Uso:
    python3 pruebas/rendimiento/medir_contexto.py [puerto]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8086"
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"

# Conversacion de trabajo real: empieza corta y se va cargando de historial,
# que es como crece un agente que sostiene una tarea.
TURNOS = [
    "Necesito armar un scraper en Python para una tabla HTML. Por donde empiezo?",
    "Usa requests y BeautifulSoup. Escribeme la funcion que baja la pagina.",
    "Ahora la funcion que parsea la tabla y devuelve una lista de diccionarios.",
    "Que pasa si la tabla tiene celdas combinadas con colspan?",
    "Agregale manejo de errores: timeout, status distinto de 200, tabla ausente.",
    "Escribe los tests de pytest para esas tres funciones.",
    "Como lo hago para que reintente tres veces con espera creciente?",
    "Ahora quiero guardarlo en SQLite. Escribe el esquema de la tabla.",
    "Y la funcion que inserta evitando duplicados por URL.",
    "Resumeme todo lo que llevamos hasta ahora en una lista de pasos.",
    "Cual de todas las funciones que escribimos es la mas fragil y por que?",
    "Escribe el README del proyecto con lo que hicimos.",
]


def pedir(historial):
    cuerpo = json.dumps({
        "model": "auto",
        "messages": historial,
        "max_tokens": 120,
        "temperature": 0.3,
        "stream": False,
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    u = d.get("usage", {}) or {}
    contenido = (d["choices"][0]["message"].get("content") or "")
    return {
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "modelo": d.get("model", "?"),
        "segundos": time.time() - t0,
        "respuesta": contenido,
    }


historial = []
filas = []
print(f"\n{'='*74}\n  Contexto real por pedido · intermediario :{PUERTO}\n{'='*74}")
print(f"  {'turno':>5s} {'msgs enviados':>14s} {'prompt tok':>11s} {'salida':>7s} "
      f"{'modelo':>10s} {'seg':>6s}")

for i, texto in enumerate(TURNOS, 1):
    historial.append({"role": "user", "content": texto})
    try:
        r = pedir(historial)
    except Exception as e:  # noqa: BLE001
        print(f"  {i:5d}  FALLO: {str(e)[:80]}")
        break
    historial.append({"role": "assistant", "content": r["respuesta"]})
    filas.append({"turno": i, "mensajes": len(historial) - 1, **r})
    print(f"  {i:5d} {len(historial)-1:14d} {r['prompt_tokens']:11d} "
          f"{r['completion_tokens']:7d} {r['modelo']:>10s} {r['segundos']:6.1f}")

if filas:
    picos = [f["prompt_tokens"] for f in filas]
    print(f"\n  prompt_tokens: min {min(picos)} · mediana "
          f"{sorted(picos)[len(picos)//2]} · max {max(picos)}")
    print(f"  contexto total del pedido mas grande (prompt + salida): "
          f"{max(f['prompt_tokens'] + f['completion_tokens'] for f in filas)} tokens")
    for limite in (4096, 8192):
        margen = max(picos) / limite * 100
        print(f"  contra un slot de {limite}: usa el {margen:.1f}% en el peor caso")

    salida = AQUI / "resultado_contexto.json"
    salida.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Crudos en {salida}\n")
