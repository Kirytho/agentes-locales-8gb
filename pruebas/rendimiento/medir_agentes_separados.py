# -*- coding: utf-8 -*-
"""medir_agentes_separados.py - Un agente que planifica y otro que programa,
¿sirve o solo cuesta?

POR QUE EXISTE (22/08/2026)

La arquitectura de bloques que se esta disenando propone agentes especializados:
unos que RAZONAN (planifican) y otros que PROGRAMAN. La pregunta es si esa
division mejora el resultado sobre la misma tarea, o si solo agrega latencia.

Ya hay tres mediciones previas que dicen que NO (9B 12/12->9/12, 2B 6/12->3/12,
otro modelo 90,5%->79,3%), pero ninguna fue sobre gemma-4-E4B, que es el modelo
que va a ejecutar los agentes. Y hay una razon mecanica para sospechar: la bateria
mide a gemma en 97% programando y 72% razonando. Planificar es razonar. Meter un
planificador delante del programador hace pasar la tarea por la capacidad mas
DEBIL del modelo antes de llegar a la mas fuerte.

Tres modos sobre las MISMAS 53 tareas y con los MISMOS tests como juez
(oraculo real, no un modelo opinando):

  DIRECTO   una llamada, sin rol: "escribe el codigo"
  PIPELINE  dos llamadas con los prompts genericos que usa el intermediario en produccion
  AGENTES   dos llamadas con contratos de rol tipo OCX: un agente arquitecto que
            solo escribe prosa y un agente programador que solo escribe codigo

PIPELINE y AGENTES se diferencian solo en el contrato de rol, asi que la
comparacion entre esos dos aisla exactamente lo que aporta la "personalidad".

Uso:
    python3 pruebas/rendimiento/medir_agentes_separados.py [n_tareas]
"""
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
TOPE = 2048        # el mismo para los tres modos
TOPE_PLAN = 1024

ROL_PROGRAMADOR = (AQUI.parent / "roles" / "corto.txt").read_text(encoding="utf-8").strip()
ROL_ARQUITECTO = (AQUI.parent / "roles" / "planificador.txt").read_text(encoding="utf-8").strip()

# Lo que el intermediario YA inyecta hoy en produccion (instruccion de brevedad).
# Sin esta condicion la comparacion es contra "nada", que no es el estado real
# del sistema, y cualquier ganancia medida podria estar ya capturada.
TEXTO_BREVEDAD = ("Responde de forma directa y compacta. Si es codigo, solo el codigo "
                  "con un comentario por bloque. Sin introduccion ni resumen final.")

# Los prompts genericos que el intermediario tiene en produccion.
PLANNING_PROMPT = (
    "Eres un arquitecto de software experto. Crea un plan detallado para implementar "
    "el codigo que el usuario solicita.\n\n"
    "Responde SOLO con el plan, sin codigo. Incluye:\n"
    "1. Analisis del problema y requisitos\n"
    "2. Estructura de archivos/components necesarios\n"
    "3. Logica principal, algoritmos y flujo de datos\n"
    "4. Consideraciones tecnicas (async, errores, performance, seguridad)\n"
    "5. Pasos de implementacion ordenados\n\n"
    "Maximo 500 palabras. Se conciso pero completo."
)
EXECUTION_PROMPT = (
    "A continuacion tienes un plan de arquitectura. Genera el codigo COMPLETO y FUNCIONAL "
    "siguiendo este plan.\n\n"
    "IMPORTANTE:\n"
    "- Incluye TODOS los imports necesarios\n"
    "- Manejo de errores en cada operacion\n"
    "- Codigo listo para produccion\n"
    "- No omitas secciones ni uses '...' como placeholder"
)


