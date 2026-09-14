# -*- coding: utf-8 -*-
"""
eval_reparto_codigo.py - Division real en paralelo (modo equipo, adaptado a 2 modelos)

Adaptado de chat_3modelos.py (modo_equipo) para comparar contra el pipeline
plan+ejecucion que ya tiene el intermediario. A diferencia del original
(3 modelos, jerarquia coordinador+2 especialistas pequeños), aqui son 2 modelos
de capacidad similar: uno coordina (reparte + redacta la respuesta final) y
el otro resuelve una parte en paralelo mientras el coordinador resuelve la
suya.

Uso: python eval_reparto_codigo.py [puerto_coordinador] [puerto_worker]
Default: coordinador=8081 (Qwen3.5-4B), worker=8080 (nanbeige)
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO_COORD = sys.argv[1] if len(sys.argv) > 1 else "8081"
PUERTO_WORKER = sys.argv[2] if len(sys.argv) > 2 else "8080"

PEDIDO = (
    "Necesito un modulo Python de validacion de formularios de contacto. "
    "Necesito tres funciones: 1) validar_email(s) que revise con regex si un "
    "string es un email valido. 2) validar_telefono_ar(s) que revise si un "
    "string es un telefono argentino valido (formato +54 9 11 XXXX-XXXX o "
    "variantes sin espacios). 3) validar_formulario(datos) que reciba un "
    "dict con claves email y telefono, use las dos funciones anteriores, y "
    "devuelva una lista de strings con los errores encontrados (lista vacia "
    "si todo esta bien). Escribe las tres funciones completas y funcionales "
    "con sus imports."
)

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


def preguntar(puerto, mensajes, max_tokens=1500, temp=0.2):
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


def main():
    t_ini = time.time()
    print(f"{'='*64}\n  MODO EQUIPO (2 modelos) - coordinador :{PUERTO_COORD}  "
          f"worker :{PUERTO_WORKER}\n{'='*64}")

    # --- 1. El coordinador reparte ---
    print("\n[1/3] coordinador reparte el trabajo...")
    plan_txt, seg_plan = preguntar(
        PUERTO_COORD, [{"role": "user", "content": P_REPARTIR.format(pedido=PEDIDO)}],
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
        print("  (el coordinador no repartio bien, aborta)")
        print("  plan crudo:", repr(plan_txt[:300]))
        return

    print(f"  coordinador <- {tarea_yo[:60]}")
    print(f"  worker      <- {tarea_companero[:60]}")

    # --- 2. Los dos resuelven a la vez ---
    print("\n[2/3] resolviendo en paralelo...")
    resultados = {}

    def trabajo(nombre, puerto, desc):
        txt, seg = preguntar(puerto, [{"role": "user", "content": desc}], max_tokens=1200)
        resultados[nombre] = (txt, seg)

    h1 = threading.Thread(target=trabajo, args=("coordinador", PUERTO_COORD, tarea_yo))
    h2 = threading.Thread(target=trabajo, args=("worker", PUERTO_WORKER, tarea_companero))
    h1.start(); h2.start()
    h1.join(); h2.join()
    t_partes = time.time() - t_ini

    for nombre, (txt, seg) in resultados.items():
        print(f"  listo {nombre}  ({seg:.1f}s, {len(txt)} chars)")

    # --- 3. El coordinador unifica ---
    print("\n[3/3] coordinador revisa y redacta el modulo final...")
    final, seg_fin = preguntar(
        PUERTO_COORD,
        [{"role": "user", "content": P_UNIFICAR.format(
            pedido=PEDIDO,
            parte_propia=resultados["coordinador"][0],
            parte_companero=resultados["worker"][0],
        )}],
        max_tokens=2500)

    total = time.time() - t_ini
    print(f"\n{'='*64}\n  RESULTADO FINAL   {total:.1f}s total\n{'='*64}")
    print(final)
    print(f"\n  reparto {seg_plan:.1f}s · paralelo {t_partes - seg_plan:.1f}s · "
          f"unificar {seg_fin:.1f}s")

    salida = {
        "pedido": PEDIDO,
        "plan_crudo": plan_txt,
        "tarea_coordinador": tarea_yo,
        "tarea_worker": tarea_companero,
        "parte_coordinador": resultados["coordinador"][0],
        "parte_worker": resultados["worker"][0],
        "resultado_final": final,
        "tiempos": {
            "repartir_s": round(seg_plan, 1),
            "paralelo_s": round(t_partes - seg_plan, 1),
            "unificar_s": round(seg_fin, 1),
            "total_s": round(total, 1),
        },
    }
    out = Path(__file__).resolve().parent / "resultado_reparto_equipo.json"
    out.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out.name}")


if __name__ == "__main__":
    main()
