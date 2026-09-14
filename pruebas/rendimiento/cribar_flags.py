# -*- coding: utf-8 -*-
"""cribar_flags.py - Etapa 1: descartar rapido las banderas que no mueven nada.

POR QUE (19/08/2026)

El barrido de banderas es multiplicativo: 12 tipos de especulativa x 3
cuantizaciones x 3 ejecuciones serian 108 baterias de 53 tareas. Horas para
descubrir que la mayoria no cambia nada.

Este es el cribado: por cada configuracion inicia el servidor y mide **solo
velocidad** con dos prompts fijos, ~40 s por combinacion. Despues la bateria
completa se ejecuta nada mas sobre las que sobrevivieron.

LOS DOS PROMPTS SON A PROPOSITO, y salen de lo que ya se midio el 18/08:
`--spec-type suffix` da 2,9x COPIANDO texto del pedido y PIERDE 15-33% en todo
lo demas (`resultado_spec.md`). Una sola medicion promedia esas dos cosas y no
se ve ninguna. Por eso se reportan separadas:

  copia      reescribir un texto que ya esta en el prompt (favorece a suffix,
             copyspec, recycle y a los ngram)
  generacion escribir codigo nuevo (el caso comun)

Uso:
    python3 pruebas/rendimiento/cribar_flags.py <ruta.gguf> [etiqueta]
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# .parent.parent: este script vivia en pruebas/ y el 07/09 se movio a una
# subcarpeta. Con un solo .parent la raiz quedaba en pruebas/ y buscaba los
# binarios y los modelos en pruebas/backends/ y pruebas/modelos/, que no
# existen.
RAIZ = AQUI.parent.parent
BIN = RAIZ / "backends" / "linux" / "bin" / "llama-server"
sys.path.insert(0, str(AQUI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from detectar_gguf import detectar, spec_aplicables  # noqa: E402

TEXTO = ("def procesar(items):\\n"
         "    total = 0\\n"
         "    for it in items:\\n"
         "        if it.get('activo'):\\n"
         "            total += it['valor']\\n"
         "    return total\\n") * 4

PRUEBAS = [
    ("copia", "Reescribe este codigo cambiando solo los nombres de variables a ingles. "
              "Devuelve el codigo completo:\\n" + TEXTO, 256),
    ("generacion", "Escribe una funcion Python que valide un numero de tarjeta con el "
                   "algoritmo de Luhn, con manejo de errores.", 256),
]


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def levantar(gguf, extra, puerto, log):
    entorno = dict(os.environ)
    entorno["LD_LIBRARY_PATH"] = f"{BIN.parent}:{entorno.get('LD_LIBRARY_PATH', '')}"
    cmd = [str(BIN), "--model", str(gguf), "--ctx-size", "8192", "--host", "127.0.0.1",
           "--port", str(puerto), "--jinja", "--n-gpu-layers", "99", "--parallel", "1",
           "--flash-attn", "auto", "--threads", "6"] + extra
    proc = subprocess.Popen(cmd, env=entorno, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{puerto}/v1/models"
    for _ in range(120):
        if proc.poll() is not None:
            return None      # no se inicio con estas banderas
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if b"data" in r.read():
                    time.sleep(2)
                    return proc
        except Exception:  # noqa: BLE001
            time.sleep(2)
    proc.kill()
    return None


def medir(puerto, prompt, tope):
    cuerpo = json.dumps({"model": "x", "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": tope, "temperature": 0}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}/v1/chat/completions",
                                 data=cuerpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    t = d.get("timings", {})
    return t.get("predicted_per_second", 0.0)


def probar(gguf, nombre, extra):
    puerto = puerto_libre()
    (AQUI / "logs").mkdir(exist_ok=True)
    with open(AQUI / "logs" / f"criba_{puerto}.log", "w") as log:
        proc = levantar(gguf, extra, puerto, log)
        if proc is None:
            print(f"  {nombre:20s} NO ARRANCA")
            return None
        try:
            medir(puerto, "hola", 8)                      # calentar
            r = {n: round(medir(puerto, p, t), 1) for n, p, t in PRUEBAS}
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    print(f"  {nombre:20s} copia {r['copia']:6.1f}   generacion {r['generacion']:6.1f} tok/s")
    return r


if __name__ == "__main__":
    gguf = Path(sys.argv[1])
    etiqueta = sys.argv[2] if len(sys.argv) > 2 else gguf.stem
    info = detectar(gguf)
    tipos = spec_aplicables(info)
    print(f"\n  {info['archivo']} · {info['arquitectura']} · "
          f"MoE {'si' if info['moe'] else 'no'} · MTP {'si' if info['mtp'] else 'no'}")
    print(f"  {len(tipos)} tipos de especulativa aplicables\n")

    configs = [("base", [])]
    configs += [(t, ["--spec-type", t]) for t in tipos if t != "none"]
    # Las del caché KV cambian VRAM y velocidad; se prueban aparte del spec.
    configs += [("kv f16", ["--cache-type-k", "f16", "--cache-type-v", "f16"]),
                ("kv q4_0", ["--cache-type-k", "q4_0", "--cache-type-v", "q4_0"])]
    if info["moe"]:
        configs += [("ncmoe 16", ["--n-cpu-moe", "16"]), ("ncmoe 32", ["--n-cpu-moe", "32"])]

    filas = []
    for nombre, extra in configs:
        r = probar(gguf, nombre, extra)
        if r:
            filas.append({"config": nombre, "banderas": extra, **r})

    base = next((f for f in filas if f["config"] == "base"), None)
    if base:
        print(f"\n  {'config':20s} {'copia':>16s} {'generacion':>18s}")
        for f in sorted(filas, key=lambda x: -x["generacion"]):
            dc = f["copia"] / base["copia"] - 1
            dg = f["generacion"] / base["generacion"] - 1
            print(f"  {f['config']:20s} {f['copia']:7.1f} ({dc:+5.0%})  "
                  f"{f['generacion']:7.1f} ({dg:+5.0%})")

    salida = AQUI / f"resultado_criba_{etiqueta}.json"
    salida.write_text(json.dumps({"modelo": info, "filas": filas}, ensure_ascii=False,
                                 indent=2), encoding="utf-8")
    print(f"\n  Crudos en {salida}\n")
