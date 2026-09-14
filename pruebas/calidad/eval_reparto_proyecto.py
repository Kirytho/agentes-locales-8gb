# -*- coding: utf-8 -*-
"""eval_reparto_proyecto.py - Repartir un PROYECTO entre N trabajadores, ¿integra?

POR QUE EXISTE (12/09/2026)

Ya se midio que repartir FUNCIONES entre slots concurrentes gana:
`pruebas/rendimiento/medir_reparto_piezas.py` (22/08) dio 110/110 piezas y
10/10 integraciones en los tres modos, con el paralelo 2,9x mas rapido que el
monolito (84,6 s contra 244,6). Pero ahi las cuatro piezas son funciones en UN
archivo, y las interfaces son triviales.

Esto es lo otro: un PROYECTO Django real de 10 a 27 archivos, donde `views.py`
importa de `.forms` y `.models`, y donde ademas el modelo tiene que declarar los
IDs de los elementos HTML que uso para que el test los encuentre. Dos
trabajadores que no se ven tienen que coincidir en una firma Y en un id de HTML.
Ningun test por pieza detecta eso; solo detecta el proyecto entero iniciado.

DE DONDE SALEN LAS TAREAS Y EL ORACULO

De ProjectEval (ACL 2025 Findings / ACM TOSEM), clonado en `externos/`. No se
versiona: es GPL-3.0 y pesa 141 MB, igual que los motores de llama.cpp.

    https://github.com/RyanLoil/ProjectEval

Su fase de generacion y su fase de juicio estan separadas, y eso es lo que hace
viable este banco: NOSOTROS reemplazamos la generacion, y su juez queda intacto.
El juez inicia el proyecto Django de verdad y lo maneja con Selenium como lo
haria un usuario, asi que un proyecto que no integra no pasa sin que nadie tenga
que opinar sobre el codigo.

    este script  ->  JSON en experiments/  ->  run_judge.py  ->  Selenium

TRUCO DE MONTAJE: los tres brazos se escriben como si fueran tres MODELOS
distintos en la jerarquia que el juez exige
(`<dir>/<modelo>/direct/<modelo>_<ts>_level_<n>.json`). Asi el juez los evalua
en una sola pasada y quedan comparables sin tocarle una linea.

LOS TRES BRAZOS

    MONOLITO    1 llamada: escribe todos los archivos con trabajo de una
    SECUENCIAL  N llamadas: la k-esima VE lo que escribieron las anteriores
    PARALELO    N llamadas a la vez: cada una ve SOLO su archivo, mas las
                FIRMAS de los otros (nombres y argumentos, sin cuerpos)

Los N trabajadores del paralelo son SLOTS del llama-server (`--parallel`), no
subagentes de un harness. Esa es la diferencia que hace viable el experimento:
un subagente de Hermes arrastra ~5.657 tokens de prompt de sistema propio y por
eso el abanico agotaba la reserva de KV (medido el 28/08 y el 07/09); un slot con
un prompt minimo cuesta una fraccion.

QUE SE COPIA Y QUE SE PIDE

Del esqueleto se copian TAL CUAL los archivos sin trabajo (settings.py, wsgi.py,
templates dados). Solo se piden los que tienen `def`/`class` con cuerpo vacio.
Sin esto el experimento mide otra cosa: gpt-5 en los resultados oficiales
regenero el andamiaje entero y entrego 26 a 92 archivos por proyecto, contra los
10-27 del esqueleto.

Uso:
    python3 pruebas/calidad/eval_reparto_proyecto.py
    BANCO_REPARTO_TAREAS=1,3,5 BANCO_REPARTO_REPES=3 ... (ver variables abajo)
"""
import argparse
import ast
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
BANCO = Path(os.getenv("BANCO_REPARTO_BANCO", RAIZ / "externos" / "ProjectEval"))

