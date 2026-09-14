# -*- coding: utf-8 -*-
"""medir_juez.py - ¿Sabe el modelo elegir la mejor de varias respuestas?

POR QUE (20/08/2026)

La arquitectura que se quiere montar son bloques de 3 trabajadores + 1
controlador que elige entre las tres respuestas. TODO el diseno descansa en que
el controlador sepa elegir: si elige mal, un bloque 3+1 rinde PEOR que un agente
solo, porque tres candidatas buenas y una eleccion mala dan una respuesta mala.

Este banco mide exactamente eso, y lo mide contra la unica referencia que
importa: **el azar**. Si de tres candidatas dos son correctas, elegir al azar
acierta el 67% de las veces. Un juez que acierta 70% no sirve para nada.

METODO

  1. generar 3 candidatas por tarea (temperatura media, para que difieran)
  2. ejecutar los tests de cada una -> se sabe la verdad, sin opinar
  3. quedarse SOLO con las tareas MIXTAS (alguna pasa y alguna falla): son las
     unicas donde la eleccion cambia algo
  4. pedirle al modelo que elija, sin decirle cual pasa
  5. comparar su acierto contra el azar y contra "elegir siempre la primera"

Uso:
    python3 pruebas/rendimiento/medir_juez.py <puerto> [temp_generacion]
"""
import json
import random
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
TEMP_GEN = float(sys.argv[2]) if len(sys.argv) > 2 else 0.6
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
N = 3


def llamar(prompt, temp, tope=700):
    cuerpo = json.dumps({
        "model": "x", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": tope, "temperature": temp,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return (d["choices"][0]["message"].get("content") or "").strip()


def generar(prompt, salida, idx):
    try:
        salida[idx] = llamar(prompt, TEMP_GEN)
    except Exception:  # noqa: BLE001
        salida[idx] = ""


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


def preguntar_juez(tarea, codigos):
    opciones = "\n\n".join(
        f"### Opcion {i + 1}\n```python\n{c[:1500]}\n```" for i, c in enumerate(codigos))
    p = (f"Tarea pedida:\n{tarea}\n\n"
         f"Hay {len(codigos)} implementaciones. Elegi la que sea CORRECTA y este mejor "
         f"resuelta.\n\n{opciones}\n\n"
         f"Responde UNICAMENTE con el numero de la opcion elegida (1, 2 o 3). "
         f"Sin explicacion.")
    try:
        r = llamar(p, 0.1, tope=12)
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"[123]", r)
    return int(m.group(0)) - 1 if m else None


print(f"\n{'='*76}\n  ¿Sabe elegir? · puerto {PUERTO} · {N} candidatas por tarea"
      f" · temp de generacion {TEMP_GEN}\n{'='*76}")

mixtas, salteadas, t0 = [], 0, time.time()
for t in TAREAS:
    cand = [None] * N
    hilos = [threading.Thread(target=generar, args=(t["prompt"], cand, i)) for i in range(N)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    codigos = [extraer(c or "") for c in cand]
    verdad = [probar(c, t["tests"]) for c in codigos]
    if not (any(verdad) and not all(verdad)):
        salteadas += 1          # todas bien o todas mal: elegir no cambia nada
        continue
    elegida = preguntar_juez(t["prompt"], codigos)
    acerto = elegida is not None and verdad[elegida]
    mixtas.append({"id": t["id"], "verdad": verdad, "elegida": elegida, "acerto": acerto})
    marca = "".join("O" if v else "." for v in verdad)
    print(f"  {t['id']:22s} [{marca}] eligio {('?' if elegida is None else elegida + 1)} "
          f"{'ACIERTA' if acerto else 'falla'}")

if not mixtas:
    print("\n  No hubo tareas mixtas: no se puede medir al juez.")
    raise SystemExit

aciertos = sum(1 for m in mixtas if m["acerto"])
# El azar no es 50%: depende de cuantas candidatas correctas hubo en cada tarea.
azar = sum(sum(m["verdad"]) / len(m["verdad"]) for m in mixtas) / len(mixtas)
primera = sum(1 for m in mixtas if m["verdad"][0]) / len(mixtas)

print(f"\n  tareas mixtas (donde elegir importa): {len(mixtas)} de {len(TAREAS)}")
print(f"  ({salteadas} saltadas: todas las candidatas iguales de buenas o de malas)\n")
print(f"  el juez acierta        : {aciertos}/{len(mixtas)} = {aciertos/len(mixtas):.0%}")
print(f"  elegir al AZAR daria   : {azar:.0%}   <- la vara a superar")
print(f"  elegir siempre la 1a   : {primera:.0%}")
ventaja = aciertos / len(mixtas) - azar
print(f"\n  ventaja del juez sobre el azar: {ventaja:+.0%}")
print(f"  {'SIRVE como controlador' if ventaja > 0.10 else 'NO justifica el bloque 3+1'}")
print(f"\n  {time.time() - t0:.0f}s")

(AQUI / "resultado_juez.json").write_text(json.dumps(
    {"temp_gen": TEMP_GEN, "mixtas": len(mixtas), "aciertos": aciertos,
     "azar": azar, "primera": primera, "detalle": mixtas}, ensure_ascii=False, indent=2),
    encoding="utf-8")
