# -*- coding: utf-8 -*-
"""
eval_reparto_multi.py - Plan+ejecucion (intermediario) vs. reparto en equipo, 3 pedidos.

Ejecuta los mismos N pedidos por los dos caminos y VERIFICA CADA RESULTADO
EJECUTANDOLO (no a ojo), igual que eval_expertos.py. Complementa la primera
ejecucion (ver resultado_reparto_pipeline_vs_equipo.md) con mas muestra.

Uso: python eval_reparto_multi.py [puerto_intermediario] [puerto_coord] [puerto_worker]
Default: intermediario=8086, coordinador=8081 (Qwen3.5-4B), worker=8080 (nanbeige)
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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO_INTERMEDIARIO = sys.argv[1] if len(sys.argv) > 1 else "8086"
PUERTO_COORD = sys.argv[2] if len(sys.argv) > 2 else "8081"
PUERTO_WORKER = sys.argv[3] if len(sys.argv) > 3 else "8080"

AQUI = Path(__file__).resolve().parent

# ─── Pedidos: independiente / acoplamiento moderado / dependiente ───────────

TAREAS = [
    {
        "id": "independiente",
        "pedido": (
            "Necesito dos funciones Python independientes de utilidad (no comparten "
            "logica entre si): 1) es_palindromo_numerico(n) que reciba un entero y "
            "devuelva True si es palindromo leyendo sus digitos (ignorando el signo "
            "si es negativo). 2) siguiente_primo(n) que devuelva el primer numero "
            "primo estrictamente mayor a n. Escribe las dos funciones completas."
        ),
        "tests": """
assert es_palindromo_numerico(121) == True
assert es_palindromo_numerico(123) == False
assert es_palindromo_numerico(-121) == True
assert es_palindromo_numerico(7) == True
assert siguiente_primo(10) == 11
assert siguiente_primo(14) == 17
assert siguiente_primo(1) == 2
""",
    },
    {
        "id": "moderado",
        "pedido": (
            "Necesito un modulo Python de inventario simple, con tres funciones que "
            "operan sobre el mismo dict de inventario (clave=nombre del producto, "
            "valor=dict con 'cantidad' y 'precio'): 1) agregar_producto(inventario, "
            "nombre, cantidad, precio) que agrega o actualiza un producto en el dict "
            "(modifica in-place, no devuelve nada). 2) calcular_valor_total(inventario) "
            "que devuelve la suma de cantidad*precio de todos los productos. "
            "3) productos_bajo_stock(inventario, umbral) que devuelve una lista de "
            "nombres de productos con cantidad menor al umbral. Escribe las tres "
            "funciones completas."
        ),
        "tests": """
inv = {}
agregar_producto(inv, "tornillos", 100, 0.5)
agregar_producto(inv, "tuercas", 5, 0.3)
assert calcular_valor_total(inv) == 100*0.5 + 5*0.3
bajo = productos_bajo_stock(inv, 10)
assert bajo == ["tuercas"]
""",
    },
    {
        "id": "dependiente",
        "pedido": (
            "Necesito un mini parser de configuracion tipo INI en Python, con dos "
            "funciones donde la segunda DEPENDE del resultado de la primera: "
            "1) parse_ini(texto) que reciba un string multilinea con formato "
            "'clave=valor' (una por linea, ignorando lineas vacias y las que "
            "empiezan con #) y devuelva un dict {clave: valor_string}. "
            "2) get_valor_tipado(config, clave, tipo) que reciba el dict que "
            "devuelve parse_ini, una clave, y un tipo (int, float, bool o str), y "
            "devuelva el valor convertido a ese tipo (para bool, acepta 'true'/'false' "
            "sin importar mayusculas/minusculas). Escribe las dos funciones completas."
        ),
        "tests": """
texto = '''
# comentario
puerto=8080
nombre=demo
activo=true
factor=0.5
'''
cfg = parse_ini(texto)
assert get_valor_tipado(cfg, "puerto", int) == 8080
assert get_valor_tipado(cfg, "nombre", str) == "demo"
assert get_valor_tipado(cfg, "activo", bool) == True
assert get_valor_tipado(cfg, "factor", float) == 0.5
""",
    },
]

# ─── Prompts del modo equipo (mismos que eval_reparto_codigo.py) ────────────

P_REPARTIR = """Eres el coordinador de un equipo de 2 modelos que programan juntos.
Descompone este pedido en EXACTAMENTE 2 subtareas independientes que se puedan
resolver EN PARALELO (una para ti, otra para tu companero).

PEDIDO: {pedido}

Responde SOLO con las 2 subtareas, una por linea, con este formato exacto:
yo|descripcion clara y autocontenida de tu subtarea
companero|descripcion clara y autocontenida de la subtarea del companero

Sin numerar, sin encabezados, sin explicar. Exactamente 2 lineas."""

P_UNIFICAR = """Eres el coordinador de un equipo de 2 modelos que programan juntos.
Tu companero y tú resolvieron estas partes por separado.

PEDIDO ORIGINAL: {pedido}

TU PARTE:
{parte_propia}

PARTE DE TU COMPANERO:
{parte_companero}

Redacta UN SOLO modulo Python final. Tres reglas, en orden:

1. REVISA EL CODIGO DE TU COMPANERO ANTES DE COPIARLO. Si una linea esta mal
   o tiene un bug, arreglala tú. No la copies tal cual si esta rota.
