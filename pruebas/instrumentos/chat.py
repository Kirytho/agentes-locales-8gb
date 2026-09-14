# -*- coding: utf-8 -*-
"""chat.py - Chat de terminal contra el INTERMEDIARIO.

POR QUE EXISTE (22/08/2026)

`chat_3modelos.py` habla directo a los servidores de modelo (8080, 8083) y
omite el intermediario entero. Sirve para comparar modelos, no para probar el sistema:
el clasificador, el enrutado, la memoria y las validaciones quedan fuera.

Este habla con el intermediario (127.0.0.1:8086), asi que un pedido escrito a mano
recorre la cadena completa. Es la unica forma de probar el reparto interno como lo
viviria un usuario, en vez de llamando funciones sueltas.

Muestra ademas lo que el intermediario devuelve en los campos extra, que es lo que
interesa medir: que backend atendio, si se repartio en piezas, cuanto tardo.

Comandos:
  /nuevo    empieza una sesion limpia (borra el historial local)
  /sesion   muestra el id de sesion y cuantos mensajes lleva
  /sombra   muestra el resumen de logs/reparto_sombra.jsonl
  /salir

DOS MODOS

  INTERACTIVO   en una terminal de verdad:
      python3 pruebas/instrumentos/chat.py

  DE UN TIRO    cuando no hay terminal interactiva (por ejemplo con el prefijo
                `!` de Claude Code, donde input() recibe EOF y el chat se
                cerraria solo). El historial se guarda en disco, asi que los
                pedidos de seguimiento funcionan igual:
      python3 pruebas/instrumentos/chat.py "escribe un modulo de X"
      python3 pruebas/instrumentos/chat.py /sombra
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Un argumento que no sea un numero de puerto es un mensaje de un tiro.
_args = sys.argv[1:]
PUERTO = "8086"
if _args and _args[0].isdigit():
    PUERTO = _args.pop(0)
UNICO = " ".join(_args).strip()
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
SOMBRA = Path(__file__).resolve().parent.parent / "logs" / "reparto_sombra.jsonl"
REGISTRO = Path(__file__).resolve().parent / "chat_registro.md"
# El modo de un tiro pierde el historial entre invocaciones, asi que se guarda.
ESTADO = Path(__file__).resolve().parent / ".chat_estado.json"

AZUL, VERDE, GRIS, AMAR, ROJO, FIN = ("\033[96m", "\033[92m", "\033[90m",
                                      "\033[93m", "\033[91m", "\033[0m")


def registrar(texto):
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(texto + "\n")


def preguntar(historial):
    cuerpo = json.dumps({"model": "auto", "messages": historial,
                         "stream": False}).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return d, time.time() - t0


def resumen_sombra():
    if not SOMBRA.exists():
        return "  (todavia no hay nada en logs/reparto_sombra.jsonl)"
    filas = [json.loads(l) for l in SOMBRA.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not filas:
        return "  (archivo vacio)"
    out = [f"  {len(filas)} pedidos observados"]
    for d in ("repartiria", "pocas_piezas", "plan_ilegible"):
        n = sum(1 for f in filas if f.get("decision") == d)
        if n:
            out.append(f"    {d:14s} {n:3d}  ({100*n/len(filas):4.0f}%)")
    seg = sum(f.get("seg_plan", 0) for f in filas)
    perdidos = sum(f.get("seg_plan", 0) for f in filas if f.get("decision") != "repartiria")
    out.append(f"  planificacion: {seg:.0f}s en total, {perdidos:.0f}s gastados en "
               f"pedidos que NO se habrian repartido")
    pz = [f["piezas"] for f in filas if f.get("piezas")]
    if pz:
        out.append(f"  piezas: min {min(pz)}, max {max(pz)}, promedio {sum(pz)/len(pz):.1f}")
        cruzan = sum(1 for p in pz if p >= 9)
        out.append(f"  cruzan el umbral de kernel (9+ piezas): {cruzan}/{len(pz)}")
    dud = sum(len(f.get("dudosas", [])) for f in filas)
    tot = sum(f.get("piezas", 0) for f in filas)
    if tot:
        out.append(f"  estructuras declaradas: {dud} sobre {tot} piezas ({100*dud/tot:.0f}%)")
    return "\n".join(out)


def cargar_estado():
    if ESTADO.exists():
        try:
            d = json.loads(ESTADO.read_text(encoding="utf-8"))
            return d.get("sesion") or str(uuid.uuid4())[:8], d.get("historial", [])
        except Exception:
            pass
    return str(uuid.uuid4())[:8], []


def guardar_estado(sesion, historial):
    try:
        ESTADO.write_text(json.dumps({"sesion": sesion, "historial": historial},
                                     ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def responder(historial, q):
    """Envia un mensaje y muestra la respuesta con las marcas del sistema."""
    historial.append({"role": "user", "content": q})
    registrar(f"\n**usuario>** {q}")
    try:
        d, seg = preguntar(historial)
    except urllib.error.HTTPError as e:
        print(f"{ROJO}  HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}{FIN}")
        historial.pop()
        return False
    except Exception as e:
        print(f"{ROJO}  error: {e}{FIN}")
        historial.pop()
        return False

    msg = d.get("choices", [{}])[0].get("message", {})
    texto = msg.get("content") or ""
    historial.append({"role": "assistant", "content": texto})

    # Los campos extra son lo que interesa medir del sistema, no de la respuesta.
    marcas = []
    for clave, etiqueta in (("_backend", "backend"), ("_piezas", "piezas"),
                            ("_reparto", "REPARTO"), ("_pipeline", "pipeline"),
                            ("_cache", "cache"), ("_profile", "perfil")):
        v = d.get(clave, msg.get(clave))
        if v not in (None, False):
            marcas.append(etiqueta if v is True else f"{etiqueta}={v}")
    uso = d.get("usage", {})
    if uso.get("completion_tokens"):
        marcas.append(f"{uso['completion_tokens']} tok")
    marcas.append(f"{seg:.1f}s")

    print(f"\n{VERDE}intermediario>{FIN} {texto}")
    print(f"{GRIS}  [{' · '.join(marcas)}]{FIN}")
    registrar(f"\n**intermediario>** [{' · '.join(marcas)}]\n\n{texto}")
    return True


# ─── Modo de un tiro ──────────────────────────────────────────────────────────
if UNICO:
    sesion, historial = cargar_estado()
    if UNICO == "/sombra":
        print(resumen_sombra())
        sys.exit(0)
    if UNICO == "/nuevo":
        ESTADO.unlink(missing_ok=True)
        print(f"{GRIS}  sesion nueva{FIN}")
        sys.exit(0)
    if UNICO == "/sesion":
        print(f"{GRIS}  sesion {sesion} · {len(historial)} mensajes{FIN}")
        sys.exit(0)
    print(f"{AZUL}usuario>{FIN} {UNICO}")
    responder(historial, UNICO)
    guardar_estado(sesion, historial)
    sys.exit(0)


sesion = str(uuid.uuid4())[:8]
historial = []
print(f"\n{AZUL}intermediario{FIN} en 127.0.0.1:{PUERTO} · sesion {sesion}")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/health", timeout=5) as r:
        print(f"{GRIS}  health: {r.status}{FIN}")
except Exception as e:
    print(f"{ROJO}  el intermediario no responde: {e}{FIN}")
    print(f"{GRIS}  inicialo con: cd intermediario && python3 run.py{FIN}")
print(f"{GRIS}  /nuevo  /sesion  /sombra  /salir{FIN}")
registrar(f"\n\n## sesion {sesion} · {time.strftime('%Y-%m-%d %H:%M')}")

while True:
    try:
        q = input(f"\n{AZUL}usuario>{FIN} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        break
    if not q:
        continue
    if q == "/salir":
        break
    if q == "/nuevo":
        historial = []
        sesion = str(uuid.uuid4())[:8]
        print(f"{GRIS}  sesion nueva: {sesion}{FIN}")
        continue
    if q == "/sesion":
        print(f"{GRIS}  sesion {sesion} · {len(historial)} mensajes{FIN}")
        continue
    if q == "/sombra":
        print(resumen_sombra())
        continue

    historial.append({"role": "user", "content": q})
    registrar(f"\n**usuario>** {q}")
    try:
        d, seg = preguntar(historial)
    except urllib.error.HTTPError as e:
        print(f"{ROJO}  HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}{FIN}")
        historial.pop()
        continue
    except Exception as e:
        print(f"{ROJO}  error: {e}{FIN}")
        historial.pop()
        continue

    msg = d.get("choices", [{}])[0].get("message", {})
    texto = msg.get("content") or ""
    historial.append({"role": "assistant", "content": texto})

    # Los campos extra son lo que interesa medir del sistema, no de la respuesta.
    marcas = []
    for clave, etiqueta in (("_backend", "backend"), ("_piezas", "piezas"),
                            ("_reparto", "REPARTO"), ("_pipeline", "pipeline"),
                            ("_cache", "cache"), ("_profile", "perfil")):
        v = d.get(clave, msg.get(clave))
        if v not in (None, False):
            marcas.append(etiqueta if v is True else f"{etiqueta}={v}")
    uso = d.get("usage", {})
    if uso.get("completion_tokens"):
        marcas.append(f"{uso['completion_tokens']} tok")
    marcas.append(f"{seg:.1f}s")

    print(f"\n{VERDE}intermediario>{FIN} {texto}")
    print(f"{GRIS}  [{' · '.join(marcas)}]{FIN}")
    registrar(f"\n**intermediario>** [{' · '.join(marcas)}]\n\n{texto}")

print(f"{GRIS}\nregistro en {REGISTRO}{FIN}")
