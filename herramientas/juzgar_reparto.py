#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""juzgar_reparto.py - ejecuta el juez de ProjectEval y limpia lo que deja abierto.

POR QUE EXISTE (12/09/2026)

`run_judge.py` inicia un servidor Django y un Chrome por cada proyecto que
evalua, y NO los cierra. Con 120 proyectos junto tanto que el sistema mato la
ejecucion de generacion por falta de memoria, y hubo que barrer los
`manage.py runserver` a mano dos veces.

El juez es codigo externo (GPL-3.0, en `externos/`), asi que no se parchea: se
lo envuelve. El barrido va en un `finally`, para que tambien limpie si el juez
falla o si lo interrumpen con Ctrl-C.

COMO EVITA MATAR ALGO AJENO

Dos reglas, las dos necesarias:

  1. Se toma una FOTO de los procesos antes de iniciar. Solo se consideran los
     que NO estaban en esa foto. Un Django o un Chrome que el usuario ya tenia
     abierto nunca entra en la lista.
  2. De esos, se matan solo los que cumplen el criterio: `manage.py runserver`
     con el directorio de trabajo DENTRO del banco, o un chromedriver/Chrome
     lanzado por Selenium (`--test-type`, `--remote-debugging-port`, o un
     perfil temporal).

Se mata por PID y se verifica la linea de comandos justo antes, nunca con
`pkill -f` -- que en este proyecto ya se llevo puesto un `cloudflared` y un
barrido entero.

Uso:
    python3 herramientas/juzgar_reparto.py 20260912c-r1-1 20260912c-r2-1
    python3 herramientas/juzgar_reparto.py --todas
    python3 herramientas/juzgar_reparto.py --solo-limpiar
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = Path(os.getenv("BANCO_REPARTO_BANCO", RAIZ / "externos" / "ProjectEval"))
PY_BANCO = BANCO / ".venv" / "bin" / "python"


def _cmdline(pid: int) -> str:
    try:
        return (Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", "replace"))
    except OSError:
        return ""


def _cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _vivos() -> set[int]:
    return {int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()}


def _es_del_juez(pid: int) -> str:
    """Devuelve por que este proceso es basura del juez, o "" si no lo es."""
    cmd = _cmdline(pid)
    if not cmd:
        return ""
    if "manage.py" in cmd and "runserver" in cmd:
        # Solo si se ejecuta DENTRO del banco: un Django del usuario en otro lado no
        # se toca ni aunque se haya iniciado durante el juicio.
        cwd = _cwd(pid)
        if cwd and str(BANCO) in cwd:
            return f"django runserver en {cwd}"
        return ""
    if "chromedriver" in cmd:
        return "chromedriver"
    if "--test-type" in cmd or "--remote-debugging-port" in cmd:
        return "chrome de selenium"
    return ""


def barrer(previos: set[int], espera: float = 3.0) -> int:
    """Cierra lo que dejo el juez. Solo procesos NUEVOS y que cumplan el criterio."""
    candidatos = []
    for pid in sorted(_vivos() - previos):
        motivo = _es_del_juez(pid)
        if motivo:
            candidatos.append((pid, motivo))
    if not candidatos:
        print("  nada que barrer")
        return 0

    for pid, motivo in candidatos:
        # Re-verificar en el momento de matar: entre que se listo y ahora, ese
        # PID pudo reciclarse y ser otro proceso.
        if not _es_del_juez(pid):
            print(f"  pid={pid} ya no es lo que era, no lo toco")
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  cerrado pid={pid} ({motivo})")
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  pid={pid} no es mio, lo dejo")

    time.sleep(espera)
    tercos = [(p, m) for p, m in candidatos if p in _vivos() and _es_del_juez(p)]
    for pid, motivo in tercos:
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"  forzado pid={pid} ({motivo})")
        except OSError:
            pass
    return len(candidatos)


def _memoria_mb() -> int:
    for linea in Path("/proc/meminfo").read_text().splitlines():
        if linea.startswith("MemAvailable:"):
            return int(linea.split()[1]) // 1024
    return 0


def carpetas_disponibles() -> list[str]:
    exp = BANCO / "experiments"
    if not exp.is_dir():
        return []
    return sorted(d.name for d in exp.iterdir()
                  if d.is_dir() and d.name != "example"
                  and any(d.glob("*/*/*_level_*.json")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("carpetas", nargs="*", help="carpetas de experiments/ a juzgar")
    ap.add_argument("--todas", action="store_true", help="todas las que haya")
    ap.add_argument("--solo-limpiar", action="store_true",
                    help="no juzga: solo cierra lo que haya quedado abierto")
    args = ap.parse_args()

    if args.solo_limpiar:
        # Sin foto previa no hay proteccion por "proceso nuevo", asi que aqui el
        # criterio tiene que alcanzar solo: django DENTRO del banco y chrome de
        # selenium. Un Django del usuario en otro directorio no entra.
        print("barriendo lo que haya quedado abierto:")
        n = barrer(previos=set())
        print(f"cerrados: {n}   memoria disponible: {_memoria_mb()} MB")
        return 0

    carpetas = carpetas_disponibles() if args.todas else args.carpetas
    if not carpetas:
        print("no hay carpetas para juzgar. Disponibles:")
        for c in carpetas_disponibles():
            print(f"  {c}")
        return 1
    if not PY_BANCO.exists():
        print(f"falta el venv del banco en {PY_BANCO}")
        print("  uv venv --python 3.12 .venv   (dentro de externos/ProjectEval)")
        return 1

    previos = _vivos()
    mem0 = _memoria_mb()
    print(f"juzgando {carpetas}   (memoria disponible: {mem0} MB)")
    t0 = time.time()
    codigo = 0
    try:
        proc = subprocess.run(
            [str(PY_BANCO), "run_judge.py", "-r", json.dumps(carpetas)],
            cwd=BANCO)
        codigo = proc.returncode
    except KeyboardInterrupt:
        print("\ninterrumpido")
        codigo = 130
    finally:
        # SIEMPRE: si el juez fallo o lo interrumpieron, igual hay que cerrar
        # los servidores y navegadores que alcanzo a abrir.
        print(f"\nbarriendo lo que dejo el juez ({time.time() - t0:.0f} s):")
        n = barrer(previos)
        mem1 = _memoria_mb()
        print(f"cerrados: {n}   memoria disponible: {mem0} -> {mem1} MB "
              f"({mem1 - mem0:+d})")

    csvs = sorted((BANCO / "experiments").glob("projecteval-result-*.csv"),
                  key=lambda p: p.stat().st_mtime)
    if csvs:
        print(f"\nresultado -> {csvs[-1].relative_to(BANCO)}")
        print(csvs[-1].read_text(encoding="utf-8").rstrip())
    return codigo


if __name__ == "__main__":
    sys.exit(main())
