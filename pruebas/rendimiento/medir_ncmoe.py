# -*- coding: utf-8 -*-
"""medir_ncmoe.py - Barrido de `-ncmoe N` (MoE hibrido) sobre el modelo de CPU.

QUE MIDE (17/08/2026)

Qwen3-30B-A3B es un MoE de 48 bloques con 128 expertos, de los que se usan 8
por token. Hoy se ejecuta entero en RAM a ~16,7 tok/s, limitado por el ancho de
banda de memoria (32,8 GB/s medidos), no por los nucleos.

`-ncmoe N` deja los pesos de expertos de los primeros N bloques en la CPU y
envia TODO lo demas a la GPU (atencion, normalizaciones y los expertos de los
48-N bloques restantes). La atencion se ejecuta en cada token, asi que moverla
a la GPU deberia pagar aunque los expertos sigan en RAM.

N mas pequeño = mas cosas en la GPU = mas VRAM. El barrido va de mas conservador
a mas agresivo y se corta solo cuando el servidor deja de iniciar por falta
de VRAM. `-ncmoe 48` equivale a `--cpu-moe` (todos los expertos en RAM).

REQUISITO: el backend GPU (puerto 8080) tiene que estar BAJADO. Con el modelo
de 9B dentro quedan ~950 MiB libres y no alcanza para nada de esto.

Uso:
    python3 pruebas/medir_ncmoe.py [repeticiones]

Deja pruebas/resultado_ncmoe.json con las mediciones crudas.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# .parent.parent: este script vivia en pruebas/ y el 07/09 se movio a una
# subcarpeta. Con un solo .parent la raiz quedaba en pruebas/ y buscaba los
# binarios y los modelos en pruebas/backends/ y pruebas/modelos/, que no
# existen.
RAIZ = AQUI.parent.parent
BIN = RAIZ / "backends" / "linux" / "bin"
MODELO = RAIZ / "modelos" / "Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf"
PUERTO = 8083
URL = f"http://127.0.0.1:{PUERTO}"
BLOQUES = 48  # qwen3moe.block_count del GGUF

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPES = int(sys.argv[1]) if len(sys.argv) > 1 else 2

# Igual que backends/qwen3/iniciar-linux.sh (ctx 8192, 6 hilos, KV cuantizado).
BASE = [
    str(BIN / "llama-server"),
    "--model", str(MODELO),
    "--ctx-size", "8192", "--n-predict", "16384",
    "--host", "127.0.0.1", "--port", str(PUERTO),
    "--jinja", "--threads", "6",
    "--cache-type-k", "q8_0", "--cache-type-v", "q4_0",
]

# El barrido baja N: menos bloques con expertos en RAM, mas carga en GPU.
#
# OJO con el "baseline": sin `--n-gpu-layers`, llama-server NO se ejecuta en CPU.
# El ajustador automatico envia capas a la GPU si hay lugar -- medido el
# 17/08: 6780 MiB de VRAM y 27,3 tok/s, contra los 16,7 documentados. Los
# 16,7 son lo que pasa EN PRODUCCION, donde el 9B ya ocupa la GPU y el
# ajustador no encuentra hueco. Por eso ahora hay un `cpu-puro` explicito
# con `-ngl 0`, que es el unico baseline honesto para comparar.
SWEEP = (48, 46, 44, 42, 40, 38, 36)
if len(sys.argv) > 2 and sys.argv[2].startswith("--sweep="):
    SWEEP = tuple(int(x) for x in sys.argv[2].split("=", 1)[1].split(",") if x)

CONFIGS = [
    ("cpu-puro", ["--n-gpu-layers", "0"]),
    ("autofit", []),
] + [
    (f"ncmoe-{n}", ["--n-gpu-layers", "99", "--n-cpu-moe", str(n)])
    for n in SWEEP
]

PROMPTS = [
    ("razonamiento",
     "Un tren sale de A a las 9:00 a 80 km/h. Otro sale de B a las 10:00 a "
     "120 km/h en sentido contrario. A y B estan a 500 km. A que hora se cruzan? "
     "Explica el razonamiento paso a paso."),
    ("codigo",
     "Escribe una funcion Python que reciba una lista de diccionarios y los "
     "agrupe por una clave dada, devolviendo un dict de listas. Con docstring."),
    ("prosa",
     "Explica en un parrafo por que un modelo MoE activa solo una parte de sus "
     "parametros por token."),
]
MAX_TOKENS = 200  # a ~17 tok/s cada pedido ya tarda ~12 s


def esperar_salud(proc, timeout=420):
    """El modelo pesa 21,6 GB: la primera carga desde disco puede tardar."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=3) as r:
                if json.loads(r.read()).get("status") == "ok":
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(2)
    return False


