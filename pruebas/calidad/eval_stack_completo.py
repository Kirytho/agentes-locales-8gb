# -*- coding: utf-8 -*-
"""eval_stack_completo.py - El banco que mide el SISTEMA, no el modelo.

POR QUE EXISTE (28/08/2026)

Todos los bancos anteriores le hablan al intermediario directo con `urllib`. Miden al
modelo aislado. El fallo que quedo abierto --"gemma opera mal un harness"-- no
aparece ahi: aparece con el stack completo, es decir con el bucle de agente de
Hermes, sus 21 herramientas, sus skills, su prompt de sistema de ~25.800 chars
y el multi-turno.

Ya se DESCARTO POR MEDICION (25-27/08/2026) que la causa sea la cantidad de
herramientas (1 vs 18 da 6/6 y 6/6), el prompt de sistema de Hermes (12/12 con
y sin) o el largo del pedido (11/33/132 palabras dieron 3, 7 y 10 llamadas).
Lo que faltaba era mirar el stack entero funcionando, y para eso hace falta un
instrumento nuevo: `grabador_proxy.py`, que se para en el cable.

    hermes -> :8099 (grabador) -> :8086 (intermediario) -> :8080 (backend)

COMO PUNTUA

Oraculo puro sobre el DISCO, nunca un modelo opinando. Cada escenario prepara un
directorio real, le pasa a Hermes una RUTA ABSOLUTA, y despues compara lo que
quedo en disco con lo que calculamos nosotros.

OJO CON LAS RUTAS ABSOLUTAS: no son un capricho. `hermes --in DIR` NO cambia el
directorio de trabajo de la herramienta `terminal` -- se midio el 28/08 pidiendo
`pwd` y contesta `/home/usuario`. Un escenario con rutas relativas mide el cwd de
Hermes, no al modelo. Ademas la ruta absoluta ataca de frente el defecto ya
conocido: gemma no reproduce texto exacto.

Del cable se obtienen ademas, gratis, las respuestas a dos preguntas abiertas:
  - Cuantas llamadas fueron REALES (`tool_calls`) y cuantas NARRADAS como texto.
    La firma del bug llama.cpp#22786 es `finish_reason: "stop"` con el nombre de
    una herramienta escrito en el contenido.
  - Si alguna peticion llega SIN herramientas y SIN stream, que es la unica
    condicion en que el reparto interno del intermediario podria activarse.

REQUISITOS
  ./iniciar.sh                       (backend 8080 + intermediario 8086 arriba)
  proveedor `bancolocal` en ~/.hermes/config.yaml apuntando a :8099

Uso:
    python3 pruebas/calidad/eval_stack_completo.py [escenario...]
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODELO = os.getenv("BANCO_MODELO", "principal")
PROVEEDOR = os.getenv("BANCO_PROVEEDOR", "bancolocal")
PUERTO_GRABADOR = os.getenv("BANCO_GRABADOR_PUERTO", "8099")
DESTINO = os.getenv("BANCO_DESTINO", "8086")
GRABACION = Path(os.getenv("BANCO_GRABACION", "/tmp/banco_stack.jsonl"))
RAIZ = Path(os.getenv("BANCO_DIR", "/tmp/banco_stack"))
# Un turno agentico con 21 herramientas puede tardar. 300 s por escenario es
# holgado: el humo del 28/08 resolvio uno de dos vueltas en ~4 s.
LIMITE = int(os.getenv("BANCO_LIMITE", "300"))
REPES = int(os.getenv("BANCO_REPES", "1"))
# Texto que se antepone al pedido. Sirve para separar DOS preguntas distintas
# que se confunden con facilidad: si una skill SIRVE, y si el modelo la
# DESCUBRE solo. Medido el 28/08/2026: en 6 ejecuciones el modelo nunca llamo a
# `skill_view`, aunque tenia `skill_view`/`skills_list` entre sus 21
# herramientas y la descripcion de la skill en el prompt de sistema (crecio 91
# chars al agregarla). Sin forzarla, un resultado nulo no distingue "la skill no
# aporta" de "nunca la leyo".
PREFIJO = os.getenv("BANCO_PREFIJO", "")
# Lista de toolsets para `hermes -t`. Vacio = los que esten habilitados por
# defecto. Sirve para medir cuanto cuesta el PRESUPUESTO FIJO del harness: los
# esquemas de las 21 herramientas son 61.343 B (~15.335 tokens) en CADA
# peticion, mas del doble que el prompt de sistema, y viajan aunque el modelo no
# use ninguna. `hermes prompt-size` los desglosa.
TOOLSETS = os.getenv("BANCO_TOOLSETS", "")


# --------------------------------------------------------------------------
# Escenarios. Cada uno: monta(dir) -> verdad ; pide(dir) -> prompt ;
#                       revisa(dir, verdad, texto_final) -> (bool, detalle)
# --------------------------------------------------------------------------

def _lineas(p: Path) -> int:
    return len(p.read_text(encoding="utf-8").splitlines())


def _huellas(d: Path) -> dict:
    """SHA-1 de cada archivo del escenario, tomado antes de ejecutar.

    POR QUE (28/08/2026): en una ejecucion el agente REESCRIBIO los numeros.txt de
    entrada con datos inventados (`5\\n5\\n5` con backslash literal en vez de
    `1`, `1`, `1`) y despues sumo correctamente SU propio dato. El oraculo
    comparaba contra la verdad de origen y decia "sumas mal", que es la razon
    equivocada: no fallo la suma, se corrompio la entrada. Sin esta huella, el
    banco reporta un defecto que no es el que ocurrio.
    """
    return {
        str(p.relative_to(d)): hashlib.sha1(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob("*")) if p.is_file()
    }


def _entrada_tocada(d: Path, antes: dict) -> list[str]:
    return sorted(k for k, h in antes.items()
                  if not (d / k).exists() or hashlib.sha1((d / k).read_bytes()).hexdigest() != h)


def montar_inventario(d: Path) -> dict:
    contenido = {"alfa": 3, "beta": 7, "gamma": 1, "delta": 12, "epsilon": 5}
    for nombre, n in contenido.items():
        (d / f"{nombre}.txt").write_text("\n".join(f"linea {i}" for i in range(n)) + "\n")
    return {"esperado": {f"{k}.txt": v for k, v in contenido.items()}}


def pedir_inventario(d: Path) -> str:
    return (
        f"En el directorio {d} hay varios archivos .txt. "
        f"Escribe el archivo {d}/inventario.txt con una linea por cada .txt, "
        f"con el formato exacto nombre:lineas (por ejemplo alfa.txt:3), "
        f"ordenado alfabeticamente. No agregues nada mas al archivo."
    )


def revisar_inventario(d: Path, verdad: dict, texto: str):
    f = d / "inventario.txt"
    if not f.exists():
        return False, "no escribio inventario.txt"
    lineas = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    esperado = [f"{k}:{v}" for k, v in sorted(verdad["esperado"].items())]
    if lineas == esperado:
        return True, "exacto"
    return False, f"esperado {esperado} / obtenido {lineas}"


def montar_reparto(d: Path) -> dict:
    partes = {"norte": [4, 8, 15], "sur": [16, 23, 42], "este": [1, 1, 1], "oeste": [100, 250]}
    for nombre, nums in partes.items():
        sub = d / nombre
        sub.mkdir()
        (sub / "numeros.txt").write_text("\n".join(str(n) for n in nums) + "\n")
    return {"esperado": {k: sum(v) for k, v in partes.items()}}


def pedir_reparto(d: Path) -> str:
    return (
        f"El directorio {d} tiene cuatro subdirectorios: norte, sur, este y oeste. "
        f"Cada uno contiene un numeros.txt con un numero por linea. "
        f"Calcula la suma de cada subdirectorio y escribe {d}/sumas.txt con una "
        f"linea por subdirectorio con el formato exacto nombre:suma, en ese orden "
        f"(norte, sur, este, oeste)."
    )


def revisar_reparto(d: Path, verdad: dict, texto: str):
    f = d / "sumas.txt"
    if not f.exists():
        return False, "no escribio sumas.txt"
    got = {}
    for l in f.read_text(encoding="utf-8").splitlines():
        if ":" in l:
            k, _, v = l.partition(":")
            got[k.strip()] = v.strip()
    esperado = {k: str(v) for k, v in verdad["esperado"].items()}
    faltan = [k for k in esperado if got.get(k) != esperado[k]]
    if not faltan:
        return True, "las cuatro sumas correctas"
    return False, f"mal en {faltan}: esperado {esperado} / obtenido {got}"


# Cadena elegida a proposito: mezcla guion bajo, guion, mayusculas, digitos y
# punto. Es el tipo de texto que el defecto conocido rompe.
CADENA = "BANCO_v2.7-Delta_Q5_K_M::a3f9"


def montar_exacto(d: Path) -> dict:
    (d / "origen.txt").write_text(f"clave={CADENA}\n")
    return {"esperado": CADENA}


def pedir_exacto(d: Path) -> str:
    return (
        f"El archivo {d}/origen.txt tiene una linea con el formato clave=VALOR. "
        f"Copia EXACTAMENTE ese VALOR (sin el 'clave=' y sin comillas) como unica "
        f"linea del archivo {d}/copia.txt."
    )


def revisar_exacto(d: Path, verdad: dict, texto: str):
    f = d / "copia.txt"
    if not f.exists():
        return False, "no escribio copia.txt"
    got = f.read_text(encoding="utf-8").strip()
    if got == verdad["esperado"]:
        return True, "byte a byte"
    return False, f"esperado {verdad['esperado']!r} / obtenido {got!r}"


def montar_informe(d: Path) -> dict:
    tam = {"uno.log": 120, "dos.log": 4096, "tres.log": 77, "notas.txt": 9000}
    for nombre, n in tam.items():
        (d / nombre).write_bytes(b"x" * n)
    return {"n_logs": 3, "mayor": "dos.log"}


def pedir_informe(d: Path) -> str:
    return (
        f"En {d}, cuantos archivos .log hay y cual es el .log mas grande? "
        f"Responde en una sola frase, sin escribir ningun archivo."
    )


def revisar_informe(d: Path, verdad: dict, texto: str):
    t = (texto or "").lower()
    tiene_n = bool(re.search(rf"\b{verdad['n_logs']}\b", t)) or "tres" in t
    tiene_m = verdad["mayor"].lower() in t
    if tiene_n and tiene_m:
        return True, "numero y nombre correctos"
    falta = []
    if not tiene_n:
        falta.append(f"no dice {verdad['n_logs']}")
    if not tiene_m:
        falta.append(f"no nombra {verdad['mayor']}")
    return False, "; ".join(falta)


# ── Escenario 5: CONTEXTO LARGO ──────────────────────────────────────────────
# POR QUE EXISTE (06/09/2026): los otros cuatro escenarios usan ~25.000 tokens
# contando el presupuesto fijo de Hermes (~22.000). Sirven para comparar
# modelos, pero NO para comparar CONTEXTOS: medir si ctx 196.608 aporta algo
# usando tareas que nunca pasan de 25.000 es medir la variable equivocada.
#
# Este escenario usa ~45.000 tokens solo de archivos. Con el presupuesto fijo
# la sesion llega a ~67.000 y sigue creciendo con cada lectura y respuesta.
# Esta CALIBRADO PARA DOLER: el 27/08 este mismo fixture mato una sesion a ctx
# 81.920 con `Context length exceeded` y 308 errores en el backend.
#
# El oraculo pide 6 de 8 y no las 8: es una tarea de razonamiento sobre ocho
# items independientes, no una copia exacta como `exacto`. Exigir 8/8 mediria
# suerte; exigir 1 no mediria nada. El detalle informa el numero exacto.
_BUGS = {
    "inventario":  ("recalcular_stock_zx",  "    total = sum(i.cantidad for i in items)\n    return total / len(items)   # ZeroDivisionError si items esta vacio"),
    "facturacion": ("aplicar_descuento_qv", "    for d in descuentos:\n        precio -= d.monto      # sin piso en 0: el precio puede quedar negativo\n    return precio"),
    "envios":      ("calcular_ruta_mk",     "    visitados = []\n    while pendientes:\n        n = pendientes.pop()\n        visitados.append(n)\n        pendientes.extend(n.vecinos)   # no chequea visitados: ciclo infinito"),
    "usuarios":    ("normalizar_email_bt",  "    return correo.strip().lower()[:64]   # trunca a 64: dos correos distintos colisionan"),
    "reportes":    ("agrupar_por_mes_hn",   "    return f'{f.month}'   # agrupa por mes SIN el anio: mezcla eneros de anios distintos"),
    "auditoria":   ("registrar_evento_pw",  "    with open(RUTA, 'w') as fh:   # 'w' en vez de 'a': pisa el log entero cada vez\n        fh.write(linea)"),
    "sesiones":    ("expirar_sesiones_dr",  "    ahora = time.time()\n    for s in sesiones:\n        if s.creada + TTL < ahora:\n            sesiones.remove(s)   # muta la lista mientras la itera: saltea elementos"),
    "notificador": ("reintentar_envio_ls",  "    for i in range(5):\n        if enviar(msg): return True\n    return False   # cinco reintentos SIN espera: martilla al servicio caido"),
}
_RELLENO = [
    ("validar_entrada", "    if not isinstance(d, dict):\n        raise TypeError('se esperaba dict')\n    return d"),
    ("formatear_fecha", "    return f.strftime('%Y-%m-%d') if f else ''"),
    ("leer_config",     "    with open(ruta) as fh:\n        return json.load(fh)"),
    ("contar_items",    "    return sum(1 for _ in xs)"),
    ("a_mayusculas",    "    return s.upper() if s else ''"),
    ("unir_partes",     "    return '/'.join(p.strip('/') for p in partes if p)"),
    ("es_positivo",     "    return isinstance(n, (int, float)) and n > 0"),
    ("truncar",         "    return s if len(s) <= n else s[:n] + '...'"),
    ("sanear_clave",    "    return ''.join(c for c in k if c.isalnum() or c == '_')"),
    ("dividir_lotes",   "    return [xs[i:i+n] for i in range(0, len(xs), n)]"),
]


def montar_contexto(d: Path) -> dict:
    import random
    # semilla fija: los seis brazos tienen que ver EXACTAMENTE el mismo fixture,
    # si no la comparacion mide el azar del relleno.
    rnd = random.Random(7)
    for serv, (fn, cuerpo) in _BUGS.items():
        sub = d / serv
        sub.mkdir()
        L = ["import json", "import time", "", "TTL = 3600", "RUTA = '/var/log/app.log'", ""]
        relleno = [(f"{n}_{k}", c) for k in range(16) for n, c in _RELLENO]
        rnd.shuffle(relleno)
        m = len(relleno) // 2
        firma = "(d=None, f=None, ruta='', xs=(), s='', partes=(), n=0, k='', **kw):"
        for n, c in relleno[:m]:
            L += [f"def {n}{firma}", c, ""]
        L += [f"def {fn}(items=(), descuentos=(), precio=0, pendientes=None, correo='',"
              f" f=None, linea='', sesiones=None, msg=None):", cuerpo, ""]
        for n, c in relleno[m:]:
            L += [f"def {n}{firma}", c, ""]
        (sub / "servicio.py").write_text("\n".join(L))
    return {"esperado": [v[0] for v in _BUGS.values()], "minimo": 6}


def pedir_contexto(d: Path) -> str:
    return (
        f"En {d} hay OCHO subdirectorios independientes (inventario, facturacion, "
        f"envios, usuarios, reportes, auditoria, sesiones, notificador). Cada uno "
        f"tiene un servicio.py de ~540 lineas con muchas funciones correctas y "
        f"EXACTAMENTE UNA con un defecto real. Para cada servicio dime el NOMBRE "
        f"EXACTO de la funcion defectuosa. Son ocho analisis independientes."
    )


def revisar_contexto(d: Path, verdad: dict, texto: str):
    t = texto or ""
    halladas = [fn for fn in verdad["esperado"] if fn in t]
    n, minimo = len(halladas), verdad["minimo"]
    faltan = [fn for fn in verdad["esperado"] if fn not in t]
    if n >= minimo:
        return True, f"nombro {n}/8" + (f" (faltaron {faltan})" if faltan else " (todas)")
    return False, f"solo nombro {n}/8, minimo {minimo}; faltaron {faltan}"


ESCENARIOS = {
    # El unico que puntua sobre PROSA. Los otros tres puntuan sobre DISCO.
    # La distincion no es cosmetica: eval_scripts.py ya midio que cambiando solo
    # el oraculo, el mismo modelo pasa de ~100% (script) a ~67% (prosa).
    "informe": (montar_informe, pedir_informe, revisar_informe),
    "inventario": (montar_inventario, pedir_inventario, revisar_inventario),
    "reparto": (montar_reparto, pedir_reparto, revisar_reparto),
    "exacto": (montar_exacto, pedir_exacto, revisar_exacto),
    # El unico que estira el contexto: ~45.000 tokens de archivos.
    "contexto": (montar_contexto, pedir_contexto, revisar_contexto),
}


# --------------------------------------------------------------------------
# Lectura del cable
# --------------------------------------------------------------------------

# Gemma tiene sintaxis nativa propia; si sale por ahi tampoco es una tool_call
# valida para el harness, pero no es lo mismo que narrar en prosa.
NATIVA = re.compile(r"<\|?tool_call\|?>")


def _narradas(contenido: str, ofrecidas: list[str]) -> list[str]:
    """Nombres de herramientas ESCRITOS como texto en la respuesta.

    Se exige el parentesis de apertura para no contar una mencion en prosa
    ("uso la herramienta terminal para...") como si fuera una llamada narrada.
    """
    fuera = []
    for nombre in set(ofrecidas):
        if re.search(rf"\b{re.escape(nombre)}\s*\(", contenido):
            fuera.append(nombre)
    return sorted(fuera)


def leer_cable(archivo: Path) -> dict:
    filas = []
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                try:
                    filas.append(json.loads(linea))
                except Exception:
                    pass
    filas.sort(key=lambda r: r.get("n", 0))

    m = {
        "peticiones": len(filas),
        "vueltas_agente": 0,     # las que llevan herramientas: el bucle real
        "sin_herramientas": 0,
        "sin_stream": 0,
        "sin_herramientas_ni_stream": 0,   # unica condicion donde el reparto interno podria activarse
        "llamadas_reales": 0,
        "narradas": [],
        "nativa_en_texto": 0,
        "razonamiento_con_llamada": 0,
        "finish": {},
        "firma_22786": 0,        # finish=stop + herramienta narrada
        "errores_http": 0,
        "max_herramientas": 0,
        "max_chars_sistema": 0,
        # Los argumentos de cada llamada. Sin esto, un escenario fallado dice
        # "salio mal" y no se puede saber POR QUE: el 28/08 el escenario reparto
        # escribio las cuatro sumas en cero y no quedaba rastro del script.
        "detalle_llamadas": [],
    }
    for r in filas:
        p, res = r.get("pedido", {}), r.get("respuesta", {})
        if r.get("estado") and r["estado"] != 200:
            m["errores_http"] += 1
        con_h = p.get("n_herramientas", 0) > 0
        m["max_herramientas"] = max(m["max_herramientas"], p.get("n_herramientas", 0))
        m["max_chars_sistema"] = max(m["max_chars_sistema"], p.get("chars_sistema", 0))
        if con_h:
            m["vueltas_agente"] += 1
        else:
            m["sin_herramientas"] += 1
        if not p.get("stream"):
            m["sin_stream"] += 1
        if not con_h and not p.get("stream"):
            m["sin_herramientas_ni_stream"] += 1

        for c in res.get("tool_calls") or []:
            m["detalle_llamadas"].append(
                {"n": r.get("n"), "nombre": c.get("nombre"), "argumentos": (c.get("argumentos") or "")[:1500]}
            )
        m["llamadas_reales"] += len(res.get("tool_calls") or [])
        fr = res.get("finish_reason") or "?"
        m["finish"][fr] = m["finish"].get(fr, 0) + 1

        contenido = res.get("contenido") or ""
        narr = _narradas(contenido, p.get("herramientas") or [])
        if narr:
            m["narradas"].extend(narr)
            if fr == "stop":
                m["firma_22786"] += 1
        if NATIVA.search(contenido):
            m["nativa_en_texto"] += 1
        razon = res.get("razonamiento") or ""
        if razon and _narradas(razon, p.get("herramientas") or []):
            m["razonamiento_con_llamada"] += 1
    return m


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------

def arrancar_grabador():
    # El puerto tiene que estar LIBRE. Si ya hay algo escuchando, el grabador
    # nuevo no puede abrirlo, pero la verificacion de salud de abajo igual pasa
    # --contra el proceso ajeno-- y el banco se ejecuta entero enviando el trafico
    # por un grabador que escribe en OTRO archivo. Paso el 28/08/2026: 8
    # ejecuciones con `vueltas=0` y el cable vacio mientras las tareas se hacian
    # bien. Un instrumento que se cree sano midiendo por el cable equivocado es
    # peor que uno que falla.
    import socket
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", int(PUERTO_GRABADOR))) == 0:
            raise SystemExit(
                f"el puerto {PUERTO_GRABADOR} ya esta ocupado. Es otro grabador de una "
                f"corrida anterior: matalo antes de seguir, o usa BANCO_GRABADOR_PUERTO."
            )
    GRABACION.parent.mkdir(parents=True, exist_ok=True)
    entorno = dict(os.environ, BANCO_GRABACION=str(GRABACION))
    proc = subprocess.Popen(
        # El grabador vive en pruebas/instrumentos/ desde la reorganizacion del
        # 07/09/2026: es una herramienta de medicion, no un banco.
        [sys.executable, str(AQUI.parent / "instrumentos" / "grabador_proxy.py"),
         PUERTO_GRABADOR, DESTINO],
        env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    import urllib.request
    for _ in range(30):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PUERTO_GRABADOR}/v1/models", timeout=2).read()
            return proc
        except Exception:
            if proc.poll() is not None:
                raise SystemExit(f"el grabador murio: {proc.stderr.read().decode()[-600:]}")
    raise SystemExit("el grabador no respondio en 15 s")


def correr(nombre: str, rep: int) -> dict:
    montar, pedir, revisar = ESCENARIOS[nombre]
    d = RAIZ / f"{nombre}_{rep}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    verdad = montar(d)
    huellas = _huellas(d)
    prompt = (PREFIJO + "\n\n" if PREFIJO else "") + pedir(d)

    # Truncar el cable justo antes: cada escenario se lee solo.
    GRABACION.write_text("")
    t0 = time.time()
    try:
        r = subprocess.run(
            ["hermes", "-z", prompt, "-m", MODELO, "--provider", PROVEEDOR, "--yolo"]
            + (["-t", TOOLSETS] if TOOLSETS else []),
            capture_output=True, text=True, timeout=LIMITE,
        )
        salida, corto = r.stdout.strip(), False
        err_hermes = (r.stderr or "").strip()
    except subprocess.TimeoutExpired as e:
        salida = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        corto, err_hermes = True, ""
    segundos = round(time.time() - t0, 1)

    ok, detalle = revisar(d, verdad, salida)
    if corto:
        # Una ejecucion que se comio el limite de tiempo NO es un acierto, aunque
        # el archivo haya quedado bien. Paso el 28/08/2026 con granite-4.2-3b:
        # 103 vueltas seguidas llamando `terminal`, 300 s, y el oraculo decia OK
        # porque el disco estaba correcto. El agente nunca terminó: eso es un
        # bucle, y contarlo como exito inflaba el puntaje de 10/12 a 11/12.
        ok = False
        detalle = f"NO TERMINO ({LIMITE}s de tope); " + detalle
    tocados = _entrada_tocada(d, huellas)
    if tocados:
        # Se informa aparte porque es un fallo DISTINTO: el agente no calculo
        # mal, cambio los datos sobre los que se le pidio calcular.
        detalle = f"CORROMPIO LA ENTRADA {tocados}; " + detalle
    cable = leer_cable(GRABACION)
    return {"escenario": nombre, "rep": rep, "ok": ok, "detalle": detalle,
            "entrada_tocada": tocados, "segundos": segundos, "corto_por_tiempo": corto,
            "respuesta": salida[-500:], "error_hermes": err_hermes[-400:],
            "cable": cable}


def backend_vivo() -> str:
    """Que el backend conteste ANTES de ejecutar un escenario. "" si esta sano.

    POR QUE (11/09/2026): con el modelo en Kaggle detras de un tunel, el tunel
    se cayo a mitad de una ejecucion y los tres escenarios que faltaban dieron
    MAL con 0 llamadas. Parecia que el modelo no sabia resolverlos; en realidad
    nunca le llego el pedido -- HTTP 530 seis veces. Un corte de transporte NO
    puede disfrazarse de fallo del modelo, asi que se corta con un mensaje
    claro en vez de seguir midiendo contra la nada.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{DESTINO}/v1/models", timeout=20) as r:
            if r.status != 200:
                return f"el intermediario devolvio HTTP {r.status}"
    except Exception as e:
        return f"el intermediario ({DESTINO}) no responde: {type(e).__name__}: {e}"
    cuerpo = json.dumps({"model": MODELO, "max_tokens": 4, "temperature": 0,
                         "messages": [{"role": "user", "content": "di OK"}]}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{DESTINO}/v1/chat/completions",
                                 data=cuerpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())
    except Exception as e:
        return f"el backend no genera: {type(e).__name__}: {str(e)[:120]}"
    err = d.get("error")
    if err:
        return f"el backend devolvio error: {str(err)[:160]}"
    return ""