URL = os.getenv("BANCO_REPARTO_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODELO = os.getenv("BANCO_REPARTO_MODELO", "principal")
# Cuantos trabajadores como maximo en el brazo paralelo. Tiene que coincidir con
# el `--parallel` del servidor: pedir mas no da mas concurrencia, solo encola.
TRABAJADORES = int(os.getenv("BANCO_REPARTO_TRABAJADORES", "4"))
REPES = int(os.getenv("BANCO_REPARTO_REPES", "3"))
LIMITE = int(os.getenv("BANCO_REPARTO_LIMITE", "600"))
MAX_TOKENS = int(os.getenv("BANCO_REPARTO_MAX_TOKENS", "4000"))
TEMP = float(os.getenv("BANCO_REPARTO_TEMP", "0.2"))
# Que tareas ejecutar. Vacio = las 4 primeras website (las mas pequeñas por piezas).
TAREAS = [t.strip() for t in os.getenv("BANCO_REPARTO_TAREAS", "").split(",") if t.strip()]
BRAZOS = [b.strip() for b in os.getenv("BANCO_REPARTO_BRAZOS",
                                       "monolito,secuencial,paralelo").split(",") if b.strip()]
SALIDA = Path(os.getenv("BANCO_REPARTO_SALIDA", BANCO / "experiments"))
ETIQUETA = os.getenv("BANCO_REPARTO_ETIQUETA", datetime.now().strftime("%Y%m%d-reparto"))

_RE_BLOQUE = re.compile(r"```(?:python|py|html|django)?\s*\n(.*?)```", re.S)


# ─── Lectura del banco externo ───────────────────────────────────────────────

def cargar_tareas() -> list[dict]:
    """Las 20 tareas de ProjectEval, tal como vienen."""
    p = BANCO / "data" / "project_eval_project.json"
    if not p.exists():
        raise SystemExit(
            f"no encuentro el banco en {BANCO}.\n"
            f"  git clone --depth 1 https://github.com/RyanLoil/ProjectEval.git {BANCO}")
    return json.loads(p.read_text(encoding="utf-8"))


# Andamiaje de Django: tienen `def` pero los escribe `django-admin`, no el
# modelo. Contarlos como pieza inflaba el reparto con trabajo que nadie hace
# (medido el 12/09: el modelo ignoro `manage.py`, y al copiarse del esqueleto la
# omision no se notaba).
ANDAMIAJE = {"manage.py", "apps.py", "wsgi.py", "asgi.py", "settings.py",
             "0001_initial.py", "__init__.py"}


def piezas_de(tarea: dict) -> list[dict]:
    """Archivos del esqueleto que tienen algo que escribir.

    OJO: el esqueleto deja el cuerpo VACIO, no pone `pass`. Buscar `pass` da
    cero piezas en 4 de las 16 tareas website (9, 13, 14, 20) y las omite en
    silencio; lo que marca la pieza es tener `def`/`class`.
    """
    fuera = []
    for f in tarea["skeleton"]:
        if Path(f["path"]).name in ANDAMIAJE:
            continue
        codigo = f.get("code", "")
        if re.search(r"^\s*(?:def|class)\s", codigo, re.M):
            fuera.append(f)
        elif f["path"].endswith(".html") and "<!--" in codigo:
            # Los templates del esqueleto son cascaras: `<body>` con UN comentario
            # que dice que va dentro. Son 88 de los 91 templates del banco.
            # Dejarlos fuera fue el defecto del 12/09: se copiaban vacios, y como
            # el juez maneja el proyecto con Selenium, NINGUN elemento aparecia.
            # Los tres brazos daban identico 4/48 -- el piso, no una comparacion.
            fuera.append(f)
    return fuera


def firmas_de(codigo: str) -> str:
    """Nombres y argumentos, sin cuerpos: el contrato entre trabajadores.

    Se extrae con `ast`, no con expresiones regulares, para que un docstring que
    contenga la palabra `def` no invente una firma.
    """
    try:
        arbol = ast.parse(codigo)
    except SyntaxError:
        return ""
    lineas = []

    def firma(nodo, sangria=""):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in nodo.args.args]
            lineas.append(f"{sangria}def {nodo.name}({', '.join(args)})")
        elif isinstance(nodo, ast.ClassDef):
            bases = [b.id for b in nodo.bases if isinstance(b, ast.Name)]
            lineas.append(f"{sangria}class {nodo.name}({', '.join(bases)})")
            for hijo in nodo.body:
                firma(hijo, sangria + "    ")

    for nodo in arbol.body:
        firma(nodo)
    return "\n".join(lineas)