def pedir(prompt):
    cuerpo = json.dumps({
        "model": "ncmoe-test",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "seed": 1234,
    }).encode()
    req = urllib.request.Request(
        f"{URL}/v1/chat/completions", data=cuerpo,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    msg = d["choices"][0]["message"]
    texto = (msg.get("reasoning_content") or "") + (msg.get("content") or "")
    tim = d.get("timings", {})
    return (float(tim.get("predicted_per_second", 0.0)),
            hashlib.sha1(texto.encode()).hexdigest()[:12],
            int(tim.get("predicted_n", 0)),
            float(tim.get("prompt_per_second", 0.0)))


def vram_usada():
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else "?"


def correr(nombre, extra):
    print(f"\n{'='*62}\n  {nombre}   {' '.join(extra) or '(todo en RAM)'}\n{'='*62}")
    env = dict(os.environ, LD_LIBRARY_PATH=str(BIN))
    if nombre == "cpu-puro":
        # `-ngl 0` igual reserva buffers de computo en CUDA; para medir CPU de
        # verdad hay que esconder la GPU (medido en sesiones anteriores).
        env["CUDA_VISIBLE_DEVICES"] = ""
    log = open(AQUI / "logs" / f"ncmoe_{nombre}.log", "wb")
    proc = subprocess.Popen(BASE + extra, stdout=log, stderr=subprocess.STDOUT,
                            env=env, cwd=str(BIN))
    try:
        if not esperar_salud(proc):
            print(f"  NO ARRANCO -- probablemente no entra en VRAM "
                  f"(ver pruebas/logs/ncmoe_{nombre}.log)")
            return None
        vram = vram_usada()
        print(f"  VRAM en uso: {vram} MiB")
        medidas = []
        for rep in range(1, REPES + 1):
            for etq, prompt in PROMPTS:
                vel, h, n, pp = pedir(prompt)
                medidas.append({"rep": rep, "prompt": etq, "tok_s": vel,
                                "hash": h, "n": n, "prompt_tok_s": pp})
                print(f"  r{rep} {etq:14s} {vel:6.2f} tok/s   prompt {pp:7.1f} tok/s   {h}")
        return {"config": nombre, "flags": extra, "vram_mib": vram,
                "medidas": medidas}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        time.sleep(5)


(AQUI / "logs").mkdir(exist_ok=True)
crudos = []
for nombre, extra in CONFIGS:
    r = correr(nombre, extra)
    if r:
        crudos.append(r)
    elif nombre.startswith("ncmoe-"):
        # El barrido va de menos a mas VRAM: si uno no entro, los que siguen
        # piden mas todavia. No tiene sentido seguir probando.
        print("  -> se corta el barrido aca: los valores mas chicos piden mas VRAM")
        break

if not crudos:
    print("\nNinguna configuracion se inicio.")
    sys.exit(1)


def resumir(r):
    vels = [m["tok_s"] for m in r["medidas"]]
    pp = [m["prompt_tok_s"] for m in r["medidas"] if m["prompt_tok_s"]]
    por_prompt = {}
    for m in r["medidas"]:
        por_prompt.setdefault(m["prompt"], []).append(m["tok_s"])
    return {"config": r["config"], "vram_mib": r["vram_mib"],
            "media": sum(vels) / len(vels), "min": min(vels), "max": max(vels),
            "prompt_media": sum(pp) / len(pp) if pp else 0,
            "por_prompt": {k: sum(v) / len(v) for k, v in por_prompt.items()},
            "hashes": {m["prompt"]: m["hash"] for m in r["medidas"]}}


res = [resumir(r) for r in crudos]
base = res[0]

print(f"\n\n{'='*78}\n  RESUMEN   ({REPES} repeticiones x {len(PROMPTS)} prompts, temperature 0)\n{'='*78}")
print(f"  {'config':15s} {'gen tok/s':>10s} {'min':>7s} {'max':>7s} {'vs RAM':>9s} "
      f"{'prompt t/s':>11s} {'VRAM':>9s}")
for r in res:
    d = "" if r is base else f"{(r['media'] / base['media'] - 1) * 100:+.1f}%"
    print(f"  {r['config']:15s} {r['media']:10.2f} {r['min']:7.2f} {r['max']:7.2f} "
          f"{d:>9s} {r['prompt_media']:11.1f} {r['vram_mib']:>6s}MiB")

print("\n  Salida identica al baseline (control):")
for r in res[1:]:
    difs = [p for p, h in r["hashes"].items() if base["hashes"].get(p) != h]
    print(f"    {r['config']:15s} {'si' if not difs else 'NO -> ' + ', '.join(difs)}")

salida = AQUI / "resultado_ncmoe.json"
salida.write_text(json.dumps({"repeticiones": REPES, "bloques": BLOQUES,
                              "crudos": crudos, "resumen": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
