# -*- coding: utf-8 -*-
"""bateria_repetida.py - Ejecuta eval_expertos.py N veces y promedia.

POR QUE EXISTE (17/08/2026): la bateria NO es determinista. eval_expertos.py
pide las respuestas con `temp 0.1` para codigo, pero el backend puede estar
configurado con su propia temperatura, y en la practica el mismo modelo con la
misma config dio **22, 21 y 23** sobre 25 en tres ejecuciones seguidas.

Consecuencia: **una sola ejecucion no distingue dos modelos que esten a menos de
~3 puntos**. Durante la sesion del 17/08 varias comparaciones se hicieron con
n=1 y hubo que rehacerlas; una llego a invertirse por completo (se creia que
Qwen3.8-9B superaba a Qwythos-9B con 24 contra 24; con 3 ejecuciones cada uno
quedo 22,0 contra 23,0, es decir al reves).

Lo mismo pasa con la velocidad: la varianza entre ejecuciones es de ~+-3 tok/s
(7%), asi que diferencias menores al 10% tampoco son concluyentes.

Uso:
    python bateria_repetida.py <puerto> <etiqueta> [repeticiones]

Ejemplo:
    python bateria_repetida.py 8080 qwen3.8-9b 3

Deja un resultado_experto_<etiqueta>-rN.json por ejecucion (los mismos que lee
resumen_bateria.py) y ademas imprime media, minimo y maximo.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8080"
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "modelo"
REPES = int(sys.argv[3]) if len(sys.argv) > 3 else 3

if REPES < 2:
    print("Con menos de 2 repeticiones esto no tiene sentido: el problema que "
          "resuelve es justamente la varianza entre corridas.")
    sys.exit(1)


def correr(rep: int) -> tuple[int, int, float] | None:
    """Ejecuta una repeticion y devuelve (aciertos, total, tok/s)."""
    etq = f"{ETIQUETA}-r{rep}"
    print(f"\n  ── corrida {rep}/{REPES} ─────────────────────────────")
    r = subprocess.run(
        [sys.executable, str(AQUI.parent / "calidad" / "eval_expertos.py"), PUERTO, etq],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(f"     FALLO (exit {r.returncode}): {(r.stderr or '')[-200:]}")
        return None

    salida = AQUI / f"resultado_experto_{etq}.json"
    if not salida.exists():
        print("     no genero archivo de resultado")
        return None

    d = json.loads(salida.read_text(encoding="utf-8"))
    cod = d.get("codigo", {})
    ok, total = cod.get("aciertos", 0), cod.get("total", 0)
    raz = d.get("razonamiento_puntaje", {})
    # la velocidad no siempre esta en el JSON; se extrae de la salida si hace falta
    vel = d.get("velocidad_media", 0.0)
    if not vel:
        m = re.search(r"velocidad media ([\d.]+)", r.stdout or "")
        vel = float(m.group(1)) if m else 0.0
    raz_txt = f"   razon {raz.get('aciertos','?')}/{raz.get('total','?')}" if raz else ""
    print(f"     codigo {ok}/{total}{raz_txt}   {vel:.1f} t/s")
    return ok, total, vel, raz.get("aciertos")


resultados = [x for x in (correr(i) for i in range(1, REPES + 1)) if x]

if not resultados:
    print("\nNinguna corrida completo. Revisa que el backend este levantado en "
          f"el puerto {PUERTO}.")
    sys.exit(1)

aciertos = [r[0] for r in resultados]
razones = [r[3] for r in resultados if len(r) > 3 and r[3] is not None]
total = resultados[0][1]
vels = [r[2] for r in resultados if r[2]]

media = sum(aciertos) / len(aciertos)
print(f"\n{'='*56}")
print(f"  {ETIQUETA}   ({len(resultados)} corridas de {REPES})")
print(f"{'='*56}")
print(f"  aciertos : {' · '.join(str(a) for a in aciertos)}  ->  "
      f"media {media:.1f}/{total}  (min {min(aciertos)}, max {max(aciertos)})")
if razones:
    print(f"  razonam. : {' · '.join(str(a) for a in razones)}  ->  "
          f"media {sum(razones)/len(razones):.1f}/4")
if vels:
    print(f"  velocidad: media {sum(vels)/len(vels):.1f} t/s  "
          f"(min {min(vels):.1f}, max {max(vels):.1f})")

dispersion = max(aciertos) - min(aciertos)
print(f"  dispersion: {dispersion} punto(s)")
if dispersion >= 2:
    print("\n  AVISO: dispersion de 2 o mas puntos. Al comparar contra otro "
          "modelo,\n  no tomes por real ninguna diferencia menor a esa.")
print()