def main() -> int:
    pedidos = [a for a in sys.argv[1:] if a in ESCENARIOS] or list(ESCENARIOS)
    RAIZ.mkdir(parents=True, exist_ok=True)
    grabador = arrancar_grabador()
    filas = []
    try:
        for rep in range(1, REPES + 1):
            for nombre in pedidos:
                mal = backend_vivo()
                if mal:
                    print(f"\n  ABORTA antes de `{nombre}`: {mal}")
                    print("  No se sigue: un transporte caido daria MAL en todos "
                          "los escenarios que falten, y eso no es del modelo.")
                    return 2
                f = correr(nombre, rep)
                filas.append(f)
                c = f["cable"]
                print(f"{'OK ' if f['ok'] else 'MAL'} {f['escenario']:<11} "
                      f"{f['segundos']:>6.1f}s  vueltas={c['vueltas_agente']:<3} "
                      f"llamadas={c['llamadas_reales']:<3} narradas={len(c['narradas']):<2} "
                      f"22786={c['firma_22786']}  {f['detalle'][:90]}", flush=True)
                if c["peticiones"] == 0:
                    # El cable en CERO no es un resultado: Hermes no llego a
                    # hablar con el intermediario, asi que el modelo nunca vio el pedido.
                    #
                    # `backend_vivo()` no alcanza para esto. Paso el 12/09/2026
                    # con el primario en Kaggle: el tunel devolvia 200 y el
                    # backend generaba, pero el banco pide `-m principal` por defecto
                    # y Hermes rechazo ESE modelo por contexto ("below the
                    # minimum 64,000 required by Hermes Agent"). El transporte
                    # estaba sano; el fallo estaba un escalon mas arriba. Sin
                    # este corte el banco imprime 0/5 con cara de medicion.
                    print(f"\n  ABORTA en `{nombre}`: el cable no registro NI UNA peticion.")
                    print(f"  Hermes no llego a hablar con el intermediario, asi que esto no "
                          f"mide al modelo.")
                    print(f"  Revisar que BANCO_MODELO={MODELO!r} sea uno de "
                          f"BACKEND_NAMES y que su contexto llegue a 64k.")
                    if f["error_hermes"]:
                        print(f"  hermes dijo: {f['error_hermes'][:300]}")
                    return 2
    finally:
        grabador.terminate()

    print()
    ok = sum(1 for f in filas if f["ok"])
    print(f"ACIERTOS  {ok}/{len(filas)}")
    tot = {k: 0 for k in ("vueltas_agente", "llamadas_reales", "firma_22786",
                          "nativa_en_texto", "sin_herramientas_ni_stream",
                          "razonamiento_con_llamada", "errores_http")}
    for f in filas:
        for k in tot:
            tot[k] += f["cable"][k]
    narradas = sorted({n for f in filas for n in f["cable"]["narradas"]})
    print(f"CABLE     vueltas={tot['vueltas_agente']} llamadas_reales={tot['llamadas_reales']} "
          f"nativa_en_texto={tot['nativa_en_texto']} razonamiento_con_llamada={tot['razonamiento_con_llamada']}")
    print(f"BUG 22786 firma (finish=stop + herramienta narrada): {tot['firma_22786']}"
          + (f"  narradas: {narradas}" if narradas else ""))
    print(f"REPARTO   peticiones sin herramientas Y sin stream: {tot['sin_herramientas_ni_stream']}")
    print(f"HTTP      respuestas != 200: {tot['errores_http']}")
    corruptas = [f"{f['escenario']}#{f['rep']}" for f in filas if f.get("entrada_tocada")]
    print(f"ENTRADA   corridas que reescribieron los datos de entrada: "
          f"{len(corruptas)}" + (f"  {corruptas}" if corruptas else ""))
    if filas:
        c = filas[-1]["cable"]
        print(f"CONTEXTO  herramientas ofrecidas={c['max_herramientas']} "
              f"prompt de sistema={c['max_chars_sistema']} chars")

    destino = RAIZ / "resultado.json"
    destino.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndetalle -> {destino}")
    return 0 if ok == len(filas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
