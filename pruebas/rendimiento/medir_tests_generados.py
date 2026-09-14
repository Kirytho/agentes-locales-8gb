# -*- coding: utf-8 -*-
"""medir_tests_generados.py - ¿Gemma escribe tests que sirvan para elegir?

POR QUE EXISTE (22/08/2026)

La arquitectura de bloques 3+1 necesita que el "1" decida cual de las tres
candidatas es buena. Ya se midio que **como juez no sirve**: elegir opinando
esta al nivel del azar (+7%, una tarea sobre 14). La salida propuesta fue que
el controlador no opine sino que EJECUTE tests, y que los agentes sobrantes
escriban esos tests.

Toda esa arquitectura depende de una pregunta que nunca se midio: **¿gemma
escribe tests usables?** Un test malo es PEOR que no tener test, porque rechaza
la candidata correcta.

Como se mide:

  1. Por cada tarea se generan 3 candidatas con temperatura 0.8 (alta a
     proposito: hacen falta fallos reales que detectar).
  2. Los tests de la bateria dicen la VERDAD sobre cada candidata (oraculo).
  3. En una llamada aparte, gemma escribe tests viendo SOLO el enunciado, sin
     ver ninguna candidata.
  4. Se ejecutan los tests de gemma contra cada candidata y se compara su
     veredicto contra el del oraculo.

Lo que importa no es "cuantos tests escribe" sino dos errores asimetricos:

  FALSA ALARMA  el test de gemma rechaza una candidata que en realidad es buena
  ESCAPE        el test de gemma acepta una candidata que en realidad es mala

Y la metrica final, comparable con el +7% del juez: eligiendo por los tests de
gemma, ¿cuantas veces el bloque entrega codigo correcto, contra simplemente
quedarse con la primera candidata?

Uso:
    python3 pruebas/medir_tests_generados.py [n_tareas]
"""
import ast
import json
import re
import subprocess
import sys
import tempfile
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

URL = "http://127.0.0.1:8080/v1/chat/completions"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 53
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "r1"
CANDIDATAS = 3
TEMP_CODIGO = 0.8      # alta a proposito: hacen falta fallos que detectar
TEMP_TESTS = 0.2       # baja: el test tiene que ser conservador
TOPE = 2048

ROL_PROGRAMADOR = (AQUI / "roles" / "corto.txt").read_text(encoding="utf-8").strip()
ROL_QA = (
    "Eres un ingeniero de QA. Escribes SOLO asserts de Python que verifiquen la "
    "funcion pedida, dentro de un bloque ```python. No implementas la funcion, no "
    "importas nada, no definis nada: asumis que la funcion ya existe con el nombre "
    "que dice el enunciado. Cubris el caso normal y los casos borde. Cada assert "
    "tiene que ser verdadero para una implementacion CORRECTA. Maximo 10 asserts."
)


