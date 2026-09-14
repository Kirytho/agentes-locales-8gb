# -*- coding: utf-8 -*-
"""
medir_gpu.py - ¿Sirve tener varios modelos pequeños residentes en VRAM?

Toda la campaña previa midió UN modelo grande en GPU y los pequeños en RAM. De ahí
salió la tesis del informe: el recurso escaso es el ancho de banda de RAM. Este
arnés pregunta lo que falta: qué pasa cuando la RAM no está en el circuito.

La pregunta que decide es la contención. En RAM el caudal agregado NO crecía
(27,0 t/s con un modelo, 24,0 t/s entre dos: se repartía, no se sumaba). Si en
VRAM sí crece, el reparto de trabajo vuelve a ser viable.

Fases:
  censo       cada modelo solo en GPU -> VRAM real por proceso; después los 3 juntos
  solo-gpu    velocidad en solitario, binario CUDA
  solo-cpu    la MISMA medición con el binario CPU (línea base comparable)
  contencion  2 y 3 modelos generando a la vez en VRAM

Uso:  python medir_gpu.py <fase> [...]
      python medir_gpu.py todo

Higiene (sin esto los números no comparan nada):
  --fit off + -ngl 99 + --ctx-size explícitos: con --fit on el tercer servidor ve
    menos VRAM libre y ENCOGE su ctx en silencio; la diferencia se leería como
    contención cuando sería otra configuración.
  --parallel 1: el default es auto y parte el ctx entre slots.
  La primera generación de cada servidor se descarta: incluye autotune de kernels.
"""
import json
import os
import statistics
import subprocess
import sys
import threading
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
MODELOS_DIR = RAIZ / "modelos"
EXE_CUDA = RAIZ / "backends" / "principal" / "bin" / "cuda" / "llama-server.exe"
EXE_CPU = RAIZ / "backends" / "qwen3" / "bin" / "cpu" / "llama-server.exe"
LOGS = AQUI / "logs"
SALIDA = AQUI / "medicion_gpu.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Con ctx 4096 los tres juntos dejan solo 272 MiB libres de VRAM. Si el caudal
# se derrumba ahi, hay que poder repetir con mas margen para saber si la causa
# es competencia por computo o presion de memoria. De ahi el override.
CTX = int(os.environ.get("MEDIR_CTX", "4096"))
HILOS = 6

MODELOS = [
    {"id": "qwen3-4b", "archivo": "Qwen3-4B-Q4_K_M.gguf", "puerto": 8090},
    {"id": "coder-1.5b", "archivo": "qwen2.5-coder-1.5b-instruct-q6_k.gguf", "puerto": 8091},
    {"id": "qwen3.5-2b", "archivo": "Qwen3.5-2B-Q6_K.gguf", "puerto": 8092},
]

# Un solo prompt para todos: comparar velocidades exige que el trabajo sea el
# mismo. Pide una enumeración larga para que ninguno corte antes de max_tokens y
# la medición no quede dominada por el arranque.
PROMPT = ("Enumera y explica en una frase cada uno de los pasos que sigue una "
          "peticion HTTP desde que el navegador la envia hasta que recibe la "
          "respuesta. Se exhaustivo.")
MAX_TOKENS = 400
REPETICIONES = 3

# ignore_eos: TODOS generan exactamente MAX_TOKENS. Sin esto cada modelo corta
# donde quiere —medido: Coder 47 tokens, Qwen3.5-2B 154, Qwen3-4B 250— y la
# prueba de contencion se arruina: el Coder terminaria en 0,3 s y el 4B en
# 2,8 s, es decir que se estarian TURNANDO en vez de competir. Es lo mismo que
# hace llama-bench. El texto despues del EOS es basura y no se lee: aquí solo
# se mide caudal.
IGNORE_EOS = True


# ─── Arranque y parada de servidores ─────────────────────────────────────────