# ─── Hablarle al backend ─────────────────────────────────────────────────────

def pedir(prompt: str, sistema: str = "") -> tuple[str, float, int]:
    """Una llamada al backend. Devuelve (texto, segundos, tokens_de_salida)."""
    mensajes = ([{"role": "system", "content": sistema}] if sistema else [])
    mensajes.append({"role": "user", "content": prompt})
    cuerpo = json.dumps({"model": MODELO, "messages": mensajes,
                         "max_tokens": MAX_TOKENS, "temperature": TEMP}).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=LIMITE) as r:
            d = json.loads(r.read())
    except Exception as e:
        return f"__ERROR__ {type(e).__name__}: {str(e)[:160]}", time.time() - t0, 0
    seg = time.time() - t0
    msg = (d.get("choices") or [{}])[0].get("message", {})
    # El contenido puede venir vacio y el texto en reasoning_content: K2 razona
    # en cada llamada. NO concatenar los dos -- un borrador en el razonamiento se
    # aplicaria junto al bueno (se corrigio igual en el MCP, commit 80e0568).
    texto = msg.get("content") or ""
    if not texto.strip():
        texto = msg.get("reasoning_content") or ""
    return texto, seg, (d.get("usage") or {}).get("completion_tokens", 0)


def solo_codigo(texto: str) -> str:
    """El contenido del primer bloque ``` , o el texto pelado si no hay."""
    m = _RE_BLOQUE.search(texto)
    return (m.group(1) if m else texto).strip()


# ─── Los tres brazos ─────────────────────────────────────────────────────────

_SISTEMA = ("Eres un programador de Django. Respondes SOLO con codigo dentro de "
            "un bloque ```. Sin explicaciones.")
_SISTEMA_HTML = ("Eres un programador de Django. Respondes SOLO con una plantilla "
                 "HTML completa dentro de un bloque ```html. Sin explicaciones.")
# Las tareas 16, 17 y 18 son de consola y la 19 es batch: NO son Django. Decirles
# "eres un programador de Django" es darles la instruccion equivocada.
_SISTEMA_PY = ("Eres un programador de Python. Respondes SOLO con codigo dentro de "
               "un bloque ```python. Sin explicaciones.")


def _sistema_de(pieza: dict, tarea: dict | None = None) -> str:
    if pieza["path"].endswith(".html"):
        return _SISTEMA_HTML
    if tarea is not None and tarea.get("project_type") != "website":
        return _SISTEMA_PY
    return _SISTEMA


def _elementos_esperados(tarea: dict) -> str:
    """Que elementos tiene que haber en las paginas, segun el banco.

    Sale de los NOMBRES y descripciones de los parametros del `testcode` -- que
    son especificacion, no respuesta: los tests mismos NO se le pasan al modelo.
    Sin esto los ids de HTML no estan en ninguna parte del esqueleto, cada
    trabajador inventa el suyo, y el brazo paralelo pierde por construccion en
    vez de por lo que se quiere medir. Se le da igual a los TRES brazos.
    """
    vistos, lineas = set(), []
    for pagina in tarea.get("testcode") or []:
        for fn in pagina.get("function", []):
            for par in fn.get("parameter", []):
                nombre = par.get("name", "")
                if nombre in vistos or nombre == "test_url":
                    continue
                vistos.add(nombre)
                lineas.append(f"  {nombre}: {par.get('description', '')}")
    return "\n".join(lineas)


