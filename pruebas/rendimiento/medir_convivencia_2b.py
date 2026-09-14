# -*- coding: utf-8 -*-
"""medir_convivencia_2b.py - Que cuesta tener E4B y E2B cargados a la vez.

POR QUE (20/08/2026)

La tabla de candidatos dejo una decision abierta: E4B (mejor calidad, entran 2)
contra E2B (el doble de caudal, entran 4). Hay una tercera opcion que la tabla
no mide: **uno de cada uno**. 3.221 + 1.710 = 4,9 GB de los 7,4 disponibles, asi
que entran juntos -- y es justo el reparto que busca el proyecto: uno que decide
y planifica, otro que ejecuta.

Lo que hay que medir no es si entran (eso es aritmetica) sino **cuanto se
estorban**. Con el 9B y el 30B se midio -7% y -0,6% (resultado_concurrencia.md),
pero ahi uno estaba en VRAM y el otro en RAM: no competian por lo mismo. Aqui los
dos pelean por la MISMA GPU y el mismo ancho de banda.

Metodo: cada modelo solo, despues los dos a la vez con la misma carga, y se
compara. Prompts distintos por pedido para que el cache de prefijo no falsee.

Uso:
    python3 pruebas/rendimiento/medir_convivencia_2b.py
"""
import json
import os
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
BIN = RAIZ / "backends" / "linux" / "bin" / "llama-server"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODELOS = [
    ("E4B", 8090, RAIZ / "modelos/candidatos/unsloth__gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf"),
    ("E2B", 8091, RAIZ / "modelos/candidatos/unsloth__gemma-4-E2B-it-GGUF/gemma-4-E2B-it-Q4_K_M.gguf"),
]
PROMPTS = [
    "Escribe una funcion Python que valide un email con expresiones regulares.",
    "Explica que es un indice en una base de datos y cuando conviene crearlo.",
    "Escribe una consulta SQL con los 5 clientes que mas compraron.",
    "Explica la diferencia entre un proceso y un hilo.",
]
MAX_TOKENS = 128


def vram():
    s = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True)
    u, f = s.stdout.strip().splitlines()[0].split(", ")
    return int(u), int(f)


def levantar(nombre, puerto, gguf):
    entorno = dict(os.environ)
    entorno["LD_LIBRARY_PATH"] = f"{BIN.parent}:{entorno.get('LD_LIBRARY_PATH', '')}"
    (AQUI / "logs").mkdir(exist_ok=True)
    log = open(AQUI / "logs" / f"conviv_{nombre}.log", "w")
    proc = subprocess.Popen(
        [str(BIN), "--model", str(gguf), "--ctx-size", "8192", "--host", "127.0.0.1",
         "--port", str(puerto), "--jinja", "--n-gpu-layers", "99", "--parallel", "2",
         "--flash-attn", "auto", "--threads", "6"],
        env=entorno, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(150):
        if proc.poll() is not None:
            raise RuntimeError(f"{nombre} murio al arrancar (codigo {proc.returncode})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/v1/models", timeout=2) as r:
                if b"data" in r.read():
                    time.sleep(3)
                    return proc
        except Exception:  # noqa: BLE001
            time.sleep(2)
    proc.kill()
    raise RuntimeError(f"{nombre} no respondio a tiempo")


def pedir(puerto, prompt, salida, idx):
    cuerpo = json.dumps({"model": "x", "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": MAX_TOKENS, "temperature": 0}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}/v1/chat/completions",
                                 data=cuerpo, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read())
        t = d.get("timings", {})
        salida[idx] = {"tok_s": t.get("predicted_per_second", 0.0),
                       "n": t.get("predicted_n", 0),
                       "ini": t0, "fin": time.time()}
    except Exception as e:  # noqa: BLE001
        salida[idx] = {"error": str(e)[:80]}


def tanda(puertos, agentes_por_puerto):
    """Dispara agentes en cada puerto a la vez y devuelve tok/s agregados por puerto."""
    hilos, salidas = [], {p: [None] * agentes_por_puerto for p in puertos}
    t0 = time.time()
    for p in puertos:
        for i in range(agentes_por_puerto):
            h = threading.Thread(target=pedir,
                                 args=(p, f"[{time.time()}-{p}-{i}] {PROMPTS[i % len(PROMPTS)]}",
                                       salidas[p], i))
            hilos.append(h)
            h.start()
    for h in hilos:
        h.join()
    pared = time.time() - t0
    res = {}
    for p in puertos:
        ok = [x for x in salidas[p] if x and "tok_s" in x]
        if not ok:
            res[p] = 0
            continue
        # El agregado de CADA modelo se mide contra SU propia ventana de tiempo,
        # no contra el reloj de la serie completa. Dividir por el reloj global
        # daba el mismo numero para los dos por construccion (los dos generan
        # 2x128 tokens), y de ahi salia un reparto de la interferencia que era
        # puro artefacto (20/08/2026).
        propio = max(x["fin"] for x in ok) - min(x["ini"] for x in ok)
        res[p] = sum(x["n"] for x in ok) / propio if propio > 0 else 0
    return res, pared


print(f"\n{'='*74}\n  Convivencia gemma-4 E4B + E2B en la misma placa\n{'='*74}")
u0, f0 = vram()
print(f"  VRAM antes de cargar: {u0} MiB usados, {f0} libres\n")

procs, vram_de = {}, {}
try:
    for nombre, puerto, gguf in MODELOS:
        antes, _ = vram()
        procs[nombre] = levantar(nombre, puerto, gguf)
        despues, libre = vram()
        vram_de[nombre] = despues - antes
        print(f"  {nombre} cargado en :{puerto} · {vram_de[nombre]} MiB · quedan {libre} libres")

    p4, p2 = MODELOS[0][1], MODELOS[1][1]
    print("\n  --- cada uno SOLO (2 agentes) ---")
    solo = {}
    for nombre, puerto, _ in MODELOS:
        r, _ = tanda([puerto], 2)
        solo[nombre] = r[puerto]
        print(f"  {nombre}: {solo[nombre]:6.1f} tok/s agregados")

    print("\n  --- los DOS a la vez (2 agentes cada uno) ---")
    r, pared = tanda([p4, p2], 2)
    junto = {"E4B": r[p4], "E2B": r[p2]}
    for nombre in ("E4B", "E2B"):
        d = junto[nombre] / solo[nombre] - 1 if solo[nombre] else 0
        print(f"  {nombre}: {junto[nombre]:6.1f} tok/s  ({d:+.0%} contra estar solo)")
    print(f"\n  TOTAL del equipo: {junto['E4B'] + junto['E2B']:.1f} tok/s")
    print(f"  VRAM con los dos: {vram()[0]} MiB usados, {vram()[1]} libres")

    (AQUI / "resultado_convivencia_2b.json").write_text(json.dumps(
        {"vram": vram_de, "solo": solo, "juntos": junto}, ensure_ascii=False, indent=2),
        encoding="utf-8")
finally:
    for nombre, p in procs.items():
        p.terminate()
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
    print("\n  servidores apagados")