def levantar(modelo, en_gpu=True):
    """Inicia un llama-server y espera a que responda /health.

    cwd = carpeta del backend porque los .exe buscan sus DLL en el DIRECTORIO DE
    TRABAJO, no en la ruta del ejecutable.
    """
    exe = EXE_CUDA if en_gpu else EXE_CPU
    cwd = exe.parent.parent.parent
    LOGS.mkdir(exist_ok=True)
    sufijo = "gpu" if en_gpu else "cpu"
    log = (LOGS / f"srv_{modelo['id']}_{sufijo}.log").open("w", encoding="utf-8",
                                                           errors="replace")
    cmd = [
        str(exe),
        "--model", str(MODELOS_DIR / modelo["archivo"]),
        # ctx por modelo cuando hace falta: en modo equipo el coordinador tiene
        # que meter las tres partes MAS su respuesta unificada, y los
        # trabajadores solo una subtarea corta.
        "--ctx-size", str(modelo.get("ctx", CTX)),
        "--host", "127.0.0.1",
        "--port", str(modelo["puerto"]),
        "--jinja",
        "--parallel", "1",
        "--threads", str(HILOS),
    ]
    if en_gpu:
        cmd += ["-ngl", "99", "--fit", "off"]
    if modelo.get("kv_q8"):
        # KV en q8_0: la mitad de VRAM por token de contexto. Sin esto el
        # coordinador con ctx 8192 no entra junto a los dos trabajadores.
        cmd += ["--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]

    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT)
    if not esperar_salud(modelo["puerto"], p):
        p.kill()
        log.close()
        raise RuntimeError(f"{modelo['id']} no arranco en {sufijo}. "
                           f"Ver logs/srv_{modelo['id']}_{sufijo}.log")
    return p, log


def esperar_salud(puerto, proc, timeout=180):
    fin = time.time() + timeout
    while time.time() < fin:
        if proc.poll() is not None:
            return False          # el proceso murio: no tiene sentido seguir esperando
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def bajar(procesos):
    for p, log in procesos:
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        log.close()
    time.sleep(3)                  # la VRAM tarda un instante en liberarse


# ─── Lectura de VRAM ─────────────────────────────────────────────────────────

def vram_total():
    """MiB usados en la GPU, incluido el escritorio."""
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    usada, total = (int(x.strip()) for x in r.stdout.strip().split(","))
    return usada, total


def vram_por_proceso():
    """{pid: MiB} de los procesos de computo. Puede venir vacio en algunos
    drivers de Windows (WDDM); por eso el censo tambien mide el delta total."""
    r = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    salida = {}
    for linea in r.stdout.strip().splitlines():
        if not linea.strip() or "," not in linea:
            continue
        pid, mib = linea.split(",")
        try:
            salida[int(pid.strip())] = int(mib.strip())
        except ValueError:
            pass
    return salida


# ─── Generación y medida ─────────────────────────────────────────────────────

