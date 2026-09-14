#!/usr/bin/env python3
"""eval_edicion.py - ¿Sabe MODIFICAR codigo que ya existe?

POR QUE EXISTE (08/09/2026)

`eval_expertos` mide funciones escritas DESDE CERO (fizzbuzz, palindromo,
busqueda binaria): autocontenidas, 5-20 lineas, nivel ejercicio de entrevista.
`eval_scripts` se acerca -- un script operativo ejecutado de verdad -- pero son
4 tareas. Ninguno mide lo que un servidor MCP le va a pedir a un modelo local:
leer codigo que ya existe, encontrar el lugar correcto, cambiarlo sin romper
nada, y hacerlo coherente cuando el cambio toca mas de un archivo.

El hueco lo marco el usuario preguntando si los tests eran lo bastante dificiles
como para decir que un modelo sirve para programar. No lo eran.

QUE LO HACE DIFICIL, y por que cada cosa

  ARCHIVOS LARGOS (~200 lineas, ~20 funciones). La primera version usaba
  archivos de 10-15 lineas: el modelo veia la funcion objetivo de inmediato y
  no se medaa si sabe ENCONTRARLA. Con 20 funciones de relleno realista, hay
  que ubicar el lugar antes de tocarlo, que es lo que pasa en un proyecto real.

  VARIOS ARCHIVOS. Un cambio coherente que toca dos o tres modulos: agregar un
  campo y manejarlo donde se consume, mover una constante y actualizar a los
  que la usaban. Es lo que mas se parece a trabajar en un repo y lo que ningun
  banco anterior tocaba.

  DOS JUEGOS DE TESTS por tarea:
    REGRESION  pasan ANTES. Si el modelo reescribe el archivo, inventa, o
               rompe algo que funcionaba, fallan. Es el ANTI-FABRICACION: el 07/09
               un modelo entrego un archivo con formato perfecto y contenido
               inventado, y solo se detecto comparando a mano contra la fuente.
               Aqui se detecta solo.
    CAMBIO     fallan ANTES, tienen que pasar DESPUES.

  Una tarea acierta SOLO si pasan los dos juegos. Pasar el cambio rompiendo la
  regresion no es medio acierto: es peor que no hacer nada, porque mete un bug
  silencioso.

Oraculo puro por EJECUCION: no opina ningun modelo.

    uso: eval_edicion.py [PUERTO] [ETIQUETA] [REPES]
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8080"
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "modelo"
REPES = int(sys.argv[3]) if len(sys.argv) > 3 else 1
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
MAX_TOKENS = int(os.getenv("BANCO_EDICION_MAX_TOKENS", "4000"))
TIMEOUT = int(os.getenv("BANCO_EDICION_TIMEOUT", "420"))
SOLO = os.getenv("BANCO_EDICION_SOLO", "")   # ejecutar una sola tarea, por id

INSTRUCCION = (
    "Vas a modificar codigo Python que ya existe. Respondes SOLO con los "
    "archivos que cambian, COMPLETOS, cada uno en su propio bloque asi:\n\n"
    "```python\n# archivo: nombre.py\n<contenido completo del archivo>\n```\n\n"
    "Sin explicaciones. Conserva TODO lo que no haga falta cambiar: el resto "
    "del codigo tiene que seguir funcionando exactamente igual."
)

# ── Relleno realista para engordar los archivos ──────────────────────────────
# Semilla fija: todos los modelos ven EXACTAMENTE el mismo archivo. Con relleno
# al azar la comparacion mediria la suerte del relleno, no el modelo.
_RELLENO = [
    ("_normalizar_clave", "    return str(k).strip().lower().replace(' ', '_')"),
    ("_es_vacio", "    return v is None or (isinstance(v, str) and not v.strip())"),
    ("_a_lista", "    return list(v) if isinstance(v, (list, tuple, set)) else [v]"),
    ("_truncar", "    return s if len(s) <= n else s[: n - 1] + '\\u2026'"),
    ("_contar", "    return sum(1 for _ in xs)"),
    ("_primero", "    for x in xs:\n        return x\n    return None"),
    ("_aplanar_uno", "    return [y for x in xs for y in (x if isinstance(x, list) else [x])]"),
    ("_sin_none", "    return [x for x in xs if x is not None]"),
    ("_pares", "    return list(zip(xs, xs[1:]))"),
    ("_indice_de", "    try:\n        return xs.index(v)\n    except ValueError:\n        return -1"),
    ("_mayor", "    return max(xs) if xs else None"),
    ("_menor", "    return min(xs) if xs else None"),
    ("_unicos", "    vistos = []\n    for x in xs:\n        if x not in vistos:\n            vistos.append(x)\n    return vistos"),
    ("_particionar", "    return [x for x in xs if p(x)], [x for x in xs if not p(x)]"),
    ("_agrupar_por_len", "    d = {}\n    for s in xs:\n        d.setdefault(len(s), []).append(s)\n    return d"),
    ("_invertir_dict", "    return {v: k for k, v in d.items()}"),
    ("_fusionar", "    r = dict(a)\n    r.update(b)\n    return r"),
    ("_solo_claves", "    return {k: v for k, v in d.items() if k in ks}"),
    ("_ordenar_por", "    return sorted(xs, key=f)"),
    ("_repetir", "    return [x for x in xs for _ in range(n)]"),
]
_FIRMA = "(xs=(), d=None, k='', v=None, s='', n=0, a=None, b=None, p=bool, f=str, **kw):"


def _engordar(nucleo: str, semilla: int, cuantas: int = 20) -> str:
    """Mete `cuantas` funciones de relleno alrededor del nucleo.

    El nucleo NO va ni primero ni ultimo: si cayera siempre en un extremo,
    encontrarlo seria trivial y no se mediria la busqueda.
    """
    rnd = random.Random(semilla)
    # Sin sufijo mientras alcancen los nombres distintos: los asserts de
    # regresion llaman a estas funciones por su nombre, y un `_truncar_0`
    # inesperado rompia 8 de 13 tareas -- el banco se autoverifica justamente
    # para que eso no llegue a medirse como fallo del modelo.
    if cuantas <= len(_RELLENO):
        relleno = list(_RELLENO[:cuantas])
    else:
        relleno = [(f"{n}_{i}", c) for i in range((cuantas // len(_RELLENO)) + 1)
                   for n, c in _RELLENO][:cuantas]
    rnd.shuffle(relleno)
    corte = rnd.randrange(3, max(4, len(relleno) - 3))
    partes = ['"""Utilidades internas del modulo."""', ""]
    for n, c in relleno[:corte]:
        partes += [f"def {n}{_FIRMA}", c, ""]
    partes += [nucleo.strip(), ""]
    for n, c in relleno[corte:]:
        partes += [f"def {n}{_FIRMA}", c, ""]
    return "\n".join(partes)


# ── Tareas ───────────────────────────────────────────────────────────────────
# `archivos` es {nombre: fuente}. `regresion` y `cambio` son fragmentos que se
# ejecutan con el paquete ya importable; el modulo principal entra como `m`.

def _t(id_, pedido, archivos, regresion, cambio, largo=True, semilla=7):
    if largo and len(archivos) == 1:
        (n, src), = archivos.items()
        archivos = {n: _engordar(src, semilla)}
    return {"id": id_, "pedido": pedido, "archivos": archivos,
            "regresion": regresion, "cambio": cambio}


TAREAS = [
    _t("agregar_caso",
       "Agrega el sufijo 'TB' (terabytes, 1024 GB) a `formatear_tamano`, "
       "siguiendo el mismo patron que los demas.",
       {"m.py": '''
def formatear_tamano(bytes_):
    """Devuelve el tamano legible: 1536 -> '1.5 KB'."""
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 ** 2:
        return f"{bytes_ / 1024:.1f} KB"
    if bytes_ < 1024 ** 3:
        return f"{bytes_ / 1024 ** 2:.1f} MB"
    return f"{bytes_ / 1024 ** 3:.1f} GB"
'''},
       ["assert m.formatear_tamano(512) == '512 B'",
        "assert m.formatear_tamano(1536) == '1.5 KB'",
        "assert m._truncar(s='abcdef', n=4) == 'abc\\u2026'"],
       ["assert m.formatear_tamano(1024**4) == '1.0 TB'",
        "assert m.formatear_tamano(1024**3 * 5) == '5.0 GB'"], semilla=11),

    _t("arreglar_bug",
       "`promedio` falla con lista vacia. Haz que devuelva 0.0 en ese caso, "
       "sin cambiar nada mas.",
       {"m.py": '''
def promedio(xs):
    """Promedio de una lista de numeros."""
    return sum(xs) / len(xs)


def mediana(xs):
    """Mediana; para lista par, promedio de los dos del medio."""
    o = sorted(xs)
    n = len(o)
    if n % 2:
        return float(o[n // 2])
    return (o[n // 2 - 1] + o[n // 2]) / 2
'''},
       ["assert m.promedio([1, 2, 3]) == 2.0",
        "assert m.mediana([1, 2, 3, 4]) == 2.5",
        "assert m._unicos([1, 1, 2]) == [1, 2]"],
       ["assert m.promedio([]) == 0.0",
        "assert m.promedio([4, 4]) == 4.0"], semilla=13),

    _t("parametro_opcional",
       "Agrega a `normalizar` un parametro opcional `quitar_espacios` que por "
       "defecto sea False. Si es True, ademas quita TODOS los espacios. Quien ya "
       "llamaba a la funcion no se puede enterar.",
       {"m.py": '''
def normalizar(texto):
    """Minusculas y sin espacios en los extremos."""
    return texto.strip().lower()


def es_igual(a, b):
    """Compara dos textos ya normalizados."""
    return normalizar(a) == normalizar(b)
'''},
       ["assert m.normalizar('  Hola Mundo  ') == 'hola mundo'",
        "assert m.es_igual('Hola', ' hola ') is True",
        "assert m._menor([3, 1, 2]) == 1"],
       ["assert m.normalizar('  Hola Mundo  ', quitar_espacios=True) == 'holamundo'",
        "assert m.normalizar('a b c') == 'a b c'"], semilla=17),

    _t("extender_registro",
       "Agrega al registro la operacion 'potencia' (a elevado a b) y haz que "
       "`aplicar` la acepte. Segui el patron que ya esta.",
       {"m.py": '''
OPERACIONES = {
    "suma": lambda a, b: a + b,
    "resta": lambda a, b: a - b,
    "producto": lambda a, b: a * b,
}


def aplicar(nombre, a, b):
    """Aplica una operacion del registro. Error claro si no existe."""
    if nombre not in OPERACIONES:
        raise ValueError(f"operacion desconocida: {nombre}")
    return OPERACIONES[nombre](a, b)
'''},
       ["assert m.aplicar('suma', 2, 3) == 5",
        "assert m.aplicar('producto', 4, 5) == 20",
        "try:\n    m.aplicar('raiz', 1, 2)\n    raise AssertionError('debia fallar')\nexcept ValueError:\n    pass"],
       ["assert m.aplicar('potencia', 2, 10) == 1024",
        "assert 'potencia' in m.OPERACIONES"], semilla=19),

    _t("manejar_error",
       "`leer_entero` falla si el texto no es un numero. Haz que devuelva "
       "None en ese caso. El resto igual.",
       {"m.py": '''
def leer_entero(texto):
    """Convierte texto a entero."""
    return int(texto.strip())


def sumar_columna(lineas):
    """Suma los enteros de una lista de lineas."""
    return sum(leer_entero(l) for l in lineas)
'''},
       ["assert m.leer_entero(' 42 ') == 42",
        "assert m.sumar_columna(['1', '2', '3']) == 6",
        "assert m._contar([1, 2, 3]) == 3"],
       ["assert m.leer_entero('abc') is None",
        "assert m.leer_entero('7') == 7"], semilla=23),

    _t("dos_lugares",
       "El separador ',' esta escrito a mano en `partir` y en `unir`. Sacalo a "
       "una constante SEPARADOR y usala en las dos. El comportamiento no cambia.",
       {"m.py": '''
def partir(linea):
    """Parte una linea CSV simple."""
    return [c.strip() for c in linea.split(",")]


def unir(campos):
    """Une campos en una linea CSV simple."""
    return ",".join(str(c) for c in campos)
'''},
       ["assert m.partir('a, b ,c') == ['a', 'b', 'c']",
        "assert m.unir(['a', 'b', 'c']) == 'a,b,c'",
        "assert m.partir(m.unir(['x', 'y'])) == ['x', 'y']"],
       ["assert hasattr(m, 'SEPARADOR') and m.SEPARADOR == ','"], semilla=29),

    _t("filtrar_lista",
       "`filtrar` devuelve los elementos que cumplen el predicado. Agregale un "
       "parametro opcional `limite` que, si viene, corta el resultado a esa "
       "cantidad. Por defecto no corta.",
       {"m.py": '''
def filtrar(xs, pred):
    """Los elementos que cumplen el predicado."""
    return [x for x in xs if pred(x)]


def contar_si(xs, pred):
    """Cuantos cumplen el predicado."""
    return len(filtrar(xs, pred))
'''},
       ["assert m.filtrar([1,2,3,4], lambda x: x % 2 == 0) == [2, 4]",
        "assert m.contar_si([1,2,3,4], lambda x: x > 2) == 2",
        "assert m._sin_none([1, None, 2]) == [1, 2]"],
       ["assert m.filtrar([1,2,3,4,5,6], lambda x: x % 2 == 0, limite=2) == [2, 4]",
        "assert m.filtrar([2,4,6], lambda x: True) == [2, 4, 6]"], semilla=31),

    _t("cambiar_orden",
       "`listar` devuelve las claves en el orden del diccionario. Haz que las "
       "devuelva ORDENADAS alfabeticamente. Nada mas cambia.",
       {"m.py": '''
def listar(d):
    """Las claves del diccionario."""
    return list(d.keys())


def valores_de(d, claves):
    """Los valores de esas claves, salteando las que no estan."""
    return [d[k] for k in claves if k in d]
'''},
       ["assert m.valores_de({'a': 1, 'b': 2}, ['b', 'z', 'a']) == [2, 1]",
        "assert m._fusionar(a={'a': 1}, b={'b': 2}) == {'a': 1, 'b': 2}"],
       ["assert m.listar({'c': 1, 'a': 2, 'b': 3}) == ['a', 'b', 'c']",
        "assert m.listar({}) == []"], semilla=37),

    _t("validar_entrada",
       "`dividir` no controla el divisor cero. Haz que lance "
       "ValueError('division por cero') en ese caso.",
       {"m.py": '''
def dividir(a, b):
    """Division real."""
    return a / b


def porcentaje(parte, total):
    """Que porcentaje representa la parte."""
    return dividir(parte, total) * 100
'''},
       ["assert m.dividir(10, 4) == 2.5",
        "assert m.porcentaje(25, 200) == 12.5",
        "assert m._mayor([1, 9, 3]) == 9"],
       ["try:\n    m.dividir(1, 0)\n    raise AssertionError('debia fallar')\nexcept ValueError as e:\n    assert 'cero' in str(e).lower()"],
       semilla=41),

    _t("acumular_estado",
       "`Contador` no tiene forma de reiniciarse. Agregale un metodo `reiniciar()` "
       "que ponga la cuenta en cero.",
       {"m.py": '''
class Contador:
    """Cuenta cuantas veces se llamo."""

    def __init__(self):
        self.cuenta = 0

    def sumar(self, n=1):
        self.cuenta += n
        return self.cuenta
'''},
       ["c = m.Contador()\nassert c.sumar() == 1\nassert c.sumar(4) == 5",
        "assert m._pares([1, 2, 3]) == [(1, 2), (2, 3)]"],
       ["c = m.Contador()\nc.sumar(9)\nc.reiniciar()\nassert c.cuenta == 0\nassert c.sumar() == 1"],
       semilla=43),

    # ── Varios archivos ─────────────────────────────────────────────────────
    {
        "id": "multi_constante",
        "pedido": "El tope 100 esta escrito a mano en `limites.py` y repetido en "
                  "`servicio.py`. Dejalo definido UNA sola vez en limites.py como "
                  "TOPE y que servicio.py lo importe de ahi.",
        "archivos": {
            "limites.py": '"""Limites del sistema."""\n\n\ndef dentro_de_tope(n):\n    """True si n no pasa el tope."""\n    return n <= 100\n',
            "m.py": '"""Servicio."""\nimport limites\n\n\ndef aceptar(pedidos):\n    """Acepta hasta el tope; el resto se rechaza."""\n    return [p for p in pedidos if p <= 100]\n\n\ndef resumen(pedidos):\n    return {"aceptados": len(aceptar(pedidos)), "tope_ok": limites.dentro_de_tope(len(pedidos))}\n',
        },
        "regresion": [
            "assert m.aceptar([50, 100, 101]) == [50, 100]",
            "import limites\nassert limites.dentro_de_tope(100) is True",
            "assert m.resumen([1, 2])['aceptados'] == 2",
        ],
        "cambio": [
            "import limites\nassert hasattr(limites, 'TOPE') and limites.TOPE == 100",
            "import inspect, limites\nassert '100' not in inspect.getsource(m.aceptar), 'quedo el 100 a mano en servicio'",
        ],
    },
    {
        "id": "multi_campo",
        "pedido": "Agrega el campo `activo` (booleano, por defecto True) a la clase "
                  "`Usuario` de `modelo.py`, y haz que `formatear` en m.py lo "
                  "muestre al final como ' [inactivo]' cuando sea False. Si esta "
                  "activo, el texto no cambia.",
        "archivos": {
            "modelo.py": '"""Modelo de datos."""\n\n\nclass Usuario:\n    def __init__(self, nombre, edad):\n        self.nombre = nombre\n        self.edad = edad\n',
            "m.py": '"""Presentacion."""\nfrom modelo import Usuario\n\n\ndef formatear(u):\n    """Texto legible del usuario."""\n    return f"{u.nombre} ({u.edad})"\n\n\ndef listar(us):\n    return [formatear(u) for u in us]\n',
        },
        "regresion": [
            "from modelo import Usuario\nassert m.formatear(Usuario('Ana', 30)) == 'Ana (30)'",
            "from modelo import Usuario\nassert m.listar([Usuario('B', 1)]) == ['B (1)']",
        ],
        "cambio": [
            "from modelo import Usuario\nu = Usuario('Ana', 30)\nassert u.activo is True",
            "from modelo import Usuario\nu = Usuario('Ana', 30)\nu.activo = False\nassert m.formatear(u) == 'Ana (30) [inactivo]'",
        ],
    },
    {
        "id": "multi_renombrar",
        "pedido": "La funcion `calc` de `nucleo.py` tiene un nombre malo. Renombrala "
                  "a `calcular_total` y actualiza a todos los que la llaman.",
        "archivos": {
            "nucleo.py": '"""Nucleo de calculo."""\n\n\ndef calc(items):\n    """Suma los precios."""\n    return sum(i["precio"] for i in items)\n',
            "m.py": '"""Fachada."""\nimport nucleo\n\n\ndef total_carrito(items):\n    return nucleo.calc(items)\n\n\ndef total_con_iva(items, iva=0.21):\n    return nucleo.calc(items) * (1 + iva)\n',
        },
        "regresion": [
            "assert m.total_carrito([{'precio': 10}, {'precio': 5}]) == 15",
            "assert abs(m.total_con_iva([{'precio': 100}]) - 121.0) < 0.001",
        ],
        "cambio": [
            "import nucleo\nassert hasattr(nucleo, 'calcular_total')",
            "import nucleo\nassert not hasattr(nucleo, 'calc'), 'quedo el nombre viejo'",
        ],
    },
]


def _pedir(prompt: str) -> tuple[str, float]:
    cuerpo = json.dumps({
        "model": "local", "stream": False, "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read())
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "", time.time() - t0


def _archivos_de(texto: str, originales: dict) -> dict:
    """Extrae los archivos de la respuesta.

    Se aceptan tres formas, de mas a menos explicita, porque penalizar el
    formato mediria obediencia y no capacidad de editar:
      1. bloques con `# archivo: nombre.py`
      2. un solo bloque cuando la tarea toca un solo archivo
      3. el texto crudo cuando no vino en bloque
    """
    salida = dict(originales)
    bloques = re.findall(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    if not bloques:
        bloques = [texto]
    nombrados = 0
    for b in bloques:
        mm = re.match(r"\s*#\s*archivo:\s*([\w./-]+)\s*\n(.*)", b, re.S)
        if mm and mm.group(1) in salida:
            salida[mm.group(1)] = mm.group(2)
            nombrados += 1
    if not nombrados and len(originales) == 1:
        (n,) = originales
        salida[n] = bloques[0]
    return salida


def _correr(archivos: dict, asserts: list[str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as d:
        for n, src in archivos.items():
            (Path(d) / n).write_text(src)
        pasaron, err = 0, ""
        for a in asserts:
            script = f"import sys\nsys.path.insert(0, {d!r})\nimport m\n{a}\n"
            try:
                r = subprocess.run([sys.executable, "-c", script],
                                   capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                if not err:
                    err = "timeout"
                continue
            if r.returncode == 0:
                pasaron += 1
            elif not err:
                ls = (r.stderr or "").strip().splitlines()
                err = ls[-1][:90] if ls else "fallo sin mensaje"
        return pasaron, err


def main() -> int:
    tareas = [t for t in TAREAS if not SOLO or t["id"] == SOLO]
    print(f"\n{'='*70}\n  EDICION DE CODIGO EXISTENTE: {ETIQUETA}  (puerto {PUERTO})\n{'='*70}")
    n_multi = sum(1 for t in tareas if len(t["archivos"]) > 1)
    largos = [len(s.splitlines()) for t in tareas for s in t["archivos"].values()]
    print(f"  {len(tareas)} tareas · {n_multi} tocan varios archivos · "
          f"archivo mas largo {max(largos)} lineas")
    print("  Acierta SOLO si pasan REGRESION y CAMBIO.\n")

    total = aciertos = rompio = 0
    for _ in range(REPES):
        for t in tareas:
            total += 1
            pre_r, _ = _correr(t["archivos"], t["regresion"])
            pre_c, _ = _correr(t["archivos"], t["cambio"])
            if pre_r != len(t["regresion"]) or pre_c == len(t["cambio"]):
                print(f"  BANCO MAL  {t['id']:<20} reg {pre_r}/{len(t['regresion'])} "
                      f"· cambio ya pasa {pre_c}/{len(t['cambio'])}")
                continue

            partes = "\n\n".join(
                f"Archivo `{n}`:\n```python\n{s.strip()}\n```"
                for n, s in t["archivos"].items())
            prompt = f"{INSTRUCCION}\n\n{partes}\n\nCambio pedido: {t['pedido']}"
            try:
                salida, seg = _pedir(prompt)
            except Exception as e:
                print(f"  ERROR      {t['id']:<20} {type(e).__name__}")
                continue

            nuevos = _archivos_de(salida, t["archivos"])
            reg, er = _correr(nuevos, t["regresion"])
            cam, ec = _correr(nuevos, t["cambio"])
            ok = reg == len(t["regresion"]) and cam == len(t["cambio"])
            aciertos += ok
            if reg < len(t["regresion"]):
                rompio += 1
            det = "" if ok else (f"ROMPIO LO QUE ANDABA: {er}" if reg < len(t["regresion"])
                                 else f"no hizo el cambio: {ec}")
            print(f"  {'PASA ' if ok else 'FALLA'}      {t['id']:<20} "
                  f"reg {reg}/{len(t['regresion'])} · cam {cam}/{len(t['cambio'])} "
                  f"· {seg:>3.0f}s  {det[:58]}")

    print(f"\n  EDICION: {aciertos}/{total}   (rompieron la regresion: {rompio})\n")
    Path("pruebas/resultados").mkdir(parents=True, exist_ok=True)
    Path(f"pruebas/resultados/resultado_edicion_{ETIQUETA}.json").write_text(
        json.dumps({"etiqueta": ETIQUETA, "aciertos": aciertos,
                    "total": total, "rompieron_regresion": rompio}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
