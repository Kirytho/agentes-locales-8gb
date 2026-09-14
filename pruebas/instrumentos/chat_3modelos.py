# -*- coding: utf-8 -*-
"""
chat_3modelos.py - Los 3 modelos, en dos modos.

DESACTUALIZADO (verificado 24/08/2026). Apunta a Bonsai-27B, Coder-1.5B y
Qwen3.5-2B: los tres se borraron tras medirlos. Tal como esta, no inicia.

Se conserva porque es el registro de una medicion: `pruebas/resultado_equipo.md`
dice "Implementado en chat_3modelos.py (/modo equipo)". Para leer esos
resultados hace falta poder ver como se produjeron.

Ademas habla DIRECTO a los servidores de modelo (8080, 8083) y omite el
intermediario, asi que no sirve para probarlo: el clasificador, el enrutado, la
memoria y las validaciones quedan fuera. Para eso esta `pruebas/chat.py`, que habla
con el intermediario en 8086 -- y que existe porque con este no se encontraba
ninguno de los cinco bugs que apareceron el 23/08.

MODO COMPARAR (por defecto): la misma pregunta va a los tres y ves las tres
respuestas lado a lado. Sirve para juzgar quien es mejor en que.

MODO EQUIPO: los tres trabajan JUNTOS y te dan UNA sola respuesta.
  1. El de GPU (el mas capaz) descompone el pedido en subtareas y reparte.
  2. Cada modelo resuelve la suya EN PARALELO.
  3. El de GPU revisa las partes y redacta la respuesta unica.

  Reparte por ROL, no en pedazos iguales, porque esta medido que los dos modelos
  de RAM comparten el mismo ancho de banda: juntos dan 24 t/s y uno solo da 27.
  Partir trabajo entre ellos lo divide pero no lo apura. Lo que si suma es que la
  GPU trabaje a la par (solo pierde 8% conviviendo) y que cada uno haga la etapa
  en la que es bueno.

Comandos:
  /modo equipo | /modo comparar
  /nuevo    borra el historial de los tres
  /solo N   habla solo con el modelo N (1, 2 o 3);  /solo 0 vuelve a los tres
  /sup      pide al de GPU que revise la ultima respuesta de los pequeños
  /salir    termina y apaga los servidores

Uso: chat_3modelos.bat   (inicia los modelos y llama a este script)
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Todo lo que pasa en el chat se guarda aquí: la consola de Windows se cierra y se
# lleva la sesión, y copiar de cmd es incómodo.
REGISTRO = Path(__file__).resolve().parent / "chat_registro.md"


def registrar(texto):
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(texto + "\n")

MODELOS = [
    {"n": 1, "nombre": "Bonsai-27B  (GPU)", "puerto": 8080, "color": "\033[96m"},
    {"n": 2, "nombre": "Coder-1.5B  (RAM)", "puerto": 8083, "color": "\033[93m"},
    {"n": 3, "nombre": "Qwen3.5-2B  (RAM)", "puerto": 8084, "color": "\033[92m"},
]
FIN = "\033[0m"
GRIS = "\033[90m"

# Montaje alternativo: los tres pequeños en VRAM (ver resultado_gpu_pequenos.md).
# Se MUTAN los mismos diccionarios en vez de reemplazar la lista, porque
# ESPECIALIDAD guarda referencias a estos objetos.
if "--gpu" in sys.argv:
    nuevos = [
        ("Qwen3-4B    (GPU)", 8090),      # coordinador: el mas capaz que entra
        ("Coder-1.5B  (GPU)", 8091),
        ("Qwen3.5-2B  (GPU)", 8092),
    ]
    for m, (nombre, puerto) in zip(MODELOS, nuevos):
        m["nombre"], m["puerto"] = nombre, puerto

for m in MODELOS:
    m["historial"] = []


def preguntar(modelo, mensajes, max_tokens=1400):
    body = json.dumps({
        "model": "m", "messages": mensajes, "max_tokens": max_tokens,
        "temperature": 0.4, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{modelo['puerto']}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read())
    except Exception as e:
        return f"[sin respuesta: {e}]", 0.0, 0.0
    txt = (d["choices"][0]["message"].get("content") or "").strip()
    t = d.get("timings", {})
    tps = t.get("predicted_n", 0) / max(t.get("predicted_ms", 1) / 1000, 0.001)
    return txt, tps, time.time() - t0


def esperar_servidores():
    print("Esperando a que los 3 modelos carguen...\n")
    for m in MODELOS:
        for intento in range(120):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{m['puerto']}/health", timeout=2) as r:
                    if r.status == 200:
                        print(f"  {m['color']}listo{FIN}   {m['nombre']}")
                        break
            except Exception:
                time.sleep(2)
        else:
            print(f"  {GRIS}NO ARRANCO{FIN}  {m['nombre']}  (puerto {m['puerto']})")


def responder_todos(pregunta, activos):
    """Lanza la pregunta a todos en paralelo; devuelve los resultados en orden."""
    res = {}

    def trabajo(m):
        m["historial"].append({"role": "user", "content": pregunta})
        txt, tps, seg = preguntar(m, m["historial"])
        m["historial"].append({"role": "assistant", "content": txt})
        res[m["n"]] = (txt, tps, seg)

    hilos = [threading.Thread(target=trabajo, args=(m,)) for m in activos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return res


def supervisar():
    """El primer modelo —el mas capaz— revisa la ultima respuesta de los otros dos."""
    revisor = MODELOS[0]
    for m in MODELOS[1:]:
        if len(m["historial"]) < 2:
            continue
        pregunta = m["historial"][-2]["content"]
        respuesta = m["historial"][-1]["content"]
        p = (f"Revisa esta respuesta como experto.\n\nPREGUNTA:\n{pregunta}\n\n"
             f"RESPUESTA A REVISAR:\n{respuesta}\n\n"
             "Empeza con CORRECTO o INCORRECTO y despues explica en 2 frases que falta "
             "o que esta mal.")
        txt, tps, seg = preguntar(revisor, [{"role": "user", "content": p}], max_tokens=200)
        veredicto = "INCORRECTO" if txt.upper().lstrip().startswith("INCORRECTO") else "CORRECTO"
        marca = "\033[91m" if veredicto == "INCORRECTO" else "\033[92m"
        print(f"\n  supervisor sobre {m['nombre']}: {marca}{veredicto}{FIN}")
        print(f"  {GRIS}{txt}{FIN}")
        print(f"  {GRIS}({seg:.1f}s){FIN}")
        registrar(f"\n### supervisor sobre {m['nombre']}: **{veredicto}** ({seg:.1f}s)\n\n{txt}")


# ─── MODO EQUIPO ─────────────────────────────────────────────────────────────
# Quien es bueno en que. El coordinador reparte usando estas etiquetas.
ESPECIALIDAD = {"codigo": MODELOS[1], "texto": MODELOS[2], "dificil": MODELOS[0]}

P_REPARTIR = """Eres el coordinador de un equipo de 3 modelos. Descompone este pedido
en 2 o 3 subtareas independientes que se puedan resolver EN PARALELO.