def generar(puerto, max_tokens=MAX_TOKENS):
    """Devuelve (tokens_generados, t/s segun el servidor, segundos de pared)."""
    body = json.dumps({
        "model": "m",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens, "temperature": 0.0, "stream": False,
        "ignore_eos": IGNORE_EOS,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    pared = time.time() - t0
    t = d.get("timings", {})
    n = t.get("predicted_n", 0)
    tps = n / max(t.get("predicted_ms", 1) / 1000, 0.001)
    return n, tps, pared


def medir_solo(puerto, reps=REPETICIONES):
    generar(puerto)                              # calentamiento, se descarta
    muestras = [generar(puerto) for _ in range(reps)]
    return {
        "tps_mediana": round(statistics.median(m[1] for m in muestras), 1),
        "tps_muestras": [round(m[1], 1) for m in muestras],
        "tokens": [m[0] for m in muestras],
    }


def medir_concurrente(modelos):
    """Todos generan a la vez. La barrera evita que uno arranque antes y mida
    parte del tiempo sin competencia."""
    barrera = threading.Barrier(len(modelos))
    resultados = {}

    def trabajo(m):
        barrera.wait()
        t0 = time.time()
        n, tps, pared = generar(m["puerto"])
        resultados[m["id"]] = {"tokens": n, "tps": round(tps, 1),
                               "inicio": t0, "fin": time.time()}

    for m in modelos:
        generar(m["puerto"])                     # calentamiento de cada uno
    hilos = [threading.Thread(target=trabajo, args=(m,)) for m in modelos]
    t0 = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    pared = time.time() - t0

    tokens = sum(r["tokens"] for r in resultados.values())
    return {
        "por_modelo": {k: {"tokens": v["tokens"], "tps": v["tps"]}
                       for k, v in resultados.items()},
        # Dos formas de sumar, porque no dicen lo mismo:
        "suma_tps": round(sum(r["tps"] for r in resultados.values()), 1),
        "caudal_real": round(tokens / pared, 1),
        "pared_s": round(pared, 1),
        "tokens_totales": tokens,
    }


# ─── Fases ───────────────────────────────────────────────────────────────────

def fase_censo():
    print("\n=== FASE 0: censo de VRAM ===")
    base, total = vram_total()
    print(f"Base (escritorio): {base} MiB usados de {total}")
    datos = {"base_mib": base, "total_mib": total, "individual": {}, "juntos": None}

    for m in MODELOS:
        print(f"\n  Cargando {m['id']} solo...", flush=True)
        proc = levantar(m)
        time.sleep(2)
        usada, _ = vram_total()
        porproc = vram_por_proceso().get(proc[0].pid)
        print(f"    VRAM total: {usada} MiB  |  delta: {usada - base} MiB"
              f"  |  proceso: {porproc if porproc is not None else 'n/d'} MiB")
        datos["individual"][m["id"]] = {"vram_total_mib": usada,
                                        "delta_mib": usada - base,
                                        "proceso_mib": porproc}
        bajar([proc])

    print("\n  Cargando los TRES juntos...", flush=True)
    procs = []
    try:
        for m in MODELOS:
            procs.append(levantar(m))
            print(f"    {m['id']} arriba", flush=True)
        time.sleep(2)
        usada, _ = vram_total()
        porproc = vram_por_proceso()
        print(f"    VRAM total: {usada} MiB de {total}  |  libre: {total - usada} MiB")
        datos["juntos"] = {"vram_total_mib": usada, "libre_mib": total - usada,
                           "por_proceso": {m["id"]: porproc.get(p[0].pid)
                                           for m, p in zip(MODELOS, procs)}}
    finally:
        bajar(procs)
    return datos


def fase_solo(en_gpu):
    donde = "VRAM" if en_gpu else "RAM"
    print(f"\n=== FASE 1: velocidad en solitario ({donde}) ===")
    datos = {}
    for m in MODELOS:
        print(f"  {m['id']}...", end=" ", flush=True)
        proc = levantar(m, en_gpu=en_gpu)
        try:
            datos[m["id"]] = medir_solo(m["puerto"])
            print(f"{datos[m['id']]['tps_mediana']} t/s", flush=True)
        finally:
            bajar([proc])
    return datos


def fase_contencion():
    print("\n=== FASE 2: contencion en VRAM ===")
    procs = []
    datos = {}
    try:
        for m in MODELOS:
            procs.append(levantar(m))
        usada, total = vram_total()
        datos["vram"] = {"usada_mib": usada, "libre_mib": total - usada, "ctx": CTX}
        print(f"  Los tres arriba. VRAM {usada}/{total} MiB "
              f"(libre {total - usada}). Midiendo...", flush=True)

        # Solitario CON los otros dos residentes pero ociosos: aisla el costo de
        # la residencia del costo de la competencia.
        datos["uno_solo"] = {}
        for m in MODELOS:
            datos["uno_solo"][m["id"]] = medir_solo(m["puerto"], reps=2)
            print(f"    {m['id']} solo (los otros ociosos): "
                  f"{datos['uno_solo'][m['id']]['tps_mediana']} t/s", flush=True)

        datos["dos_a_la_vez"] = medir_concurrente(MODELOS[1:])   # el par de RAM
        print(f"    dos a la vez: caudal real {datos['dos_a_la_vez']['caudal_real']} t/s",
              flush=True)

        datos["tres_a_la_vez"] = medir_concurrente(MODELOS)
        print(f"    tres a la vez: caudal real {datos['tres_a_la_vez']['caudal_real']} t/s",
              flush=True)
    finally:
        bajar(procs)
    return datos


def fase_bateria():
    """Las 25 tareas de eval_expertos.py contra los tres, en VRAM.

    Los evaluadores se ejecutan de uno en uno: aquí se mide calidad, no caudal, y con los
    tres generando a la vez el resultado seria el mismo pero mas lento.
    """
    print("\n=== FASE 3: bateria de 25 tareas en VRAM ===")
    procs = []
    try:
        for m in MODELOS:
            procs.append(levantar(m))
        usada, total = vram_total()
        print(f"  Los tres arriba. VRAM {usada}/{total} MiB. Evaluando de uno en uno...\n")
        for m in MODELOS:
            etiqueta = f"{m['id'].replace('.', '_')}_gpu"
            print(f"  --- {etiqueta} ---", flush=True)
            subprocess.run([sys.executable, str(AQUI.parent / "calidad" / "eval_expertos.py"),
                            str(m["puerto"]), etiqueta], cwd=str(AQUI))
    finally:
        bajar(procs)


def fase_bonsai():
    """La linea base que falta en todo el proyecto: el modelo grande de GPU
    nunca fue puntuado en el banco de 25 tareas. No coexiste con los pequeños."""
    print("\n=== FASE 3b: Bonsai-27B solo en GPU, mismas 25 tareas ===")
    bonsai = {"id": "bonsai-27b", "archivo": "Bonsai-27B-Q1_0.gguf", "puerto": 8093}
    proc = levantar(bonsai)
    try:
        usada, total = vram_total()
        print(f"  Arriba. VRAM {usada}/{total} MiB.\n", flush=True)
        subprocess.run([sys.executable, str(AQUI.parent / "calidad" / "eval_expertos.py"),
                        str(bonsai["puerto"]), "bonsai27b_gpu"], cwd=str(AQUI))
    finally:
        bajar([proc])


PEDIDO_EQUIPO = ("Escribe una funcion Python que lea un CSV con columnas fecha y monto "
                 "y agrupe los montos por mes. Explica por que conviene un diccionario "
                 "y no una lista para acumular. Y dame 4 casos de prueba.")


def fase_equipo():
    """Modo equipo con los tres trabajadores en VRAM, y la comparacion justa.

    El coordinador necesita mucho mas contexto que los trabajadores: tiene que
    meter las tres partes (1400 tokens cada una) mas su respuesta unificada
    (2800). Los trabajadores solo reciben una subtarea corta.
    """
    modelos = [
        {**MODELOS[0], "ctx": 8192, "kv_q8": True},   # coordinador
        {**MODELOS[1], "ctx": 2048},
        {**MODELOS[2], "ctx": 2048},
    ]
    print("\n=== FASE 4: modo equipo con los tres en VRAM ===")
    procs = []
    try:
        for m in modelos:
            procs.append(levantar(m))
        usada, total = vram_total()
        print(f"  Los tres arriba. VRAM {usada}/{total} MiB (libre {total - usada}).\n",
              flush=True)
        chat = str(AQUI.parent / "instrumentos" / "chat_3modelos.py")
        print("  --- EQUIPO ---", flush=True)
        subprocess.run([sys.executable, chat, "--gpu", "--pedido", PEDIDO_EQUIPO],
                       cwd=str(AQUI))
        print("\n  --- DIRECTO, mismo presupuesto de tokens ---", flush=True)
        subprocess.run([sys.executable, chat, "--gpu", "--solo", PEDIDO_EQUIPO],
                       cwd=str(AQUI))
    finally:
        bajar(procs)


def guardar(clave, valor):
    d = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else {}
    d[clave] = valor
    d["_config"] = {"ctx": CTX, "threads": HILOS, "max_tokens": MAX_TOKENS,
                    "repeticiones": REPETICIONES, "prompt": PROMPT}
    SALIDA.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> guardado en {SALIDA.name}")


def main():
    fase = sys.argv[1] if len(sys.argv) > 1 else "todo"
    for f in (["censo", "solo-gpu", "solo-cpu", "contencion"] if fase == "todo" else [fase]):
        if f == "censo":
            guardar("censo", fase_censo())
        elif f == "solo-gpu":
            guardar("solo_gpu", fase_solo(en_gpu=True))
        elif f == "solo-cpu":
            guardar("solo_cpu", fase_solo(en_gpu=False))
        elif f == "contencion":
            clave = "contencion" if CTX == 4096 else f"contencion_ctx{CTX}"
            guardar(clave, fase_contencion())
        elif f == "bateria":
            fase_bateria()          # eval_expertos.py escribe sus propios .json
        elif f == "bonsai":
            fase_bonsai()
        elif f == "equipo":
            fase_equipo()
        else:
            print(f"Fase desconocida: {f}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
