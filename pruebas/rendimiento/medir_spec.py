# -*- coding: utf-8 -*-
"""medir_spec.py - Compara las estrategias de decodificacion especulativa
(--spec-type) del backend GPU, midiendo tok/s con salida identica.

POR QUE ASI (17/08/2026):

La especulacion no cambia lo que el modelo responde, solo como lo calcula:
adivina varios tokens y los verifica en una sola pasada. Con `temperature 0` la
salida es la MISMA en todas las configuraciones, asi que cualquier diferencia
de tok/s viene de la especulacion y no de que un modelo escribio mas o menos.
El script verifica esa igualdad (hash de la respuesta); si el hash cambia
entre configuraciones, la comparacion no vale y lo avisa.

Las estrategias sin modelo borrador (ngram-*, suffix, copyspec, recycle) no
ocupan VRAM extra: adivinan repitiendo texto que ya aparecio. Por eso son las
unicas que se pueden probar con 8 GB teniendo el modelo ya dentro.

`draft-mtp` si necesita VRAM extra (~0,9 GB para el contexto borrador), y el
GGUF tiene que traer los tensores nextn. Qwen3.8-9B los trae
(qwen35.nextn_predict_layers); el 30B-A3B no.

Uso:
    python3 pruebas/medir_spec.py [repeticiones]

Deja pruebas/resultado_spec.json con todas las mediciones crudas.
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
# .parent.parent: este script vivia en pruebas/ y el 07/09 se movio a
# pruebas/rendimiento/. Con un solo .parent la raiz quedaba en pruebas/ y
# buscaba los binarios en pruebas/backends/, que no existe.
RAIZ = AQUI.parent.parent
BIN = Path(os.getenv("SPEC_BIN", str(RAIZ / "backends" / "linux" / "bin")))
# El modelo se pasa por env: el Qwen3.8-9B con el que se midio el 17/08 ya no
# esta en modelos/, y ademas la pregunta ahora es sobre el modelo del MCP.
MODELO = Path(os.getenv("SPEC_MODELO",
                        str(RAIZ / "modelos" / "Ornith-1.5-9B-MTP-IQ4_XS.gguf")))
ETIQUETA = os.getenv("SPEC_ETIQUETA", MODELO.stem)
PUERTO = 8080
URL = f"http://127.0.0.1:{PUERTO}"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPES = int(sys.argv[1]) if len(sys.argv) > 1 else 3

# Mismas banderas que backends/principal/iniciar-linux.sh. El muestreo (--temp,
# --top-p, --top-k) se omite a proposito: cada pedido pide temperature 0.
def base(ctx="16384"):
    """Mismas banderas que backends/principal/iniciar-linux.sh, con ctx variable.

    El muestreo (--temp, --top-p, --top-k) se omite a proposito: cada pedido
    pide temperature 0 y seed fijo.
    """
    return [
        str(BIN / "llama-server"),
        "--model", str(MODELO),
        "--ctx-size", ctx, "--n-predict", "32768",
        "--host", "127.0.0.1", "--port", str(PUERTO),
        "--jinja", "--n-gpu-layers", "99", "--parallel", "2",
        "--flash-attn", "auto", "--cont-batching",
        "--cache-type-k", "q8_0", "--cache-type-v", "q4_0",
        "--threads", "6",
    ]


# draft-mtp no entra junto a `-ngl 99` con ctx 16384: el ajustador avisa
# "n_gpu_layers already set by user to 99, abort" y el servidor no inicia
# (pruebas/logs/spec_draft-mtp.log, ejecucion del 17/08). El contexto borrador
# necesita ~0,9 GB y con 8 GB no sobra. Por eso se prueba bajando el contexto
# en vez de bajar las capas -- bajar capas es justo lo que costaba 34-40%.
# Cada ctx reducido lleva su propio baseline para que la comparacion sea justa.
# draft-mtp necesita tensores nextn en el GGUF. Ornith los trae; K2-Horizon no
# (verificado: 0 literales `nextn`). Sin ellos el servidor no inicia, asi que
# se saltan esas configuraciones en vez de registrarlas como fallo.
TIENE_NEXTN = b"nextn" in MODELO.read_bytes()[:8_000_000]

CONFIGS = [
    ("baseline", base(), []),
    ("ngram-cache", base(), ["--spec-type", "ngram-cache"]),
    ("copyspec", base(), ["--spec-type", "copyspec"]),
    ("suffix", base(), ["--spec-type", "suffix"]),
    ("recycle", base(), ["--spec-type", "recycle"]),
] + ([] if not TIENE_NEXTN else [
    ("baseline-ctx8k", base("8192"), []),
    ("draft-mtp-ctx8k", base("8192"), ["--spec-type", "draft-mtp"]),
    ("baseline-ctx4k", base("4096"), []),
    ("draft-mtp-ctx4k", base("4096"), ["--spec-type", "draft-mtp"]),
])

# Cada configuracion carga el modelo de nuevo. Nueve cargas seguidas de un GGUF
# de 5 GB llenaron el cache de pagina y el sistema mato la ejecucion (09/09/2026),
# asi que se puede filtrar y ejecutar por series.
_SOLO = [x for x in os.getenv("SPEC_SOLO", "").split(",") if x]
if _SOLO:
    CONFIGS = [c for c in CONFIGS if c[0] in _SOLO]

# Prompts fijos. Mezcla a proposito: el codigo repite mucho texto (donde la
# especulacion por n-gramas deberia ganar) y la prosa repite poco (donde no).
PROMPTS = [
    ("codigo_clase",
     "Escribe una clase Python 'CuentaBancaria' con saldo, depositar, retirar "
     "(que valide fondos) y un historial de movimientos. Solo codigo, sin explicar."),
    ("codigo_refactor",
     "Reescribe este codigo usando dataclasses y type hints, manteniendo el "
     "comportamiento:\n\nclass P:\n    def __init__(self, n, e, c):\n        "
     "self.n = n\n        self.e = e\n        self.c = c\n    def __repr__(self):\n"
     "        return 'P(' + self.n + ')'\n\nSolo codigo."),
    ("codigo_tests",
     "Escribe tests de pytest para una funcion dividir(a, b) que lanza "
     "ZeroDivisionError. Cubre 5 casos. Solo codigo."),
    ("prosa",
     "Explica en un parrafo por que la inferencia de un modelo en CPU esta "
     "limitada por el ancho de banda de memoria y no por los nucleos."),
    # El caso donde la especulacion por n-gramas DEBERIA ganar: la respuesta
    # repite casi textual un bloque que ya esta en el prompt. Si no gana aqui,
    # no gana en ningun lado.
    ("copia_larga",
     "Devuelve este archivo completo, identico, cambiando solo el nombre de la "
     "funcion 'procesar' por 'ejecutar'. No expliques nada, solo el codigo:\n\n"
     + "\n".join(
         f"def procesar_{i}(datos, config):\n"
         f"    resultado = []\n"
         f"    for item in datos:\n"
         f"        if item.get('activo') and item['tipo'] == {i}:\n"
         f"            resultado.append(procesar(item, config))\n"
         f"    return resultado\n"
         for i in range(8))),

    # LA CARGA DE HOY (09/09/2026). Desde que `editar_archivo` pide bloques
    # SEARCH/REPLACE, el modelo NO devuelve el archivo: lee mucho y escribe
    # poco (~400 chars contra 2.650). `copia_larga` quedo como CONTROL de la
    # forma vieja, porque es justo donde `suffix` daba 2,9x el 17/08 -- si esa
    # ventaja era por copiar el archivo, con bloques tiene que desaparecer.
    ("edicion_bloques",
     "Modifica el codigo Python que ya existe. Responde SOLO con bloques de "
     "busqueda y reemplazo, sin explicaciones. Cada bloque asi:\n\n"
     "m.py\n<<<<<<< SEARCH\nlas lineas EXACTAS que hay hoy\n=======\n"
     "las que las reemplazan\n>>>>>>> REPLACE\n\n"
     "Lo que va entre SEARCH y ======= tiene que ser copia LITERAL del archivo "
     "y aparecer UNA SOLA VEZ. No reescribas el archivo entero.\n\n"
     "Archivo `m.py`:\n```python\n"
     + "\n\n".join(
         f"def procesar_{i}(datos, config):\n"
         f"    resultado = []\n"
         f"    for item in datos:\n"
         f"        if item.get('activo') and item['tipo'] == {i}:\n"
         f"            resultado.append(item['valor'] + {i})\n"
         f"    return resultado"
         for i in range(8))
     + "\n```\n\nCambio pedido: en procesar_3, sumar 100 en vez de 3."),
]

MAX_TOKENS = 320


def esperar_salud(proc, timeout=180):
    """Espera a que el servidor responda /health, o falla si el proceso murio."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=2) as r:
                if json.loads(r.read()).get("status") == "ok":
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(1.5)
    return False


