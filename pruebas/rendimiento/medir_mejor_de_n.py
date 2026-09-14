# -*- coding: utf-8 -*-
"""medir_mejor_de_n.py - Varios agentes sobre LA MISMA tarea: ¿sirve?

POR QUE (20/08/2026)

Hay cuatro formas de poner varios agentes sobre un objetivo comun y en este
proyecto solo se probaron dos, las dos peores:

  descomponer   partir la tarea y unir las partes -> medido 3 veces, peor las 3
  encadenar     uno planifica, otro ejecuta       -> medido, peor
  MEJOR-DE-N    los N resuelven lo mismo, se elige -> nunca se midio  <-- esto
  debatir       uno propone, otro critica          -> nunca se midio

Las dos que fracasaron comparten causa: le piden al modelo que PLANIFIQUE, que
es lo que peor hace. Mejor-de-N no: cada agente resuelve el problema entero de
una, que es lo unico que sabe hacer bien. Y es vergonzosamente paralela: usa
exactamente la concurrencia que sobra.

QUE MIDE

  pass@1   cuantas tareas resuelve UN intento (promedio de los N intentos)
  pass@N   cuantas tareas resuelve AL MENOS UNO de los N

La diferencia entre las dos responde la pregunta de fondo: **los errores de los
agentes, son independientes?** Si el modelo falla siempre las mismas tareas, N
agentes no arreglan nada y pass@N = pass@1. Si falla tareas distintas segun la
ejecucion, N intentos recuperan varias.

OJO CON LA TEMPERATURA: con temp 0 los N intentos serian identicos y la medicion
no tendria sentido. Se usa temp alta para que haya diversidad, y pass@1 se mide
a LA MISMA temperatura para que la comparacion sea justa.

LIMITE HONESTO: pass@N usa los tests como juez, es decir un verificador perfecto.
En uso real no se tiene. Es el TECHO de lo que mejor-de-N puede dar, no lo que
vas a obtener eligiendo a ojo.

Uso:
    python3 pruebas/rendimiento/medir_mejor_de_n.py <puerto> [N] [temp]
"""
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# pruebas/ se reorganizo en carpetas el 07/09/2026: los bancos de calidad
# viven en pruebas/calidad/. Sin esta linea el import de abajo no los
# encuentra desde otra subcarpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "calidad"))
from eval_expertos import TAREAS  # noqa: E402

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8080"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 4
TEMP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.7
# De donde sale la diversidad entre los N intentos:
#   "temp"      todos el mismo prompt, se confia en el muestreo. Medido el
#               20/08: hace falta temp 0,7 y eso le costo a gemma 33 puntos
#               (51,4 -> 18,2). La diversidad sale cara y es de mala calidad.
#   "prompt"    el MISMO pedido escrito de cuatro maneras, todos a temp 0,1.
#               Cada formulacion empuja al modelo por un camino distinto sin
#               degradarlo. Es lo que faltaba probar.
DIVERSIDAD = sys.argv[4] if len(sys.argv) > 4 else "temp"

# Cuatro envoltorios que piden LO MISMO. No agregan requisitos ni cambian lo que
# los tests verifican: solo cambian como esta redactado el pedido.
ENVOLTORIOS = [
    lambda p: p,
    lambda p: f"Tarea: {p}\n\nEscribe directamente la funcion, sin explicaciones.",
    lambda p: f"Implementa esta especificacion:\n\n{p}",
    lambda p: f"{p}\n\nAntes de escribir, considera los casos borde.",
    lambda p: f"Como programador experimentado, resolve: {p}",
    lambda p: f"{p}\n\nDevuelve codigo Python listo para usar.",
    lambda p: f"Se necesita esto:\n{p}\nEscribilo de la forma mas simple que funcione.",
    lambda p: f"{p}\n\nAsegurate de que maneje entradas vacias o invalidas.",
]


def variante(prompt, i):
    return ENVOLTORIOS[i % len(ENVOLTORIOS)](prompt) if DIVERSIDAD == "prompt" else prompt
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"


def generar(prompt, salida, idx):
    cuerpo = json.dumps({
        "model": "x", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 700, "temperature": TEMP,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read())
        salida[idx] = {"texto": (d["choices"][0]["message"].get("content") or ""),
                       "n": d.get("timings", {}).get("predicted_n", 0)}
    except Exception as e:  # noqa: BLE001
        salida[idx] = {"texto": "", "n": 0, "error": str(e)[:70]}


def extraer(texto):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return (m.group(1) if m else texto).strip()


def probar(codigo, tests):
    fuente = codigo + "\n\n" + tests + "\nprint('OK')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(fuente)
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=15, encoding="utf-8", errors="replace")
        return p.returncode == 0 and "OK" in (p.stdout or "")
    except subprocess.TimeoutExpired:
        return False
    finally:
        Path(ruta).unlink(missing_ok=True)


print(f"\n{'='*74}\n  Mejor-de-{N} · puerto {PUERTO} · temperatura {TEMP} · diversidad por {DIVERSIDAD.upper()}"
      f"\n  {len(TAREAS)} tareas · los {N} agentes resuelven LA MISMA\n{'='*74}")

filas, t_ini, tokens = [], time.time(), 0
for t in TAREAS:
    salida = [None] * N
    hilos = [threading.Thread(target=generar, args=(variante(t["prompt"], i), salida, i))
             for i in range(N)]
    t0 = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    pasan = [probar(extraer(s["texto"]), t["tests"]) for s in salida if s]
    tokens += sum(s.get("n", 0) for s in salida if s)
    filas.append({"id": t["id"], "pasan": sum(pasan), "de": len(pasan),
                  "por_variante": pasan, "segundos": time.time() - t0})
    marca = "".join("O" if p else "." for p in pasan)
    print(f"  {t['id']:22s} [{marca}]  {sum(pasan)}/{len(pasan)}")

total = len(filas)
p1 = sum(f["pasan"] for f in filas) / sum(f["de"] for f in filas) * total
pN = sum(1 for f in filas if f["pasan"] > 0)
todos = sum(1 for f in filas if f["pasan"] == f["de"])
ninguno = sum(1 for f in filas if f["pasan"] == 0)

print(f"\n  pass@1 (un intento, promedio) : {p1:.1f}/{total}")
print(f"  pass@{N} (al menos uno acierta) : {pN}/{total}")
print(f"  ganancia de {N} agentes         : {pN - p1:+.1f} tareas")
print(f"\n  tareas que aciertan los {N}     : {todos}")
print(f"  tareas que falla siempre       : {ninguno}   <- irrecuperables con mas agentes")
print(f"  tareas que dependen del intento: {total - todos - ninguno}   <- donde mejor-de-N sirve")
print(f"\n  costo: {tokens} tokens · {time.time() - t_ini:.0f}s")
if DIVERSIDAD == "prompt":
    print("\n  acierto POR FORMULACION (si una carga con todo, no hay diversidad real):")
    for i in range(N):
        ok = sum(1 for f in filas if f["por_variante"][i])
        print(f"    formulacion {i}: {ok:2d}/{len(filas)}")

(AQUI / f"resultado_mejor_de_{N}_{DIVERSIDAD}.json").write_text(
    json.dumps({"n": N, "temp": TEMP, "diversidad": DIVERSIDAD, "pass1": p1, "passN": pN, "total": total,
                "todos": todos, "ninguno": ninguno, "tokens": tokens, "filas": filas},
               ensure_ascii=False, indent=2), encoding="utf-8")