2. NO PIERDAS NADA. El pedido original tiene varias partes; todas tienen que
   estar en la respuesta final.
3. Responde SOLO con el codigo Python final, dentro de un bloque ```python.
   Sin explicaciones fuera del bloque."""


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
        p = subprocess.run([sys.executable, ruta], capture_output=True,
                           text=True, timeout=15, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:150]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        Path(ruta).unlink(missing_ok=True)


def preguntar_directo(puerto, mensajes, max_tokens=1500, temp=0.2):
    body = json.dumps({
        "model": "m", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": temp, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{puerto}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    txt = (d["choices"][0]["message"].get("content") or "").strip()
    return txt, time.time() - t0


def correr_pipeline(pedido):
    """Camino 1: via la API real del intermediario (plan + ejecucion)."""
    body = json.dumps({
        "messages": [{"role": "user", "content": pedido}],
        "max_tokens": 2000, "temperature": 0.2, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PUERTO_INTERMEDIARIO}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    seg = time.time() - t0
    content = d["choices"][0]["message"].get("content") or ""
    usado_pipeline = bool(d.get("_pipeline"))
    return content, seg, usado_pipeline


def correr_equipo(pedido):
    """Camino 2: reparto en equipo (coordinador + worker en paralelo)."""
    t0 = time.time()
    plan_txt, _ = preguntar_directo(
        PUERTO_COORD, [{"role": "user", "content": P_REPARTIR.format(pedido=pedido)}],
        max_tokens=200)

    tarea_yo, tarea_companero = None, None
    for linea in plan_txt.splitlines():
        if "|" not in linea:
            continue
        rol, _, desc = linea.partition("|")
        rol, desc = rol.strip().lower().strip("`*-0123456789. "), desc.strip()
        if rol == "yo" and len(desc) > 10:
            tarea_yo = desc
        elif rol == "companero" and len(desc) > 10:
            tarea_companero = desc

    if not tarea_yo or not tarea_companero:
        return None, time.time() - t0, False

    resultados = {}

    def trabajo(nombre, puerto, desc):
        txt, _ = preguntar_directo(puerto, [{"role": "user", "content": desc}], max_tokens=1200)
        resultados[nombre] = txt

    h1 = threading.Thread(target=trabajo, args=("coordinador", PUERTO_COORD, tarea_yo))
    h2 = threading.Thread(target=trabajo, args=("worker", PUERTO_WORKER, tarea_companero))
    h1.start(); h2.start()
    h1.join(); h2.join()

    final, _ = preguntar_directo(
        PUERTO_COORD,
        [{"role": "user", "content": P_UNIFICAR.format(
            pedido=pedido, parte_propia=resultados["coordinador"],
            parte_companero=resultados["worker"])}],
        max_tokens=2500)

    return final, time.time() - t0, True


def main():
    resultados_finales = []
    for t in TAREAS:
        print(f"\n{'='*64}\n  TAREA: {t['id']}\n{'='*64}")

        print("  [pipeline] corriendo...")
        try:
            texto_p, seg_p, usado_pipe = correr_pipeline(t["pedido"])
            ok_p, err_p = probar(extraer_codigo(texto_p), t["tests"])
        except Exception as e:
            texto_p, seg_p, usado_pipe, ok_p, err_p = "", 0, False, False, f"EXCEPCION: {e}"
        print(f"  [pipeline] {'PASA' if ok_p else 'FALLA'}  {seg_p:.1f}s  "
              f"pipeline_activado={usado_pipe}  {err_p}")

        print("  [equipo] corriendo...")
        try:
            texto_e, seg_e, repartio = correr_equipo(t["pedido"])
            if texto_e is None:
                ok_e, err_e = False, "coordinador no repartio bien"
            else:
                ok_e, err_e = probar(extraer_codigo(texto_e), t["tests"])
        except Exception as e:
            texto_e, seg_e, repartio, ok_e, err_e = "", 0, False, False, f"EXCEPCION: {e}"
        print(f"  [equipo]   {'PASA' if ok_e else 'FALLA'}  {seg_e:.1f}s  "
              f"reparto_ok={repartio}  {err_e}")

        resultados_finales.append({
            "id": t["id"],
            "pipeline": {"ok": ok_p, "error": err_p, "segundos": round(seg_p, 1),
                        "activado": usado_pipe, "codigo": extraer_codigo(texto_p)},
            "equipo": {"ok": ok_e, "error": err_e, "segundos": round(seg_e, 1),
                      "codigo": extraer_codigo(texto_e) if texto_e else ""},
        })

    print(f"\n{'='*64}\n  RESUMEN\n{'='*64}")
    print(f"  {'tarea':<15} {'pipeline':<20} {'equipo':<20}")
    for r in resultados_finales:
        p = r["pipeline"]; e = r["equipo"]
        print(f"  {r['id']:<15} {'PASA' if p['ok'] else 'FALLA':<6}{p['segundos']:>6.1f}s"
              f"      {'PASA' if e['ok'] else 'FALLA':<6}{e['segundos']:>6.1f}s")

    out = AQUI / "resultado_reparto_multi.json"
    out.write_text(json.dumps(resultados_finales, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out.name}")


if __name__ == "__main__":
    main()