def pedir(prompt):
    """Un pedido con temperature 0. Devuelve (tok/s, hash, n_tokens).

    `enable_thinking: False` replica lo que envia produccion para el backend
    GPU. Sin esto el modelo contesta en
    modo razonamiento: los tokens se van a `reasoning_content`, `content`
    queda vacio, y se termina midiendo velocidad sobre texto de razonamiento
    en vez de sobre la respuesta -- que es justo el texto repetitivo donde la
    especulacion tendria que ganar. (Paso en la primera ejecucion del 17/08.)
    """
    cuerpo = json.dumps({
        "model": "spec-test",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "seed": 1234,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        f"{URL}/v1/chat/completions", data=cuerpo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    msg = d["choices"][0]["message"]
    # Se hashea razonamiento + contenido: si el modelo contestara igual pero
    # por otro campo, el control lo tiene que ver.
    texto = (msg.get("reasoning_content") or "") + (msg.get("content") or "")
    tim = d.get("timings", {})
    return (
        float(tim.get("predicted_per_second", 0.0)),
        hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12],
        int(tim.get("predicted_n", 0)),
    )


def correr_config(nombre, cmd_base, extra):
    print(f"\n{'='*60}\n  {nombre}   {' '.join(extra) or '(sin especulacion)'}\n{'='*60}")
    env = dict(os.environ, LD_LIBRARY_PATH=str(BIN))
    log = open(AQUI / "logs" / f"spec_{nombre}.log", "wb")
    proc = subprocess.Popen(cmd_base + extra, stdout=log, stderr=subprocess.STDOUT,
                            env=env, cwd=str(BIN))
    try:
        if not esperar_salud(proc):
            print(f"  NO ARRANCO (ver pruebas/logs/spec_{nombre}.log)")
            return None
        vram = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False).stdout.strip().splitlines()[0]

        medidas = []
        for rep in range(1, REPES + 1):
            for etiqueta, prompt in PROMPTS:
                vel, h, n = pedir(prompt)
                medidas.append({"rep": rep, "prompt": etiqueta, "tok_s": vel,
                                "hash": h, "n": n})
                print(f"  r{rep} {etiqueta:16s} {vel:6.1f} tok/s   {n:3d} tok   {h}")
        ctx = cmd_base[cmd_base.index("--ctx-size") + 1]
        return {"config": nombre, "flags": extra, "ctx": ctx,
                "vram_mib": vram, "medidas": medidas}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        time.sleep(3)  # que la VRAM quede libre antes del siguiente


