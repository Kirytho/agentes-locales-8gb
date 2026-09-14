#!/usr/bin/env python3
"""eval_formato_edicion.py - ¿Puede el modelo editar con bloques SEARCH/REPLACE?

POR QUE EXISTE (09/09/2026)

El servidor MCP le pide al modelo el ARCHIVO ENTERO reescrito. Es lo mas facil
de cumplir -- Aider llama a ese formato `whole` y se lo pone por defecto a los
modelos poco conocidos por la misma razon -- pero tiene un costo que estamos
pagando: el archivo entra DOS veces en el contexto del modelo (lo lee y lo
reescribe), y de ahi sale el cupo de ~12.000 caracteres, es decir ~300 lineas.
Medido: 22 de los 103 .py del proyecto no entran.

Con bloques SEARCH/REPLACE el modelo emite solo el trozo que cambia, y el techo
se inicia. La pregunta es si un modelo de 7B los emite BIEN. Aider mide
exactamente eso con "percent using correct edit format", y su hallazgo es que
los modelos pequeños fallan seguido -- por eso el default. Nunca se midio con
K2-Horizon, asi que no se sabe.

QUE SE MIDE, por tarea y por formato

  formato   la respuesta trajo algo parseable en el formato pedido
  aplica    los bloques se pudieron aplicar: cada SEARCH aparece EXACTAMENTE
            una vez en el archivo. Dos apariciones es ambiguo y se rechaza --
            aplicar la primera seria adivinar.
  pasa      el archivo resultante pasa REGRESION y CAMBIO (el mismo oraculo
            de eval_edicion: no opina ningun modelo)
  chars     cuanto texto genero, que es el ahorro que se le atribuye al formato

CONTROL: cada tarea se ejecuta TAMBIEN con archivo entero, alternando el orden.
Sin control no se puede decir si bloques es mejor o peor, solo si funciona.

    uso:  eval_formato_edicion.py [repeticiones]
          EVAL_FORMATO_PUERTO=8080  EVAL_FORMATO_SOLO=<id_tarea>
          --autotest   verifica el aplicador contra casos hechos a mano
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_edicion import TAREAS, _correr                      # noqa: E402

PUERTO = os.getenv("EVAL_FORMATO_PUERTO", "8080")
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"
SOLO = os.getenv("EVAL_FORMATO_SOLO", "")
MAX_TOKENS = int(os.getenv("EVAL_FORMATO_MAX_TOKENS", "4000"))
TIMEOUT = int(os.getenv("EVAL_FORMATO_TIMEOUT", "300"))
ETIQUETA = os.getenv("EVAL_FORMATO_ETIQUETA", "modelo")

MARCA_INI, MARCA_MED, MARCA_FIN = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"


# ── El formato de bloques ────────────────────────────────────────────────────

def instrucciones_bloques(archivos: dict) -> str:
    lista = ", ".join(f"`{n}`" for n in archivos)
    return (
        "Responde SOLO con bloques de busqueda y reemplazo, sin explicaciones.\n"
        "Cada bloque tiene exactamente esta forma:\n\n"
        f"nombre_archivo.py\n{MARCA_INI}\n"
        "las lineas EXACTAS que hay hoy en el archivo\n"
        f"{MARCA_MED}\n"
        "las lineas que las reemplazan\n"
        f"{MARCA_FIN}\n\n"
        "Reglas:\n"
        f"- El nombre del archivo va en su propia linea, justo antes de {MARCA_INI}."
        f" Los archivos son: {lista}.\n"
        "- Lo que va entre SEARCH y ======= tiene que ser una copia LITERAL de lo\n"
        "  que hay en el archivo, con la misma indentacion, y tiene que aparecer\n"
        "  UNA SOLA VEZ en ese archivo. Si es ambiguo, agrega lineas de contexto.\n"
        "- No reescribas el archivo entero. Solo los trozos que cambian.\n"
        "- Pone tantos bloques como haga falta.\n"
        + (BLOQUE_CHICO if os.getenv("EVAL_FORMATO_PEQUENO") else "")
    )


# Instruccion opcional, para medir si acota el fallo caro. MEDIDO el 09/09/2026
# sobre Spark-X2.5-4B: emite bloques 2,2x mas grandes que K2 (870 contra 395
# chars) y ROMPE LA REGRESION 9 veces sobre 65 contra 3 de K2. Los fallos son
# todos del mismo tipo -- "cannot import name 'TOPE'", "name 'SEPARADOR' is not
# defined", IndentationError -- es decir, el tramo reemplazado se llevo codigo
# que estaba dentro. No es que programe mal: apunta demasiado ancho.
BLOQUE_CHICO = (
    "- Haz cada bloque LO MAS CHICO POSIBLE: solo las lineas que realmente\n"
    "  cambian, mas el minimo contexto para que el SEARCH sea unico. Si tienes\n"
    "  que cambiar una linea dentro de una funcion larga, NO copies la funcion\n"
    "  entera: copia esa linea y una o dos de alrededor. Cuanto mas grande el\n"
    "  bloque, mas facil es borrar sin querer algo que estaba adentro.\n"
)


def parsear_bloques(texto: str, validos: set[str]) -> list[tuple[str, str, str]]:
    """(archivo, buscar, reemplazar) por cada bloque bien formado.

    Se quita el cerco ```...``` si vino, porque envolver la respuesta en un
    bloque de codigo es un habito del modelo y no un error de formato: lo que
    se mide es si sabe emitir SEARCH/REPLACE, no si obedece al pie de la letra.
    """
    texto = re.sub(r"```(?:python|diff)?\s*\n", "", texto).replace("```", "")
    salida = []
    patron = re.compile(
        r"^[ \t]*([\w./-]+\.py)[ \t]*\n[ \t]*" + re.escape(MARCA_INI) +
        r"[ \t]*\n(.*?)\n[ \t]*" + re.escape(MARCA_MED) +
        r"[ \t]*\n(.*?)\n[ \t]*" + re.escape(MARCA_FIN),
        re.S | re.M)
    for nombre, buscar, reemplazar in patron.findall(texto):
        if nombre in validos:
            salida.append((nombre, buscar, reemplazar))
    return salida


def aplicar_bloques(originales: dict, bloques: list) -> tuple[dict | None, str]:
    """Aplica los bloques. (archivos, "") o (None, motivo del rechazo).

    Un SEARCH que aparece dos veces se RECHAZA en vez de aplicarse al primero:
    elegir uno seria adivinar, y un cambio en el lugar equivocado pasa los
    tests del cambio y rompe otra cosa en silencio.
    """
    if not bloques:
        return None, "sin bloques parseables"
    salida = dict(originales)
    for nombre, buscar, reemplazar in bloques:
        cuerpo = salida[nombre]
        if buscar == "":
            salida[nombre] = cuerpo.rstrip() + "\n\n\n" + reemplazar + "\n"
            continue
        n = cuerpo.count(buscar)
        if n == 0:
            # Segunda chance solo con los espacios del borde de cada linea: el
            # modelo copia bien el codigo y a veces mal la sangria de mas.
            flex = "\n".join(l.rstrip() for l in buscar.splitlines())
            cuerpo_flex = "\n".join(l.rstrip() for l in cuerpo.splitlines())
            if cuerpo_flex.count(flex) == 1:
                salida[nombre] = cuerpo_flex.replace(flex, reemplazar, 1)
                continue
            return None, f"SEARCH no esta en {nombre}"
        if n > 1:
            return None, f"SEARCH aparece {n} veces en {nombre}: ambiguo"
        salida[nombre] = cuerpo.replace(buscar, reemplazar, 1)
    return salida, ""


# ── El formato de archivo entero, para comparar ─────────────────────────────

def instrucciones_entero(archivos: dict) -> str:
    return ("Responde SOLO con los archivos que cambian, COMPLETOS, cada uno asi:\n\n"
            "```python\n# archivo: nombre.py\n<contenido completo>\n```\n\n"
            "Sin explicaciones. Conserva TODO lo que no haga falta cambiar.\n")


def parsear_entero(texto: str, originales: dict) -> tuple[dict | None, str]:
    salida = dict(originales)
    bloques = re.findall(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    if not bloques:
        bloques = [texto]
    nombrados = 0
    for b in bloques:
        m = re.match(r"\s*#\s*archivo:\s*([\w./-]+)\s*\n(.*)", b, re.S)
        if m and m.group(1) in salida:
            salida[m.group(1)] = m.group(2)
            nombrados += 1
    if not nombrados:
        if len(originales) != 1:
            return None, "no nombro los archivos y la tarea toca varios"
        (n,) = originales
        salida[n] = bloques[0]
    return salida, ""


# ── Cable ────────────────────────────────────────────────────────────────────

def _pedir(prompt: str) -> tuple[str, float]:
    cuerpo = json.dumps({"model": "local", "stream": False,
                         "max_tokens": MAX_TOKENS,
                         "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(URL, data=cuerpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read())
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return (msg.get("content") or ""), time.time() - t0


def una_corrida(tarea: dict, formato: str) -> dict:
    archivos = tarea["archivos"]
    partes = "\n\n".join(f"Archivo `{n}`:\n```python\n{s.strip()}\n```"
                         for n, s in archivos.items())
    cabecera = (instrucciones_bloques(archivos) if formato == "bloques"
                else instrucciones_entero(archivos))
    prompt = f"{cabecera}\n{partes}\n\nCambio pedido: {tarea['pedido']}"

    try:
        texto, seg = _pedir(prompt)
    except Exception as e:
        return {"formato": False, "aplica": False, "pasa": False, "rompio": False,
                "chars": 0, "seg": 0.0, "motivo": f"{type(e).__name__}: {e}"}

    if formato == "bloques":
        bl = parsear_bloques(texto, set(archivos))
        nuevos, motivo = aplicar_bloques(archivos, bl)
        formato_ok = bool(bl)
    else:
        nuevos, motivo = parsear_entero(texto, archivos)
        formato_ok = nuevos is not None

    if nuevos is None:
        return {"formato": formato_ok, "aplica": False, "pasa": False,
                "rompio": False, "chars": len(texto), "seg": seg, "motivo": motivo}

    reg, err_r = _correr(nuevos, tarea["regresion"])
    cam, _ = _correr(nuevos, tarea["cambio"])
    ok_reg = reg == len(tarea["regresion"])
    ok_cam = cam == len(tarea["cambio"])
    return {"formato": formato_ok, "aplica": True, "pasa": ok_reg and ok_cam,
            "rompio": not ok_reg, "chars": len(texto), "seg": seg,
            "motivo": "" if ok_reg and ok_cam else (f"regresion: {err_r}" if not ok_reg
                                                    else "no hizo el cambio")}


# ── Autotest del aplicador ──────────────────────────────────────────────────

def autotest() -> int:
    """Un aplicador con un bug inventa fallos del modelo. Se verifica primero."""
    orig = {"m.py": "def a():\n    return 1\n\n\ndef b():\n    return 1\n"}
    casos = [
        ("bloque normal",
         f"m.py\n{MARCA_INI}\ndef a():\n    return 1\n{MARCA_MED}\ndef a():\n    return 2\n{MARCA_FIN}",
         lambda r: r and r[0]["m.py"].startswith("def a():\n    return 2")),
        ("SEARCH ambiguo se rechaza",
         f"m.py\n{MARCA_INI}\n    return 1\n{MARCA_MED}\n    return 9\n{MARCA_FIN}",
         lambda r: r[0] is None and "ambiguo" in r[1]),
        ("SEARCH inexistente se rechaza",
         f"m.py\n{MARCA_INI}\ndef zzz():\n    pass\n{MARCA_MED}\ndef zzz():\n    return 1\n{MARCA_FIN}",
         lambda r: r[0] is None and "no esta" in r[1]),
        ("archivo desconocido se ignora",
         f"otro.py\n{MARCA_INI}\ndef a():\n    return 1\n{MARCA_MED}\nx\n{MARCA_FIN}",
         lambda r: r[0] is None and "sin bloques" in r[1]),
        ("envuelto en ``` igual parsea",
         f"```\nm.py\n{MARCA_INI}\ndef b():\n    return 1\n{MARCA_MED}\ndef b():\n    return 3\n{MARCA_FIN}\n```",
         lambda r: r and r[0]["m.py"].endswith("def b():\n    return 3\n")),
        ("dos bloques en una respuesta",
         f"m.py\n{MARCA_INI}\ndef a():\n    return 1\n{MARCA_MED}\ndef a():\n    return 7\n{MARCA_FIN}\n"
         f"m.py\n{MARCA_INI}\ndef b():\n    return 1\n{MARCA_MED}\ndef b():\n    return 8\n{MARCA_FIN}",
         lambda r: r[0] and "return 7" in r[0]["m.py"] and "return 8" in r[0]["m.py"]),
        ("sangria de mas se tolera",
         f"m.py\n{MARCA_INI}\ndef a():   \n    return 1   \n{MARCA_MED}\ndef a():\n    return 5\n{MARCA_FIN}",
         lambda r: r[0] and "return 5" in r[0]["m.py"]),
        ("texto suelto sin bloques",
         "aca esta el codigo corregido, cambiando el return",
         lambda r: r[0] is None),
    ]
    fallaron = 0
    for etiqueta, texto, comprobar in casos:
        bl = parsear_bloques(texto, {"m.py"})
        r = aplicar_bloques(orig, bl)
        try:
            ok = bool(comprobar(r))
        except Exception as e:
            ok, r = False, (None, f"{type(e).__name__}: {e}")
        print(f"  {'ok    ' if ok else 'FALLA '} {etiqueta}"
              f"{'' if ok else f'   -> {r[1] if r[0] is None else r[0]}'}")
        fallaron += not ok
    print(f"\n  {len(casos)-fallaron}/{len(casos)} del aplicador\n")
    return 1 if fallaron else 0


def main() -> int:
    if "--autotest" in sys.argv:
        return autotest()
    repes = int(next((a for a in sys.argv[1:] if a.isdigit()), 3))
    tareas = [t for t in TAREAS if not SOLO or t["id"] == SOLO]

    print(f"\n{'='*74}\n  FORMATO DE EDICION: {ETIQUETA}  (puerto {PUERTO})\n{'='*74}")
    print(f"  {len(tareas)} tareas x {repes} repeticiones x 2 formatos = "
          f"{len(tareas)*repes*2} llamadas\n")

    acu = {f: {"formato": 0, "aplica": 0, "pasa": 0, "rompio": 0,
               "chars": 0, "seg": 0.0, "n": 0} for f in ("entero", "bloques")}
    motivos: dict[str, list[str]] = {"entero": [], "bloques": []}

    for r in range(repes):
        for t in tareas:
            # Se alterna el orden entre repeticiones: si el backend se degrada
            # con el uso, el segundo formato pagaria siempre el costo.
            orden = ("entero", "bloques") if r % 2 == 0 else ("bloques", "entero")
            linea = f"  [{r+1}/{repes}] {t['id']:<20}"
            for f in orden:
                d = una_corrida(t, f)
                a = acu[f]
                for k in ("formato", "aplica", "pasa", "rompio"):
                    a[k] += bool(d[k])
                a["chars"] += d["chars"]; a["seg"] += d["seg"]; a["n"] += 1
                if d["motivo"]:
                    motivos[f].append(f"{t['id']}: {d['motivo']}")
                marca = "PASA" if d["pasa"] else ("aplica" if d["aplica"]
                                                 else ("formato" if d["formato"] else "-"))
                linea += f"  {f}={marca:<7}"
            print(linea, flush=True)

    print(f"\n{'='*74}")
    print(f"  {'':<10}{'formato':>9}{'aplica':>9}{'PASA':>9}{'rompio':>9}"
          f"{'chars':>9}{'seg':>7}")
    for f in ("entero", "bloques"):
        a = acu[f]; n = a["n"] or 1
        print(f"  {f:<10}{a['formato']:>6}/{n:<2}{a['aplica']:>6}/{n:<2}"
              f"{a['pasa']:>6}/{n:<2}{a['rompio']:>9}"
              f"{a['chars']//n:>9}{a['seg']/n:>7.0f}")
    print(f"{'='*74}\n")

    for f in ("entero", "bloques"):
        if motivos[f]:
            print(f"  por que fallo {f} ({len(motivos[f])}):")
            for m in motivos[f][:8]:
                print(f"    {m}")
            if len(motivos[f]) > 8:
                print(f"    ... y {len(motivos[f])-8} mas")
            print()

    salida = Path(__file__).resolve().parent.parent / "resultados" / f"resultado_formato_{ETIQUETA}.json"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps({"etiqueta": ETIQUETA, "repes": repes,
                                  "tareas": len(tareas), "acu": acu,
                                  "motivos": motivos}, indent=2, ensure_ascii=False))
    print(f"  guardado en {salida}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