def _prompt_pieza(tarea: dict, pieza: dict, contrato: str, ya_escrito: str = "") -> str:
    es_html = pieza["path"].endswith(".html")
    marca = "html" if es_html else "python"
    que = ("Escribe la plantilla `{}` completa, reemplazando el comentario por el "
           "contenido real.").format(pieza["path"]) if es_html else (
          "Escribe el archivo `{}` completo, respetando las firmas y los "
          "docstrings del esqueleto:").format(pieza["path"])
    partes = [
        f"Proyecto: {tarea['nl_prompt']}",
        "",
        "Requisitos:",
        str(tarea["nl_checklist"]),
        "",
        que,
        f"```{marca}",
        pieza["code"],
        "```",
    ]
    elementos = _elementos_esperados(tarea)
    if elementos:
        partes += ["", "La interfaz tiene que exponer estos elementos, con estos "
                       "ids exactos:", elementos]
    if contrato:
        partes += ["", "Los otros archivos del proyecto exponen esto "
                       "(respetá estos nombres exactos):", contrato]
    if ya_escrito:
        partes += ["", "Ya se escribieron estos archivos:", ya_escrito]
    return "\n".join(partes)


def _contrato(piezas: list[dict], salvo: str) -> str:
    trozos = []
    for p in piezas:
        if p["path"] == salvo or p["path"].endswith(".html"):
            continue
        f = firmas_de(p["code"])
        if f:
            trozos.append(f"# {p['path']}\n{f}")
    plantillas = [p["path"] for p in piezas if p["path"].endswith(".html") and p["path"] != salvo]
    if plantillas:
        trozos.append("# plantillas del proyecto:\n" +
                      "\n".join(f"#   {x}" for x in plantillas))
    return "\n".join(trozos)


def brazo_monolito(tarea: dict, piezas: list[dict]) -> tuple[dict, dict]:
    # Con UNA sola pieza, pedir "escribe los 1 archivos, cada uno precedido por
    # su marca" confunde: medido el 12/09, el modelo contesto `urls.py` cuando
    # se le pedia `views.py`. Con una pieza, monolito ES pedir esa pieza.
    if len(piezas) == 1:
        texto, seg, toks = pedir(_prompt_pieza(tarea, piezas[0], ""), _sistema_de(piezas[0], tarea))
        return {piezas[0]["path"]: solo_codigo(texto)}, {
            "segundos": seg, "tokens": toks, "llamadas": 1}
    cuerpo = "\n\n".join(f"# ── {p['path']} ──\n```python\n{p['code']}\n```" for p in piezas)
    rutas = "\n".join(f"  - {p['path']}" for p in piezas)
    prompt = (f"Proyecto: {tarea['nl_prompt']}\n\nRequisitos:\n{tarea['nl_checklist']}\n\n"
              f"Escribe COMPLETOS estos {len(piezas)} archivos, y ninguno mas:\n{rutas}\n\n"
              f"Formato de respuesta: un bloque ```python por archivo, y como PRIMERA "
              f"linea dentro de cada bloque, el comentario `# ARCHIVO: <ruta>` con la "
              f"ruta exacta de la lista.\n\n{cuerpo}")
    texto, seg, toks = pedir(prompt, _sistema_de(piezas[0], tarea))
    escritos = _partir_por_archivo(texto, piezas)
    return escritos, {"segundos": seg, "tokens": toks, "llamadas": 1}


def brazo_secuencial(tarea: dict, piezas: list[dict]) -> tuple[dict, dict]:
    escritos, seg_tot, toks_tot, acumulado = {}, 0.0, 0, ""
    for p in piezas:
        prompt = _prompt_pieza(tarea, p, _contrato(piezas, p["path"]), acumulado)
        texto, seg, toks = pedir(prompt, _sistema_de(p, tarea))
        codigo = solo_codigo(texto)
        escritos[p["path"]] = codigo
        acumulado += f"\n# {p['path']}\n{codigo}\n"
        seg_tot += seg
        toks_tot += toks
    return escritos, {"segundos": seg_tot, "tokens": toks_tot, "llamadas": len(piezas)}