def llamar(mensajes, max_tokens):
    cuerpo = json.dumps({
        "model": "x", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": 0.1, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    texto = (d["choices"][0]["message"].get("content") or "").strip()
    corte = d["choices"][0].get("finish_reason") == "length"
    tim = d.get("timings", {})
    return texto, time.time() - t0, tim.get("predicted_n", 0), corte


def extraer_codigo(texto):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return (m.group(1) if m else texto).strip()


def probar(codigo, tests):
    fuente = codigo + "\n\n" + tests + "\nprint('OK')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(fuente)
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=15, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:80]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        Path(ruta).unlink(missing_ok=True)


def directo(tarea, rol=None):
    mensajes = ([{"role": "system", "content": rol}] if rol else []) + \
        [{"role": "user", "content": tarea["prompt"]}]
    texto, seg, tok, corte = llamar(mensajes, TOPE)
    ok, err = probar(extraer_codigo(texto), tarea["tests"])
    return {"ok": ok, "err": err, "segundos": seg, "tokens": tok,
            "plan_tok": 0, "truncado": corte}


def dos_etapas(tarea, rol_plan, rol_codigo):
    plan, seg1, tok1, _ = llamar(
        [{"role": "system", "content": rol_plan},
         {"role": "user", "content": tarea["prompt"]}], TOPE_PLAN)
    texto, seg2, tok2, corte = llamar(
        [{"role": "system", "content": rol_codigo},
         {"role": "user", "content": f"{tarea['prompt']}\n\n[PLAN]\n{plan}"}], TOPE)
    codigo = extraer_codigo(texto)
    ok, err = probar(codigo, tarea["tests"])
    return {"ok": ok, "err": err, "segundos": seg1 + seg2, "tokens": tok1 + tok2,
            "plan_tok": tok1, "plan_seg": seg1, "code_seg": seg2,
            "truncado": corte, "plan_tenia_codigo": "```" in plan}


MODOS = {
    "directo": directo,
    # Control indispensable: AGENTES difiere de DIRECTO en DOS cosas (dos etapas
    # y contrato de rol). Este modo tiene el contrato pero NO el plan, asi que
    # la diferencia entre "solo_rol" y "agentes" aisla lo que aporta planificar.
    "brevedad": lambda t: directo(t, TEXTO_BREVEDAD),   # el estado ACTUAL de produccion
    "solo_rol": lambda t: directo(t, ROL_PROGRAMADOR),
}

tareas = TAREAS[:N]
print(f"\n{'=' * 86}\n  Agentes separados (planifica / programa) · {len(tareas)} tareas"
      f"\n  gemma-4-E4B · tests reales como juez · temperatura 0.1\n{'=' * 86}")
print("  " + f"{'tarea':20s}" + "".join(f"{m.upper():>18s}" for m in MODOS))

res = []
for t in tareas:
    fila = {"id": t["id"]}
    for nombre, fn in MODOS.items():
        fila[nombre] = fn(t)
    res.append(fila)
    linea = f"  {t['id']:20s}"
    for nombre in MODOS:
        r = fila[nombre]
        linea += f" {'PASA' if r['ok'] else 'falla':>5s} {r['segundos']:5.1f}s {r['tokens']:4d}t"
    print(linea, flush=True)

print(f"\n{'=' * 86}")
resumen = {}
for nombre in MODOS:
    ok = sum(1 for r in res if r[nombre]["ok"])
    seg = sum(r[nombre]["segundos"] for r in res)
    tok = sum(r[nombre]["tokens"] for r in res)
    cortadas = sum(1 for r in res if r[nombre].get("truncado"))
    con_codigo = sum(1 for r in res if r[nombre].get("plan_tenia_codigo"))
    resumen[nombre] = {"ok": ok, "de": len(res), "segundos": seg, "tokens": tok,
                       "truncadas": cortadas, "planes_con_codigo": con_codigo}
    extra = f" · TRUNCADAS {cortadas}" if cortadas else ""
    if nombre in ("pipeline", "agentes"):
        extra += f" · planes que igual metieron codigo: {con_codigo}/{len(res)}"
    print(f"  {nombre.upper():9s} {ok:2d}/{len(res)} tests · {seg:6.1f}s "
          f"({seg / len(res):5.1f}s por tarea) · {tok} tokens{extra}")

base = resumen["directo"]
for nombre in [m for m in MODOS if m != "directo"]:
    r = resumen[nombre]
    print(f"\n  {nombre.upper():9s} cuesta {r['segundos'] / base['segundos']:.2f}x el tiempo, "
          f"{r['tokens'] / base['tokens']:.2f}x los tokens, "
          f"y acierta {r['ok'] - base['ok']:+d} tareas sobre {len(res)}.")

etiqueta = sys.argv[2] if len(sys.argv) > 2 else "r1"
salida = AQUI / f"resultado_agentes_separados_{etiqueta}.json"
salida.write_text(json.dumps({"tareas": len(res), "resumen": resumen, "detalle": res},
                             ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
