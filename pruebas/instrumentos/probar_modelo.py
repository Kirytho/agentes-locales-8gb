# -*- coding: utf-8 -*-
"""probar_modelo.py - Baja un modelo de HuggingFace, lo mide y lo apaga.

POR QUE (19/08/2026)

La bateria (`eval_expertos.py`) ya sabe puntuar un backend iniciado, pero
iniciarlo era a mano: bajar el GGUF, acordarse de las banderas, buscar un
puerto libre, ejecutar, matar. Probar cinco modelos asi es una tarde perdida y
medio garantizado que alguna ejecucion quede con una bandera distinta.

Esto automatiza la cañeria y ademas mide lo que hace falta para la pregunta que
importa en este proyecto: **cuantos modelos pequeños entran juntos en 8 GB**. Por
eso reporta VRAM real ocupada y puntaje por GB, no solo el puntaje.

Las banderas son las mismas que usa produccion (`backends/principal/iniciar-linux.sh`)
salvo dos, a proposito:

  --parallel 1   para medir la VRAM del modelo, no la del pool de 4 agentes.
  --ctx-size     8192, modesto, para que la comparacion entre modelos no quede
                 dominada por el KV.

Uso:
    python3 pruebas/instrumentos/probar_modelo.py \\
        empero-ai/Qwen3.8-2B-Distill-GGUF Qwen3.8-2B-Q5_K_M.gguf 2b-q5
"""
import json
import os
import re
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
DESTINO = RAIZ / "modelos" / "candidatos"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CTX = 8192


def vram_usada_mib():
    s = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    return int(s.stdout.strip().splitlines()[0])


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def bajar(repo, archivo):
    from huggingface_hub import hf_hub_download
    # Una carpeta POR REPO. Guardar por nombre de archivo suelto es un error
    # silencioso: `unsloth/Qwen3.5-2B-GGUF` y `unsloth/Qwen3.5-2B-MTP-GGUF`
    # publican los dos un `Qwen3.5-2B-Q5_K_M.gguf`, asi que el segundo habria
    # reusado el archivo del primero y se habria medido dos veces el mismo
    # modelo creyendo que eran distintos (19/08/2026).
    carpeta = DESTINO / repo.replace("/", "__")
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / archivo
    if destino.exists():
        print(f"  ya estaba: {destino.name} ({destino.stat().st_size / 2**30:.2f} GB)")
        return destino
    print(f"  bajando {repo}/{archivo} ...")
    t0 = time.time()
    ruta = hf_hub_download(repo_id=repo, filename=archivo, local_dir=str(carpeta))
    p = Path(ruta)
    print(f"  bajado: {p.stat().st_size / 2**30:.2f} GB en {time.time() - t0:.0f}s")
    return p


def levantar(gguf, puerto, registro=None, extra=None):
    base = vram_usada_mib()
    # llama-server viene con sus .so al lado (libggml, libcublas...). Sin esto
    # muere con codigo 127 antes de escribir una linea: son bibliotecas que no
    # encuentra, no un problema del modelo. Los lanzadores de produccion lo
    # hacen en la linea 60 de backends/principal/iniciar-linux.sh.
    entorno = dict(os.environ)
    entorno["LD_LIBRARY_PATH"] = f"{BIN.parent}:{entorno.get('LD_LIBRARY_PATH', '')}"
    # El log del servidor se guarda: si algo falla, hay donde mirar.
    log = open(registro or (AQUI / "logs" / f"servidor_{puerto}.log"), "w")
    proc = subprocess.Popen(
        [str(BIN), "--model", str(gguf), "--ctx-size", str(CTX), "--host", "127.0.0.1",
         "--port", str(puerto), "--jinja", "--n-gpu-layers", "99", "--parallel", "1",
         # --fit off: la heuristica de ajuste del fork buun aborta con algunos
         # modelos aunque sobre VRAM ("failed to fit parameters to device memory
         # (hard error); retry with -fit off"). Paso con LFM2.5 y Ling-3.0 el
         # 23/08/2026, con 7,5 GB libres. Como aqui se pasa --n-gpu-layers 99
         # explicito, la heuristica no aporta nada y solo puede estorbar.
         "--fit", "off",
         "--flash-attn", "auto", "--cache-type-k", "q8_0", "--cache-type-v", "q4_0",
         "--threads", "6", *(extra or [])],
        env=entorno, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{puerto}/v1/models"
    for _ in range(180):
        if proc.poll() is not None:
            log.close()
            cola = Path(log.name).read_text(errors="replace").strip().splitlines()[-3:]
            raise RuntimeError(f"el servidor murio al arrancar (codigo {proc.returncode})\n"
                               + "\n".join(f"      {x}" for x in cola))
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if b"data" in r.read():
                    break
        except Exception:  # noqa: BLE001 - todavia no se inicio
            time.sleep(2)
    else:
        proc.kill()
        raise RuntimeError("el servidor no respondio en 6 minutos")
    time.sleep(4)
    return proc, vram_usada_mib() - base


def medir(repo, archivo, etiqueta, extra=None):
    gguf = bajar(repo, archivo)
    puerto = puerto_libre()
    proc, vram = levantar(gguf, puerto, extra=extra)
    print(f"  levantado en :{puerto} · VRAM {vram} MiB")
    try:
        subprocess.run([sys.executable, str(AQUI.parent / "calidad" / "eval_expertos.py"), str(puerto), etiqueta],
                       cwd=str(RAIZ), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        d = json.loads((AQUI / f"resultado_experto_{etiqueta}.json").read_text(encoding="utf-8"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    cod, raz = d["codigo"], d["razonamiento_puntaje"]
    fila = {
        "etiqueta": etiqueta, "repo": repo, "archivo": archivo,
        "gb_disco": round(gguf.stat().st_size / 2**30, 2),
        "vram_mib": vram,
        "codigo": cod["aciertos"], "codigo_total": cod["total"],
        "razonamiento": raz["aciertos"], "razonamiento_total": raz["total"],
        "tok_s": round(d.get("velocidad_media", 0), 1),
    }
    # Lo que decide en este proyecto: cuantos entran juntos y cuanto rinde cada GB.
    fila["caben_en_7400"] = 7400 // vram if vram > 0 else 0
    fila["puntaje_por_gb"] = round(cod["aciertos"] / (vram / 1024), 1) if vram else 0
    fila["banderas"] = list(extra or [])
    return fila


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(1)
    # Todo lo que venga despues de la etiqueta son banderas extra para el
    # servidor: asi se ejecuta la bateria sobre la configuracion que gano el
    # cribado (pruebas/rendimiento/cribar_flags.py) sin tocar el codigo.
    fila = medir(sys.argv[1], sys.argv[2], sys.argv[3], extra=sys.argv[4:] or None)
    print(f"\n  {fila['etiqueta']}: codigo {fila['codigo']}/{fila['codigo_total']} · "
          f"razonamiento {fila['razonamiento']}/{fila['razonamiento_total']} · "
          f"{fila['tok_s']} tok/s · VRAM {fila['vram_mib']} MiB · "
          f"entran {fila['caben_en_7400']} en la placa")
    salida = AQUI / "resultado_modelos.json"
    hist = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else []
    hist = [h for h in hist if h["etiqueta"] != fila["etiqueta"]] + [fila]
    salida.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  guardado en {salida}")
