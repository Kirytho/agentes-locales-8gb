# -*- coding: utf-8 -*-
"""medir_plan_roto.py - ¿Los errores del plan se propagan al codigo?

POR QUE EXISTE (22/08/2026)

Al programar uno le pide un plan a la IA, lo LEE, lo corrige, y solo despues
deja que escriba codigo. Ese habito solo vale la pena si los errores del plan se
propagan: si el programador ignora el plan o lo arregla solo, revisarlo es
ritual.

La parte "¿lo habria detectado yo?" no es medible. La parte que decide sí:
inyectar defectos conocidos en el plan y ver si el codigo sale roto.

  SANO   la spec correcta del banco (control)
  ROTO   la misma spec con UN defecto introducido a proposito

Los defectos son de tres clases, para ver si alguna se propaga mas que otra:

  tipo         cambia la estructura de datos (lista por dict, tupla por lista)
  borde        borra un caso borde que la spec original declaraba
  orden        invierte un criterio (ascendente por descendente, primera por
               ultima)

No hace falta que ningun modelo opine: los tests del banco dicen si el codigo
quedo bien o mal.

Uso:
    python3 pruebas/medir_plan_roto.py [repeticiones]
"""
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# pruebas/ se reorganizo en carpetas el 07/09/2026: los bancos de calidad
# viven en pruebas/calidad/. Sin esta linea el import de abajo no los
# encuentra desde otra subcarpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "calidad"))
from banco_compuesto import TAREAS  # noqa: E402

URL = "http://127.0.0.1:8080/v1/chat/completions"
REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "r1"
TOPE = 2048
TEMP = 0.1

ROL = (AQUI / "roles" / "corto.txt").read_text(encoding="utf-8").strip()

# Un defecto por pieza, escrito a mano contra la spec real del banco. Cada uno
# contradice el enunciado en un punto concreto y verificable por los tests.
DEFECTOS = {
    ("inventario", "agregar_item"): ("tipo",
        "agregar_item(inv, nombre, cantidad, precio): el inventario es un dict que mapea "
        "nombre a una TUPLA (cantidad, precio). Agrega o suma cantidad a un producto "
        "existente y actualiza su precio. Devuelve el inventario."),
    ("inventario", "quitar_item"): ("borde",
        "quitar_item(inv, nombre, cantidad): resta cantidad al producto. Devuelve el "
        "inventario."),
    ("inventario", "bajo_stock"): ("orden",
        "bajo_stock(inv, umbral): devuelve la lista de nombres con cantidad menor al "
        "umbral, ordenada alfabeticamente de forma DESCENDENTE."),
    ("logs", "parsear_linea"): ("tipo",
        "parsear_linea(linea): la linea tiene formato 'NIVEL|timestamp|mensaje'. Devuelve "
        "una TUPLA (nivel, fecha, mensaje) con el nivel en mayusculas. Si la linea no "
        "tiene exactamente 3 partes separadas por '|', devuelve None."),
    ("logs", "mas_grave"): ("orden",
        "mas_grave(registros): recibe una lista de dicts con claves 'nivel', 'fecha' y "
        "'mensaje'. Devuelve el dict del registro de mayor gravedad segun "
        "DEBUG > INFO > WARN > ERROR. Si hay empate devuelve el ultimo. Con lista vacia "
        "devuelve None."),
    ("logs", "contar_por_nivel"): ("borde",
        "contar_por_nivel(registros): recibe una lista de dicts con claves 'nivel', "
        "'fecha' y 'mensaje'. Devuelve un dict {nivel: cantidad} que incluye SIEMPRE las "
        "cuatro claves ERROR, WARN, INFO y DEBUG, con 0 en las que no aparezcan."),
    ("carrito", "agregar"): ("tipo",
        "agregar(carrito, producto, cantidad, precio): el carrito es una lista de TUPLAS "
        "(producto, cantidad, precio). Si el producto ya esta, le suma la cantidad; si no, "
        "lo agrega al final. Devuelve el carrito."),
    ("carrito", "aplicar_descuento"): ("borde",
        "aplicar_descuento(monto, porcentaje): devuelve el monto con el porcentaje "
        "descontado."),
    ("carrito", "resumen"): ("tipo",
        "resumen(carrito, porcentaje): el carrito es una lista de dicts con claves "
        "'producto', 'cantidad' y 'precio'. Devuelve una TUPLA (lineas, subtotal, total) "
        "donde lineas es la cantidad de productos distintos y total es el subtotal con el "
        "descuento aplicado."),
    ("texto", "normalizar"): ("borde",
        "normalizar(texto): devuelve el texto en minusculas. Los espacios se mantienen."),
    ("texto", "palabras"): ("borde",
        "palabras(texto): recibe un texto ya normalizado. Devuelve la lista de palabras "
        "separando por espacios."),
    ("texto", "top_n"): ("orden",
        "top_n(frecs, n): recibe un dict {palabra: cantidad}. Devuelve la lista de las n "
        "palabras mas frecuentes como tuplas (palabra, cantidad), ordenadas por cantidad "
        "ASCENDENTE y, en caso de empate, alfabeticamente."),
}