def brazo_paralelo(tarea: dict, piezas: list[dict]) -> tuple[dict, dict]:
    prompts = [(p, _prompt_pieza(tarea, p, _contrato(piezas, p["path"]))) for p in piezas]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=TRABAJADORES) as pool:
        salidas = list(pool.map(lambda par: pedir(par[1], _sistema_de(par[0], tarea)), prompts))
    pared = time.time() - t0
    escritos = {p["path"]: solo_codigo(t) for (p, _), (t, _s, _k) in zip(prompts, salidas)}
    return escritos, {"segundos": pared, "tokens": sum(k for _t, _s, k in salidas),
                      "llamadas": len(piezas)}


def _partir_por_archivo(texto: str, piezas: list[dict]) -> dict:
    """Del monolito: separa la respuesta en archivos por la marca `# ARCHIVO:`.

    Si el modelo no la respeta, cae a repartir los bloques ``` en orden. Un
    reparto por orden puede asignar mal, y eso se registra como fallo del modelo:
    no seguir el formato pedido ES parte de lo que se mide.
    """
    escritos = {}
    # La marca puede venir ANTES del bloque o como primera linea DENTRO de el:
    # medido el 12/09, el modelo la pone dentro. Se buscan primero los bloques
    # y se mira si cada uno se declara a si mismo.
    for bloque in _RE_BLOQUE.findall(texto):
        m = re.match(r"\s*#\s*ARCHIVO:\s*(\S+)\s*\n", bloque)
        if m:
            escritos[m.group(1).strip()] = bloque[m.end():].strip()
    if escritos:
        return escritos
    marcas = re.split(r"^#\s*ARCHIVO:\s*(\S+)\s*$", texto, flags=re.M)
    if len(marcas) > 1:
        for i in range(1, len(marcas), 2):
            escritos[marcas[i].strip()] = solo_codigo(marcas[i + 1])
        return escritos
    bloques = _RE_BLOQUE.findall(texto)
    for p, b in zip(piezas, bloques):
        escritos[p["path"]] = b.strip()
    return escritos


BRAZOS_FN = {"monolito": brazo_monolito,
             "secuencial": brazo_secuencial,
             "paralelo": brazo_paralelo}


# ─── Construccion de la respuesta que el juez espera ────────────────────────────

def armar_respuesta(tarea: dict, escritos: dict) -> list[dict]:
    """El proyecto completo: lo que escribio el modelo + el andamiaje del esqueleto."""
    fuera = []
    for f in tarea["skeleton"]:
        codigo = escritos.get(f["path"], f["code"])
        fuera.append({"file": f["file"], "path": f["path"], "code": codigo})
    return fuera


def pedir_parametros(tarea: dict, respuesta: list[dict]) -> list:
    """Los IDs de HTML y URLs que el modelo dice haber usado.

    El juez los necesita para manejar el proyecto con Selenium, y los busca POR
    NOMBRE de pagina y de funcion. La estructura exacta que espera es:

        [{"page": ..., "function": [{"function": ...,
          "parameter": [{"name": ..., "answer": ...}]}]}]

    LA ESTRUCTURA NO SE LE PIDE AL MODELO. Se copia del `testcode` de la tarea,
    que ya la trae, y del modelo se piden SOLO los valores. Pedirsela entera
    salio mal el 12/09: devolvio algo parecido pero no igual --un objeto donde
    iba una lista, y `parameter` como diccionario en vez de lista de pares-- y
    el juez no encontro un solo parametro. Los tres brazos dieron identico
    (4/48) porque nunca se llego a probar nada: era el instrumento, no el
    modelo.
    """
    plan = tarea.get("testcode") or []
    pedidos = []
    for pagina in plan:
        for fn in pagina.get("function", []):
            for par in fn.get("parameter", []):
                pedidos.append((pagina["page"], fn["function"], par["name"],
                                par.get("description", "")))
    if not pedidos:
        return []

    codigo = "\n\n".join(f"# {f['path']}\n{f['code']}" for f in respuesta
                         if f["path"].endswith((".py", ".html")))
    listado = "\n".join(f'  "{pg}||{fu}||{nm}": <{desc}>' for pg, fu, nm, desc in pedidos)
    prompt = ("Este es el proyecto que escribiste:\n\n"
              f"{codigo[:12000]}\n\n"
              "Completá este JSON con los valores REALES de tu implementación. "
              "Las URLs empiezan con http://localhost:8000 y los ids de elementos "
              "HTML tienen que ser los que escribiste en las plantillas.\n\n"
              "{\n" + listado + "\n}\n\n"
              "Respondé SOLO el JSON, con las mismas claves y los valores reemplazados.")
    texto, _seg, _toks = pedir(prompt)
    try:
        m = re.search(r"\{.*\}", texto, re.S)
        valores = json.loads(m.group(0)) if m else {}
    except Exception:
        valores = {}

    # La estructura se construye aqui, no la trae el modelo: asi nunca sale malformada.
    fuera = []
    for pagina in plan:
        funciones = []
        for fn in pagina.get("function", []):
            pars = []
            for par in fn.get("parameter", []):
                clave = f"{pagina['page']}||{fn['function']}||{par['name']}"
                pars.append({"name": par["name"],
                             "answer": str(valores.get(clave, "")).strip()})
            funciones.append({"function": fn["function"], "parameter": pars})
        fuera.append({"page": pagina["page"], "function": funciones})
    return fuera