PEDIDO: {pedido}

Tu equipo:
  codigo  -> modelo especializado en programar (rapido, pero se equivoca en casos borde)
  texto   -> modelo generalista para explicar, redactar y razonar liviano
  dificil -> tú mismo, el mas capaz; reservate lo que exige criterio

Responde SOLO con las subtareas, una por linea, con este formato exacto:
codigo|descripcion clara y autocontenida de la subtarea
texto|descripcion clara y autocontenida de la subtarea

Sin numerar, sin encabezados, sin explicar. Maximo 3 lineas."""

P_UNIFICAR = """Eres el coordinador. Tu equipo resolvio estas partes por separado.

PEDIDO ORIGINAL: {pedido}

PARTES ENTREGADAS:
{partes}

Redacta UNA sola respuesta final para el usuario. Tres reglas, en orden:

1. REVISA EL CODIGO ANTES DE COPIARLO. Las partes vienen de modelos chicos que se
   equivocan en casos borde. Si una linea esta mal, reescribila. No la copies tal cual.
2. NO PIERDAS NADA. El pedido original tiene varias partes; todas tienen que estar en
   la respuesta final. Si una parte falta o quedo a medias, completala tú.
3. NO REPITAS SECCIONES. Cada tema aparece una sola vez.

No menciones al equipo ni digas de donde vino cada pedazo."""


def repartir_sin_repetir(subtareas):
    """Un modelo, una subtarea.

    Cada servidor atiende de uno en uno: si el coordinador le asigna dos subtareas al
    mismo modelo, se ENCOLAN en vez de ir en paralelo, y encima la GPU —el mas
    rapido— se queda sin hacer nada. Las repetidas se pasan al primer modelo libre,
    empezando por la GPU.
    """
    libres = ["dificil", "codigo", "texto"]      # la GPU primero: es la mas rapida
    usados, salida = set(), []
    for rol, desc in subtareas:
        if rol in usados:
            rol = next((r for r in libres if r not in usados), None)
            if rol is None:                      # los 3 ocupados: la subtarea sobra
                continue
        usados.add(rol)
        salida.append((rol, desc))
    return salida


def modo_equipo(pedido):
    coord = MODELOS[0]
    t_ini = time.time()
    registrar(f"\n\n## [equipo] {pedido}\n_{datetime.now():%H:%M:%S}_")

    # --- 1. El coordinador reparte ---
    print(f"\n{GRIS}  [1/3] {coord['nombre']} reparte el trabajo...{FIN}")
    plan_txt, _, seg_plan = preguntar(coord, [{"role": "user",
                                             "content": P_REPARTIR.format(pedido=pedido)}],
                                      max_tokens=300)
    subtareas = []
    for linea in plan_txt.splitlines():
        if "|" not in linea:
            continue
        rol, _, desc = linea.partition("|")
        rol, desc = rol.strip().lower().strip("`*-0123456789. "), desc.strip()
        if rol in ESPECIALIDAD and len(desc) > 10:
            subtareas.append((rol, desc))
    subtareas = repartir_sin_repetir(subtareas[:3])

    if not subtareas:
        # El coordinador no supo repartir: mejor que lo haga solo que inventar un plan.
        print(f"{GRIS}        (no se pudo repartir; lo resuelve el coordinador solo){FIN}")
        txt, tps, seg = preguntar(coord, [{"role": "user", "content": pedido}], max_tokens=800)
        print(f"\n{coord['color']}{'─'*72}\n  RESPUESTA DEL EQUIPO   "
              f"{GRIS}{seg:.1f}s{FIN}\n{coord['color']}{'─'*72}{FIN}\n{txt}")
        return

    for rol, desc in subtareas:
        print(f"{GRIS}        {ESPECIALIDAD[rol]['nombre']} <- {desc[:52]}{FIN}")

    # --- 2. Todos resuelven a la vez ---
    print(f"{GRIS}  [2/3] resolviendo en paralelo...{FIN}")
    hechas = {}

    def trabajo(i, rol, desc):
        m = ESPECIALIDAD[rol]
        txt, tps, seg = preguntar(m, [{"role": "user", "content": desc}], max_tokens=1400)
        hechas[i] = (m, desc, txt, tps, seg)

    hilos = [threading.Thread(target=trabajo, args=(i, r, d))
             for i, (r, d) in enumerate(subtareas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    t_partes = time.time() - t_ini

    for i in sorted(hechas):
        m, desc, _, tps, seg = hechas[i]
        print(f"{GRIS}        listo  {m['nombre']}  {tps:.1f} t/s · {seg:.1f}s{FIN}")

    # --- 3. El coordinador revisa y redacta una sola respuesta ---
    print(f"{GRIS}  [3/3] {coord['nombre']} revisa y redacta la respuesta unica...{FIN}")
    partes = "\n\n".join(f"--- {desc}\n{txt}" for i, (_, desc, txt, _, _) in sorted(hechas.items()))
    final, _, seg_fin = preguntar(
        coord, [{"role": "user", "content": P_UNIFICAR.format(pedido=pedido, partes=partes)}],
        max_tokens=2800)

    total = time.time() - t_ini
    print(f"\n{coord['color']}{'═'*72}")
    print(f"  RESPUESTA DEL EQUIPO   {GRIS}{total:.1f}s total{FIN}")
    print(f"{coord['color']}{'═'*72}{FIN}")
    print(final)
    print(f"\n{GRIS}  repartir {seg_plan:.1f}s · trabajo en paralelo {t_partes-seg_plan:.1f}s "
          f"· unificar {seg_fin:.1f}s{FIN}")

    registrar("\n### Reparto")
    for i in sorted(hechas):
        m, desc, txt, tps, seg = hechas[i]
        registrar(f"\n**{m['nombre']}** ({tps:.1f} t/s · {seg:.1f}s) <- {desc}\n\n{txt}")
    registrar(f"\n### Respuesta del equipo — {total:.1f}s total "
              f"(repartir {seg_plan:.1f}s · paralelo {t_partes-seg_plan:.1f}s · "
              f"unificar {seg_fin:.1f}s)\n\n{final}")


def main():
    esperar_servidores()

    # --pedido "..." : una sola ejecucion del modo equipo y salir. Para MEDIR el
    # experimento sin tipearlo a mano, que es lo unico que lo hace repetible.
    if "--pedido" in sys.argv:
        i = sys.argv.index("--pedido")
        pedido = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        if not pedido:
            print("Falta el texto despues de --pedido")
            return
        registrar(f"\n\n{'='*72}\n# Sesion {datetime.now():%Y-%m-%d %H:%M} (una corrida)\n{'='*72}")
        modo_equipo(pedido)
        return

    # --solo "..." : el coordinador resuelve el pedido entero por su cuenta, con
    # el MISMO presupuesto de tokens que usa el equipo para redactar la respuesta
    # final (2800). Sin esto la comparacion equipo-vs-directo esta amanada: la
    # medicion vieja le dio 900 tokens al camino directo y 2800 al equipo.
    if "--solo" in sys.argv:
        i = sys.argv.index("--solo")
        pedido = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        if not pedido:
            print("Falta el texto despues de --solo")
            return
        m = MODELOS[0]
        print(f"\n{GRIS}  {m['nombre']} resuelve el pedido entero (2800 tokens)...{FIN}")
        txt, tps, seg = preguntar(m, [{"role": "user", "content": pedido}], max_tokens=2800)
        print(f"\n{m['color']}{'═'*72}")
        print(f"  RESPUESTA DIRECTA   {GRIS}{seg:.1f}s · {tps:.1f} t/s · {len(txt)} chars{FIN}")
        print(f"{m['color']}{'═'*72}{FIN}\n{txt}")
        registrar(f"\n\n## [solo] {pedido}\n_{datetime.now():%H:%M:%S}_\n\n"
                  f"### {m['nombre']} — {tps:.1f} t/s · {seg:.1f}s · {len(txt)} chars\n\n{txt}")
        return

    print(f"\n{'='*72}")
    print("  modo COMPARAR : la misma pregunta a los tres, tres respuestas")
    print("  modo EQUIPO   : los tres se reparten el trabajo, UNA respuesta")
    print(f"  {GRIS}/modo equipo   /modo comparar   /nuevo  /solo N  /sup  /salir{FIN}")
    print(f"\n  Todo queda guardado en {REGISTRO.name}   {GRIS}(/abrir para verlo){FIN}")
    print("=" * 72)
    registrar(f"\n\n{'='*72}\n# Sesion {datetime.now():%Y-%m-%d %H:%M}\n{'='*72}")

    filtro, modo = 0, "comparar"
    while True:
        try:
            q = input(f"\n\033[1m[{modo}] usuario>{FIN} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q == "/salir":
            break
        if q == "/nuevo":
            for m in MODELOS:
                m["historial"] = []
            print(f"  {GRIS}historial borrado en los tres{FIN}")
            continue
        if q.startswith("/solo"):
            partes = q.split()
            filtro = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else 0
            destino = ("los tres" if filtro == 0
                       else next((m["nombre"] for m in MODELOS if m["n"] == filtro), "los tres"))
            print(f"  {GRIS}hablando con: {destino}{FIN}")
            continue
        if q == "/sup":
            supervisar()
            continue
        if q == "/abrir":
            import subprocess
            subprocess.Popen(["notepad.exe", str(REGISTRO)])
            print(f"  {GRIS}{REGISTRO}{FIN}")
            continue
        if q.startswith("/modo"):
            modo = "equipo" if "equipo" in q else "comparar"
            print(f"  {GRIS}modo {modo}{FIN}")
            continue

        if modo == "equipo":
            modo_equipo(q)
            continue

        activos = [m for m in MODELOS if filtro == 0 or m["n"] == filtro]
        t0 = time.time()
        registrar(f"\n\n## [comparar] {q}\n_{datetime.now():%H:%M:%S}_")
        res = responder_todos(q, activos)
        for m in activos:
            txt, tps, seg = res[m["n"]]
            print(f"\n{m['color']}{'─'*72}")
            print(f"[{m['n']}] {m['nombre']}   {GRIS}{tps:.1f} t/s · {seg:.1f}s{FIN}")
            print(f"{m['color']}{'─'*72}{FIN}")
            print(txt)
            registrar(f"\n### [{m['n']}] {m['nombre']} — {tps:.1f} t/s · {seg:.1f}s\n\n{txt}")
        if len(activos) > 1:
            print(f"\n{GRIS}  (los {len(activos)} en paralelo: {time.time()-t0:.1f}s en total){FIN}")

    print("\nChau.")


if __name__ == "__main__":
    main()