def llamar(mensajes, max_tokens=TOPE):
    cuerpo = json.dumps({
        "model": "x", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": TEMP, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return (d["choices"][0]["message"].get("content") or "").strip()


def extraer(texto):
    b = re.findall(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return "\n\n".join(x.strip() for x in b) if b else texto.strip()


def correr(fuente):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(fuente + "\nprint('OK')\n")
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                           timeout=20, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:110]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        Path(ruta).unlink(missing_ok=True)


def pedir(tarea, spec):
    return extraer(llamar([
        {"role": "system", "content": ROL},
        {"role": "user", "content": f"Contexto del modulo:\n{tarea['descripcion']}\n\n"
                                    f"Escribe UNICAMENTE esta funcion:\n{spec}"}]))


print(f"\n{'=' * 94}\n  ¿Los errores del plan se propagan al codigo? · "
      f"{len(DEFECTOS)} piezas con defecto · {REPS} repeticiones\n"
      f"  gemma-4-E4B · los tests del banco deciden, ningun modelo opina\n{'=' * 94}")
print(f"  {'tarea.pieza':28s} {'clase':7s} {'SANO':>6s} {'ROTO':>6s}   detalle del fallo con plan roto")

res = []
for rep in range(1, REPS + 1):
    for tarea in TAREAS:
        specs = dict(tarea["piezas"])
        for (tid, pieza), (clase, spec_rota) in DEFECTOS.items():
            if tid != tarea["id"]:
                continue
            tests = tarea["tests_pieza"][pieza]
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_sano = ex.submit(pedir, tarea, specs[pieza])
                f_roto = ex.submit(pedir, tarea, spec_rota)
                cod_sano, cod_roto = f_sano.result(), f_roto.result()
            ok_s, err_s = correr(cod_sano + "\n" + tests)
            ok_r, err_r = correr(cod_roto + "\n" + tests)
            res.append({"rep": rep, "tarea": tid, "pieza": pieza, "clase": clase,
                        "sano_ok": ok_s, "roto_ok": ok_r,
                        "sano_err": err_s, "roto_err": err_r,
                        "codigo_roto": cod_roto})
            print(f"  {tid + '.' + pieza:28s} {clase:7s} "
                  f"{'PASA' if ok_s else 'falla':>6s} {'PASA' if ok_r else 'falla':>6s}   "
                  f"{'' if ok_r else err_r[:52]}", flush=True)

print(f"\n{'=' * 94}")
n = len(res)
sano = sum(r["sano_ok"] for r in res)
roto = sum(r["roto_ok"] for r in res)
print(f"  plan SANO  {sano:3d}/{n}  ({100*sano/n:5.1f}%)")
print(f"  plan ROTO  {roto:3d}/{n}  ({100*roto/n:5.1f}%)")

# Lo que decide: de las veces que el plan sano funcionaba, ¿cuantas rompio el defecto?
propagados = sum(1 for r in res if r["sano_ok"] and not r["roto_ok"])
absorbidos = sum(1 for r in res if r["sano_ok"] and r["roto_ok"])
base = propagados + absorbidos
if base:
    print(f"\n  De las {base} piezas que salian bien con el plan sano:")
    print(f"    el defecto SE PROPAGO al codigo : {propagados:3d}  ({100*propagados/base:5.1f}%)"
          f"   -> revisar el plan las atrapa")
    print(f"    el programador lo ABSORBIO      : {absorbidos:3d}  ({100*absorbidos/base:5.1f}%)"
          f"   -> revisar el plan no sirve ahi")

print("\n  Por clase de defecto:")
for clase in ("tipo", "borde", "orden"):
    f = [r for r in res if r["clase"] == clase and r["sano_ok"]]
    if not f:
        continue
    p = sum(1 for r in f if not r["roto_ok"])
    print(f"    {clase:7s} se propaga {p:2d}/{len(f)}  ({100*p/len(f):5.1f}%)")

salida = AQUI / f"resultado_plan_roto_{ETIQUETA}.json"
salida.write_text(json.dumps({"reps": REPS, "detalle": res}, ensure_ascii=False,
                             indent=2), encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