def guardar(brazo: str, rep: int, codigos: dict, parametros: dict) -> Path:
    """Escribe en la jerarquia EXACTA que exige run_judge.py.

        <experiments>/<etiqueta>-<rep>/<brazo>/direct/<brazo>_<ts>_level_1.json
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = SALIDA / f"{ETIQUETA}-{rep}" / brazo / "direct"
    d.mkdir(parents=True, exist_ok=True)
    base = d / f"{brazo}_{ts}_level_1"
    base.with_suffix(".json").write_text(
        json.dumps(codigos, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(f"{base}_parameter.json").write_text(
        json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    return base.with_suffix(".json")


# ─── Diagnostico propio: integra o no ────────────────────────────────────────

def revisar_integracion(tarea: dict, escritos: dict, piezas: list[dict]) -> list[str]:
    """Fallos que se ven SIN iniciar el proyecto. Complementa al juez, no lo reemplaza.

    Sirve para separar "la pieza esta mal" de "las piezas no encajan", que es la
    pregunta del experimento. El veredicto de acierto lo da el juez de
    ProjectEval con Selenium; esto explica POR QUE fallo.
    """
    fallos = []
    for p in piezas:
        if p["path"] not in escritos:
            # NO ENTREGADA. Hay que mirarlo aparte: `armar_respuesta` copia el
            # esqueleto cuando falta un archivo, y como el esqueleto trae las
            # firmas correctas, la omision pasaria por buena. Medido el 12/09
            # con `manage.py`.
            fallos.append(f"{p['path']}: NO ENTREGADA")
            continue
        codigo = escritos.get(p["path"], "")
        if not codigo.strip():
            fallos.append(f"{p['path']}: vacio")
            continue
        if p["path"].endswith(".html"):
            if "<!--" in codigo and len(re.sub(r"<!--.*?-->", "", codigo, flags=re.S).strip()) < 120:
                fallos.append(f"{p['path']}: sigue siendo la cascara del esqueleto")
            continue
        try:
            ast.parse(codigo)
        except SyntaxError as e:
            fallos.append(f"{p['path']}: SyntaxError linea {e.lineno}")
            continue
        esperadas = set(firmas_de(p["code"]).splitlines())
        obtenidas = set(firmas_de(codigo).splitlines())
        faltan = esperadas - obtenidas
        if faltan:
            fallos.append(f"{p['path']}: faltan {len(faltan)} firmas -> "
                          f"{sorted(faltan)[:3]}")
    # imports cruzados: que lo que un archivo importa de otro exista de verdad
    definidos = {}
    for ruta, codigo in escritos.items():
        definidos[Path(ruta).stem] = set(
            re.findall(r"^\s*(?:def|class)\s+(\w+)", codigo, re.M))
    for ruta, codigo in escritos.items():
        for mod, nombres in re.findall(r"^from\s+\.(\w+)\s+import\s+([^\n(]+)", codigo, re.M):
            if mod not in definidos:
                continue
            for n in (x.strip() for x in nombres.split(",")):
                if n and n not in definidos[mod]:
                    fallos.append(f"{ruta}: importa {n} de .{mod}, que no lo define")
    return fallos


# ─── Ejecucion ─────────────────────────────────────────────────────────────────

def correr() -> int:
    tareas = cargar_tareas()
    porid = {t["project_id"]: t for t in tareas}
    if TAREAS:
        elegidas = [porid[i] for i in TAREAS if i in porid]
    else:
        # Las mas pequeñas NO sirven: la tarea 3 tiene UNA pieza y no hay nada
        # que repartir. Se piden las que tengan al menos 3, empezando por las
        # mas baratas de esas.
        web = [t for t in tareas if t["project_type"] == "website"]
        conreparto = [t for t in web if len(piezas_de(t)) >= 3]
        elegidas = sorted(conreparto, key=lambda t: len(piezas_de(t)))[:4]
    print(f"tareas: {[t['project_id'] for t in elegidas]}   brazos: {BRAZOS}   "
          f"repeticiones: {REPES}   trabajadores: {TRABAJADORES}")

    filas = []
    for rep in range(1, REPES + 1):
        for brazo in BRAZOS:
            codigos, parametros = {}, {}
            for t in elegidas:
                piezas = piezas_de(t)
                escritos, medida = BRAZOS_FN[brazo](t, piezas)
                respuesta = armar_respuesta(t, escritos)
                codigos[t["project_id"]] = respuesta
                parametros[t["project_id"]] = pedir_parametros(t, respuesta)
                fallos = revisar_integracion(t, escritos, piezas)
                filas.append({"rep": rep, "brazo": brazo, "tarea": t["project_id"],
                              "piezas": len(piezas), "fallos": fallos, **medida})
                print(f"  r{rep} {brazo:<10} tarea {t['project_id']:>2}  "
                      f"{len(piezas)} piezas  {medida['segundos']:>6.1f}s  "
                      f"{medida['tokens']:>5} tok  "
                      f"{'OK' if not fallos else f'{len(fallos)} fallos: {fallos[0][:60]}'}",
                      flush=True)
            ruta = guardar(brazo, rep, codigos, parametros)
            print(f"  -> {ruta.relative_to(SALIDA.parent)}")

    resumen(filas)
    destino = RAIZ / "pruebas" / "resultados" / "resultado_reparto_proyecto.json"
    destino.write_text(json.dumps({"filas": filas}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"\ndetalle -> {destino.relative_to(RAIZ)}")
    print(f"juicio   -> cd {BANCO} && python run_judge.py -r "
          f"'[{', '.join(repr(f'{ETIQUETA}-{r}') for r in range(1, REPES + 1))}]'")
    return 0


def resumen(filas: list[dict]) -> None:
    print()
    print(f"{'brazo':<12} {'segundos':>9} {'tokens':>8} {'llamadas':>9} "
          f"{'con fallos':>11} {'de':>4}")
    for brazo in BRAZOS:
        f = [x for x in filas if x["brazo"] == brazo]
        if not f:
            continue
        malas = sum(1 for x in f if x["fallos"])
        print(f"{brazo:<12} {sum(x['segundos'] for x in f):>9.1f} "
              f"{sum(x['tokens'] for x in f):>8} {sum(x['llamadas'] for x in f):>9} "
              f"{malas:>11} {len(f):>4}")
    print("\nOJO: 'con fallos' es el diagnostico propio (sintaxis, firmas, imports),")
    print("NO el acierto. El acierto lo da run_judge.py levantando el proyecto.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--humo", action="store_true",
                    help="una tarea, una repeticion, solo el brazo monolito")
    args = ap.parse_args()
    if args.humo:
        BRAZOS = ["monolito"]
        REPES = 1
        if not TAREAS:
            _t = cargar_tareas()
            _web = [x for x in _t if x["project_type"] == "website"
                    and len(piezas_de(x)) >= 3]
            TAREAS = [min(_web, key=lambda x: len(piezas_de(x)))["project_id"]]
    sys.exit(correr())