def llamar(mensajes, temp, max_tokens=TOPE):
    cuerpo = json.dumps({
        "model": "x", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": temp, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    texto = (d["choices"][0]["message"].get("content") or "").strip()
    return texto, time.time() - t0, d.get("timings", {}).get("predicted_n", 0)


def extraer_codigo(texto):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return (m.group(1) if m else texto).strip()


def correr(fuente):
    """Devuelve (paso, motivo). paso=True solo si termino sin error."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(fuente + "\nprint('OK')\n")
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=15, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:90]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        Path(ruta).unlink(missing_ok=True)


tareas = TAREAS[:N]
print(f"\n{'=' * 90}\n  ¿Gemma escribe tests usables? · {len(tareas)} tareas · "
      f"{CANDIDATAS} candidatas (temp {TEMP_CODIGO})\n"
      f"  veredicto de gemma contra los tests de la bateria como verdad\n{'=' * 90}")
print(f"  {'tarea':20s} {'oraculo':>10s} {'gemma dice':>12s}   {'falsas':>6s} {'escapes':>7s}  test")

res = []
for t in tareas:
    # 1) tres candidatas
    cands = []
    for _ in range(CANDIDATAS):
        texto, seg, tok = llamar(
            [{"role": "system", "content": ROL_PROGRAMADOR},
             {"role": "user", "content": t["prompt"]}], TEMP_CODIGO)
        cands.append(extraer_codigo(texto))

    # 2) verdad segun la bateria
    verdad = [correr(c + "\n\n" + t["tests"])[0] for c in cands]

    # 3) tests escritos por gemma, sin ver ninguna candidata
    texto, seg_t, tok_t = llamar(
        [{"role": "system", "content": ROL_QA},
         {"role": "user", "content": t["prompt"]}], TEMP_TESTS)
    tests_gemma = extraer_codigo(texto)
    # Un solo parentesis mal escrito en el test rechaza TODAS las candidatas de
    # golpe. Se separa ese caso porque tiene arreglo trivial (validar que parsee
    # antes de usarlo) y hace falta saber cuanto pesa.
    try:
        ast.parse(tests_gemma)
        test_roto = False
    except SyntaxError:
        test_roto = True
    n_asserts = sum(1 for l in tests_gemma.splitlines() if l.strip().startswith("assert"))

    # 4) veredicto de gemma sobre cada candidata
    dice = []
    motivos = []
    for c in cands:
        ok, err = correr(c + "\n\n" + tests_gemma)
        dice.append(ok)
        motivos.append(err)

    falsas = sum(1 for v, g in zip(verdad, dice) if v and not g)
    escapes = sum(1 for v, g in zip(verdad, dice) if not v and g)
    # ¿el test de gemma sirve para algo? si acepta todo o rechaza todo, no separa
    inutil = len(set(dice)) == 1 and len(set(verdad)) > 1

    res.append({"id": t["id"], "verdad": verdad, "dice": dice,
                "falsas": falsas, "escapes": escapes,
                "test_roto": test_roto, "n_asserts": n_asserts,
                "tests_gemma": tests_gemma, "motivos": motivos,
                "candidatas": cands, "tok_tests": tok_t, "seg_tests": seg_t})
    marca = "TEST NO COMPILA" if test_roto else ("NO SEPARA" if inutil else "")
    print(f"  {t['id']:20s} {sum(verdad)}/{CANDIDATAS:<8d} {sum(dice)}/{CANDIDATAS:<10d}"
          f" {falsas:>6d} {escapes:>7d}  {marca}", flush=True)

# ---------------- resumen ----------------
tot = sum(len(r["verdad"]) for r in res)
buenas = sum(sum(r["verdad"]) for r in res)
malas = tot - buenas
falsas = sum(r["falsas"] for r in res)
escapes = sum(r["escapes"] for r in res)

print(f"\n{'=' * 90}")
print(f"  candidatas evaluadas: {tot}  ({buenas} buenas / {malas} malas segun la bateria)")
if buenas:
    print(f"  FALSAS ALARMAS  {falsas:3d}/{buenas}  ({100*falsas/buenas:5.1f}%)  "
          f"rechazo codigo bueno")
if malas:
    print(f"  ESCAPES         {escapes:3d}/{malas}  ({100*escapes/malas:5.1f}%)  "
          f"acepto codigo malo")
acuerdo = tot - falsas - escapes
print(f"  ACUERDO         {acuerdo:3d}/{tot}  ({100*acuerdo/tot:5.1f}%)")

rotos = [r for r in res if r["test_roto"]]
print(f"\n  Tests que ni compilan: {len(rotos)}/{len(res)} tareas"
      + (f"  ({', '.join(r['id'] for r in rotos[:8])})" if rotos else ""))
if rotos:
    perdidas = sum(sum(r["verdad"]) for r in rotos)
    print(f"    esas tareas se llevan {perdidas} de las {falsas} falsas alarmas "
          f"(el resto son asserts equivocados de verdad)")
    sanos = [r for r in res if not r["test_roto"]]
    b = sum(sum(r["verdad"]) for r in sanos)
    f_ = sum(r["falsas"] for r in sanos)
    if b:
        print(f"    descartando los rotos: falsas alarmas {f_}/{b} ({100*f_/b:5.1f}%)")
prom = sum(r["n_asserts"] for r in res) / len(res)
print(f"  Asserts por tarea: {prom:.1f} promedio")

# ---- la metrica que decide la arquitectura ----
mixtas = [r for r in res if 0 < sum(r["verdad"]) < len(r["verdad"])]
print(f"\n  Tareas donde elegir IMPORTA (candidatas mixtas): {len(mixtas)}/{len(res)}")
if mixtas:
    acierta_gemma = 0
    acierta_primera = 0
    for r in mixtas:
        # el controlador elige la primera candidata que pase los tests de gemma
        elegida = next((i for i, g in enumerate(r["dice"]) if g), 0)
        acierta_gemma += r["verdad"][elegida]
        acierta_primera += r["verdad"][0]
    n = len(mixtas)
    print(f"    eligiendo por los tests de gemma : {acierta_gemma}/{n}  ({100*acierta_gemma/n:5.1f}%)")
    print(f"    quedandose con la primera        : {acierta_primera}/{n}  ({100*acierta_primera/n:5.1f}%)")
    print(f"    ventaja de tener el verificador  : {acierta_gemma - acierta_primera:+d} tareas")

salida = AQUI / f"resultado_tests_generados_{ETIQUETA}.json"
salida.write_text(json.dumps({"tareas": len(res), "detalle": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
