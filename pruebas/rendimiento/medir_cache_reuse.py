# -*- coding: utf-8 -*-
"""medir_cache_reuse.py - Dos preguntas de una sola ejecucion.

1) --cache-reuse: reaprovecha el KV del prefijo ya calculado cuando el pedido
   siguiente empieza igual. En una conversacion eso es TODO el historial, que
   se reenvia entero en cada turno. Se mide el tiempo de procesar el prompt
   (prompt_ms), no la generacion.

2) Latencia por agente bajo carga: hasta ahora se midio rendimiento AGREGADO
   (tokens totales / tiempo). Para un agente interactivo lo que importa es
   cuanto tarda SU pedido. Con 4 slots cada agente baja a ~32 tok/s, y esa
   caida puede pesar mas que el total del equipo.

Uso:  python3 pruebas/rendimiento/medir_cache_reuse.py [repeticiones]
"""
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# .parent.parent: este script vivia en pruebas/ y el 07/09 se movio a una
# subcarpeta. Con un solo .parent la raiz quedaba en pruebas/ y buscaba los
# binarios y los modelos en pruebas/backends/ y pruebas/modelos/, que no
# existen.
RAIZ = AQUI.parent.parent
BIN = RAIZ / "backends" / "linux" / "bin"
MODELO = RAIZ / "modelos" / "Qwen3.8-9B-Q5_K_M.gguf"
URL = "http://127.0.0.1:8080"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPES = int(sys.argv[1]) if len(sys.argv) > 1 else 3

BASE = [str(BIN / "llama-server"), "--model", str(MODELO),
        "--ctx-size", "16384", "--n-predict", "32768",
        "--host", "127.0.0.1", "--port", "8080",
        "--jinja", "--n-gpu-layers", "99", "--parallel", "4", "--kv-unified",
        "--flash-attn", "auto", "--cont-batching",
        "--cache-type-k", "q8_0", "--cache-type-v", "q4_0",
        "--threads", "6", "--temp", "0.6", "--top-p", "0.95", "--top-k", "20"]

CONFIGS = [("sin cache-reuse", []), ("con cache-reuse 256", ["--cache-reuse", "256"])]


def esperar(proc, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=2) as r:
                if json.loads(r.read()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def pedir(mensajes, max_tokens=48):
    cuerpo = json.dumps({"model": "x", "messages": mensajes, "max_tokens": max_tokens,
                         "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(f"{URL}/v1/chat/completions", data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    t = d.get("timings", {})
    return {"prompt_ms": t.get("prompt_ms", 0), "prompt_n": t.get("prompt_n", 0),
            "cache_n": t.get("cache_n", 0), "tok_s": t.get("predicted_per_second", 0),
            "pared": time.time() - t0}


def conversacion(turnos=8):
    """Turnos que reenvian todo el historial: el prefijo crece y se repite."""
    hist, filas = [], []
    for i in range(turnos):
        hist.append({"role": "user", "content":
                     f"Paso {i+1}: explica en dos lineas un concepto de Python distinto a los anteriores."})
        r = pedir(hist)
        hist.append({"role": "assistant", "content": "ok " * 40})
        filas.append(r)
    return filas


def concurrencia(n, prompts):
    """n pedidos a la vez; devuelve la latencia de cada uno."""
    salida = [None] * n
    def uno(i):
        salida[i] = pedir([{"role": "user", "content": prompts[i % len(prompts)]}], max_tokens=128)
    hilos = [threading.Thread(target=uno, args=(i,)) for i in range(n)]
    t0 = time.time()
    for h in hilos: h.start()
    for h in hilos: h.join()
    pared = time.time() - t0
    return [s for s in salida if s], pared


PROMPTS = ["Escribe una funcion que valide un email.",
           "Explica que es un indice en una base de datos.",
           "Escribe una consulta SQL de ejemplo.",
           "Diferencia entre proceso e hilo."]

resultados = {}
for nombre, extra in CONFIGS:
    print(f"\n{'='*66}\n  {nombre}\n{'='*66}")
    env = dict(os.environ, LD_LIBRARY_PATH=str(BIN))
    log = open(AQUI / "logs" / f"reuse_{nombre.split()[0]}.log", "wb")
    proc = subprocess.Popen(BASE + extra, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(BIN))
    try:
        if not esperar(proc):
            print("  NO ARRANCO"); continue
        # 1) prefijo repetido
        muestras = [conversacion() for _ in range(REPES)]
        por_turno = list(zip(*muestras, strict=True))
        prompt_ms = [statistics.mean(t["prompt_ms"] for t in turno) for turno in por_turno]
        cache_n = [statistics.mean(t["cache_n"] for t in turno) for turno in por_turno]
        prompt_n = [statistics.mean(t["prompt_n"] for t in turno) for turno in por_turno]
        print("  turno   prompt_n   cache_n   prompt_ms")
        for i, (pn, cn, ms) in enumerate(zip(prompt_n, cache_n, prompt_ms, strict=True), 1):
            print(f"  {i:5d} {pn:10.0f} {cn:9.0f} {ms:11.1f}")
        # 2) latencia por agente
        lat = {}
        for n in (1, 2, 4):
            todas = []
            for _ in range(REPES):
                rs, pared = concurrencia(n, PROMPTS)
                todas.extend(r["pared"] for r in rs)
            lat[n] = {"media": statistics.mean(todas), "p95": max(todas),
                      "min": min(todas)}
            print(f"  {n} agente(s): latencia media {lat[n]['media']:.2f}s "
                  f"(min {lat[n]['min']:.2f}, max {lat[n]['p95']:.2f})")
        resultados[nombre] = {"prompt_ms": prompt_ms, "cache_n": cache_n,
                              "prompt_n": prompt_n, "latencia": lat}
    finally:
        proc.terminate()
        try: proc.wait(timeout=30)
        except subprocess.TimeoutExpired: proc.kill()
        log.close(); time.sleep(3)

(AQUI / "resultado_cache_reuse.json").write_text(
    json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

if len(resultados) == 2:
    a, b = CONFIGS[0][0], CONFIGS[1][0]
    ta, tb = sum(resultados[a]["prompt_ms"]), sum(resultados[b]["prompt_ms"])
    print(f"\n{'='*66}\n  RESUMEN\n{'='*66}")
    print(f"  tiempo total de prompt en 8 turnos: {ta:.0f} ms -> {tb:.0f} ms "
          f"({(tb/ta-1)*100:+.1f}%)")
    for n in (1, 2, 4):
        la, lb = resultados[a]["latencia"][n]["media"], resultados[b]["latencia"][n]["media"]
        print(f"  latencia con {n} agente(s): {la:.2f}s -> {lb:.2f}s ({(lb/la-1)*100:+.1f}%)")
print()
