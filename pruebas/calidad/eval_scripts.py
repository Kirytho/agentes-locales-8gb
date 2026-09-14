# -*- coding: utf-8 -*-
"""eval_scripts.py - ¿Escribe bien un SCRIPT OPERATIVO, no una funcion aislada?

POR QUE EXISTE (25/08/2026)

`eval_expertos.py` mide dos cosas y ninguna es esta. La mitad de codigo evalua
**funciones pequeñas y aisladas** contra tests: gemma-4-E4B obtiene 51,4/53, es decir
que esta en el techo y no queda margen para detectar nada.

Pero el 24/08 se midio que gemma **arruina la mitad de los scripts de ~30 lineas
con los que opera**: bucle de recorrido, condicion de corte, manejo de rutas.
Los bugs eran de manual --confundir la ruta con el contenido, tomar el siguiente
paso de la variable equivocada, cortar antes de tiempo-- y ningun banco los veia.

Ese hueco importa porque es la capacidad que el sistema USA de verdad: cuando
gemma resuelve una tarea, casi siempre escribe un programa y lo ejecuta.

COMO MIDE

Cada tarea prepara un directorio de trabajo real, le pide al modelo que escriba y
ejecute un script que produzca UNA respuesta, y compara con la respuesta calculada
por nosotros. Oraculo puro: no opina ningun modelo.

Uso:
    python3 pruebas/calidad/eval_scripts.py <puerto> [etiqueta] [repeticiones]
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8086"
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "modelo"
REPES = int(sys.argv[3]) if len(sys.argv) > 3 else 3
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
MAX_TOKENS = 1200

# Prompt de sistema opcional, desde un archivo. Sirve para medir el efecto del
# PROMPT DEL HARNESS sobre la calidad del script.
#
# POR QUE (25/08/2026): sin prompt de sistema gemma obtiene 12/12 en este banco,
# mientras que la misma clase de tarea por Hermes daba ~58%. La diferencia no
# puede ser el modelo. La sospecha es el prompt del harness --25.679 caracteres,
# ~6.400 tokens-- compitiendo con la tarea.
_ARCHIVO_SISTEMA = os.getenv("BANCO_SCRIPTS_SISTEMA", "")
SISTEMA = ""
if _ARCHIVO_SISTEMA and os.path.exists(_ARCHIVO_SISTEMA):
    SISTEMA = open(_ARCHIVO_SISTEMA, encoding="utf-8").read()


# ─── Tareas: cada una prepara su escenario y sabe la respuesta correcta ──────────

def _cadena(d, n=12, semilla=1):
    """Archivos enlazados: el orden NO es el alfabetico. Exige seguir punteros."""
    r = random.Random(semilla)
    ids = [f"{i:02d}" for i in range(1, n + 1)]
    orden = ids[:]; r.shuffle(orden)
    val = {i: r.randint(10, 99) for i in ids}
    sig = {orden[i]: orden[i + 1] for i in range(len(orden) - 1)}
    for i in ids:
        prox = sig.get(i)
        (d / f"nodo{i}.txt").write_text(
            f"nodo {i}\nvalor: {val[i]}\nsiguiente: " + (f"nodo{prox}" if prox else "FIN") + "\n",
            encoding="utf-8")
    for j in range(3):
        (d / f"ruido{j}.txt").write_text("valor: 999\nsiguiente: nodo99\n", encoding="utf-8")
    return (f"En {d} hay archivos nodoNN.txt. Empeza en nodo{orden[0]}.txt y segui la "
            f"cadena: cada archivo tiene 'siguiente: nodoXX'. Ignora ruido*.txt. "
            f"Escribe y ejecuta un script que imprima UNA linea: los valores del campo "
            f"'valor' de cada nodo visitado, en orden, separados por comas."), \
           ",".join(str(val[i]) for i in orden)


def _mas_profundo(d, semilla=2):
    """Arbol de directorios: exige recorrer recursivamente y comparar."""
    r = random.Random(semilla)
    rutas = ["a", "a/b", "a/b/c", "x", "x/y", "m/n/o/p", "m/n"]
    for ruta in rutas:
        (d / ruta).mkdir(parents=True, exist_ok=True)
        (d / ruta / "dato.txt").write_text(str(r.randint(1, 9)), encoding="utf-8")
    hondo = max(rutas, key=lambda p: p.count("/"))
    return (f"En {d} hay un arbol de directorios y cada uno tiene un dato.txt. "
            f"Escribe y ejecuta un script que imprima UNA linea con la ruta RELATIVA "
            f"del directorio mas profundo (el que tiene mas niveles), sin nada mas."), hondo


def _suma_filtrada(d, semilla=3):
    """Filtrar y acumular: el filtro tiene una condicion facil de invertir."""
    r = random.Random(semilla)
    filas = [(f"item{i}", r.randint(1, 200), r.choice(["ok", "roto"])) for i in range(40)]
    (d / "datos.csv").write_text(
        "nombre,cantidad,estado\n" + "\n".join(f"{a},{b},{c}" for a, b, c in filas),
        encoding="utf-8")
    total = sum(b for _, b, c in filas if c == "ok" and b > 50)
    return (f"El archivo {d}/datos.csv tiene columnas nombre,cantidad,estado. "
            f"Escribe y ejecuta un script que imprima UN numero: la suma de 'cantidad' "
            f"de las filas cuyo estado sea 'ok' Y cuya cantidad sea MAYOR a 50."), str(total)


def _ultima_linea(d, semilla=4):
    """Leer varios archivos y quedarse con uno: exige ordenar bien."""
    r = random.Random(semilla)
    for i in range(8):
        n = 3 + i
        (d / f"log{i}.txt").write_text(
            "\n".join(f"linea {j} del log {i}" for j in range(n)), encoding="utf-8")
    # el de mas lineas es log7 (10 lineas); su ultima linea:
    return (f"En {d} hay archivos log*.txt. Escribe y ejecuta un script que imprima "
            f"UNA linea: el contenido de la ULTIMA linea del archivo que tenga MAS "
            f"lineas."), "linea 9 del log 7"


TAREAS = [
    ("cadena_enlazada", _cadena),
    ("dir_mas_profundo", _mas_profundo),
    ("suma_con_dos_filtros", _suma_filtrada),
    ("archivo_con_mas_lineas", _ultima_linea),
]

HERRAMIENTA = [{"type": "function", "function": {
    "name": "ejecutar_python",
    "description": "Ejecuta un script de Python y devuelve su salida estandar.",
    "parameters": {"type": "object",
                   "properties": {"codigo": {"type": "string", "description": "el script"}},
                   "required": ["codigo"]}}}]


def _pedir(mensajes):
    cuerpo = json.dumps({"model": ETIQUETA, "messages": mensajes, "tools": HERRAMIENTA,
                         "max_tokens": MAX_TOKENS, "temperature": 0.1, "stream": False}).encode()
    req = urllib.request.Request(URL, data=cuerpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def _correr_codigo(codigo, cwd):
    """Ejecuta el script del modelo. Devuelve su salida, o el error."""
    import subprocess
    try:
        p = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                           text=True, timeout=30, cwd=cwd)
        return (p.stdout or "") + (("\n[stderr] " + p.stderr[:400]) if p.returncode else "")
    except subprocess.TimeoutExpired:
        return "[error] el script no termino en 30s"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# Que se considera un acierto. Es la distincion que explico toda la
# investigacion del 25/08/2026:
#
#   "script"  -> lo que IMPRIME el script del modelo
#   "prosa"   -> lo que el modelo DICE al final, que es de lo que depende un harness
#
# Medido con las MISMAS ejecuciones, cambiando solo esto:
#   script  6/6, 6/6, 12/12, 17/17   ~100%
#   prosa   3/6, 5/6                 ~67%
#
# Gemma escribe el script bien casi siempre y falla al RELATAR el resultado. Por
# eso el banco daba 100% y por Hermes u opencode se veia mucho peor: los dos
# dependen de que el modelo reporte, no de que calcule.
MIRAR = os.getenv("BANCO_SCRIPTS_MIRAR", "script")


def una_corrida(nombre, armar):
    """Devuelve (acerto, respuesta_obtenida, esperada)."""
    tmp = Path(tempfile.mkdtemp(prefix="evalscripts_"))
    try:
        pedido, esperada = armar(tmp)
        mensajes = ([{"role": "system", "content": SISTEMA}] if SISTEMA else [])
        mensajes.append({"role": "user", "content": pedido})
        salida = ""
        prosa = ""
        for _ in range(4):                      # como mucho 4 vueltas de herramienta
            d = _pedir(mensajes)
            msg = d.get("choices", [{}])[0].get("message", {}) or {}
            llamadas = msg.get("tool_calls") or []
            if not llamadas:
                prosa = (msg.get("content") or "").strip()
                salida = prosa or salida
                break
            mensajes.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": llamadas})
            for lc in llamadas:
                try:
                    args = json.loads(lc.get("function", {}).get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                salida = _correr_codigo(args.get("codigo", ""), str(tmp))
                mensajes.append({"role": "tool", "tool_call_id": lc.get("id", ""),
                                 "content": salida[:2000]})
        texto = prosa if MIRAR == "prosa" else salida
        limpio = " ".join(texto.split())
        return (esperada in limpio), limpio[:90], esperada
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print(f"\n{'=' * 78}\n  Scripts operativos · {ETIQUETA} · {REPES} repeticiones"
      + (f"\n  con prompt de sistema de {len(SISTEMA)} chars" if SISTEMA else "\n  sin prompt de sistema")
      + (f"\n  mirando: {'lo que DICE el modelo' if MIRAR == 'prosa' else 'lo que IMPRIME el script'}") + "\n"
      f"  el oraculo mira lo que IMPRIME el script, no lo que dice el modelo\n{'=' * 78}\n")
detalle = {}
for nombre, armar in TAREAS:
    ok = 0
    fallos = []
    for _ in range(REPES):
        t0 = time.time()
        try:
            acerto, got, esp = una_corrida(nombre, armar)
        except Exception as e:
            acerto, got, esp = False, f"[{type(e).__name__}] {e}", "?"
        ok += acerto
        if not acerto:
            fallos.append((got, esp))
    detalle[nombre] = ok
    print(f"  {ok}/{REPES}  {nombre}")
    for got, esp in fallos[:2]:
        print(f"        esperaba {esp!r}")
        print(f"        obtuvo   {got!r}")

tot = sum(detalle.values())
maxi = len(TAREAS) * REPES
print(f"\n{'=' * 78}\n  {ETIQUETA}: {tot}/{maxi} = {100 * tot / maxi:.0f}%")
salida = AQUI / f"resultado_scripts_{ETIQUETA}.json"
salida.write_text(json.dumps({"etiqueta": ETIQUETA, "repeticiones": REPES,
                              "aciertos": tot, "total": maxi, "detalle": detalle},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  Guardado: {salida.name}")