def resumir(res):
    """Media por configuracion y por prompt."""
    vels = [m["tok_s"] for m in res["medidas"]]
    por_prompt = {}
    for m in res["medidas"]:
        por_prompt.setdefault(m["prompt"], []).append(m["tok_s"])
    return {
        "config": res["config"],
        "ctx": res["ctx"],
        "media": sum(vels) / len(vels),
        "min": min(vels),
        "max": max(vels),
        "vram_mib": res["vram_mib"],
        "por_prompt": {k: sum(v) / len(v) for k, v in por_prompt.items()},
        "hashes": {m["prompt"]: m["hash"] for m in res["medidas"]},
    }


(AQUI / "logs").mkdir(exist_ok=True)
crudos = [r for r in (correr_config(n, b, e) for n, b, e in CONFIGS) if r]

if not crudos:
    print("\nNinguna configuracion se inicio.")
    sys.exit(1)

resumenes = [resumir(r) for r in crudos]
# Cada configuracion se compara contra el baseline de SU contexto: bajar el
# contexto cambia la velocidad por si solo, y si no se separa eso, el efecto
# del contexto se le acreditaria a la especulacion.
bases = {r["ctx"]: r for r in resumenes if r["config"].startswith("baseline")}

print(f"\n\n{'='*76}\n  RESUMEN   ({REPES} repeticiones x {len(PROMPTS)} prompts, temperature 0, sin thinking)\n{'='*76}")
print(f"  {'config':17s} {'ctx':>6s} {'media':>8s} {'min':>7s} {'max':>7s} {'vs base':>9s}  {'VRAM':>8s}")
for r in resumenes:
    b = bases.get(r["ctx"])
    delta = ""
    if b and r is not b and b["media"]:
        delta = f"{(r['media'] / b['media'] - 1) * 100:+.1f}%"
    print(f"  {r['config']:17s} {r['ctx']:>6s} {r['media']:8.1f} {r['min']:7.1f} "
          f"{r['max']:7.1f} {delta:>9s}  {r['vram_mib']:>5s}MiB")

# Control de validez: con temperature 0 la salida debe ser identica entre una
# configuracion y su baseline. Si no lo es, la comparacion no es limpia.
print("\n  Salida identica a su baseline (control):")
for r in resumenes:
    b = bases.get(r["ctx"])
    if not b or r is b:
        continue
    difs = [p for p, h in r["hashes"].items() if b["hashes"].get(p) != h]
    print(f"    {r['config']:17s} {'si' if not difs else 'NO -> ' + ', '.join(difs)}")

print("\n  Por prompt (media tok/s):")
etiquetas = [p for p, _ in PROMPTS]
print("    " + " ".join(f"{e:>16s}" for e in ["config"] + etiquetas))
for r in resumenes:
    print("    " + " ".join([f"{r['config']:>16s}"] +
                            [f"{r['por_prompt'].get(e, 0):16.1f}" for e in etiquetas]))

salida = AQUI / "resultado_spec.json"
salida.write_text(json.dumps({"repeticiones": REPES, "max_tokens": MAX_TOKENS,
                              "crudos": crudos, "resumen": resumenes},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
