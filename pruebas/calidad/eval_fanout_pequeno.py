#!/usr/bin/env python3
"""Abanico PEQUEÑO: 4 servicios en vez de 16.

Por que existe
--------------
El 07/09/2026 el abanico de 16 servicios dio 0 aciertos en 7 ejecuciones sobre 5
modelos, y ninguno delego mas de 2 veces de 16 pedidas:

    Q4_K_M  1 y 0    IQ2_M  2    IQ3_M  2    IQ4_XS  1    TB-8B  0    Q5_K_M  0

Pero eso confunde DOS hipotesis que hay que separar:
  (a) el modelo no sabe/no quiere repartir trabajo, o
  (b) la tarea es tan grande que se pierde antes de llegar a organizarse.

Evidencia de que (b) es posible: Q4_K_M gasto 7 llamadas leyendo UN solo
servicio en pedazos (head, tail, sed 60-160, sed 160-290...) antes de empezar
el bucle sobre los 16. IQ3_M dio 93 vueltas y se comio los 900 s.

Con 4 servicios la tarea entra comoda en cualquier contexto (~38.000 tokens
contra ~153.000) y 4 ramas caben hasta en la reserva mas pequeña (65.536 / 20.900 =
3, es decir una serie de 3 y una de 1). Si aqui TAMPOCO delega, (b) queda
descartada y el bloqueo es de conducta.

Todo lo demas se hereda de eval_fanout.py sin tocarlo: mismo fixture por
servicio, mismo oraculo tolerante al formato, misma exigencia de archivo en
disco y no de prosa.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_stack_completo as E   # noqa: E402
import eval_fanout as F           # noqa: E402

# Los 4 primeros del set grande. Se mantienen los mismos nombres y defectos
# para que el resultado sea comparable con el abanico de 16.
_CUATRO = dict(list(F._DEFECTOS.items())[:4])
_MINIMO = 3   # de 4. Misma proporcion que el grande (12 de 16) y que
              # `contexto` (6 de 8): 75%.


def montar(d: Path) -> dict:
    import random
    rnd = random.Random(11)
    firma = ("(items=(), descuentos=(), precio=0, pendientes=None, correo='',"
             " d=None, f=None, ruta='', linea='', sesiones=None, msg=None,"
             " xs=(), s='', partes=(), n=0, k='', **kw):")
    for serv, (fn, cuerpo) in _CUATRO.items():
        sub = d / serv
        sub.mkdir(parents=True)
        L = ["import json", "import time", "", "TTL = 3600",
             "RUTA = '/var/log/app.log'", ""]
        relleno = [(f"{n}_{k}", c) for k in range(16) for n, c in E._RELLENO]
        rnd.shuffle(relleno)
        corte = rnd.randrange(10, len(relleno) - 10)
        for n, c in relleno[:corte]:
            L += [f"def {n}{firma}", c, ""]
        L += [f"def {fn}{firma}", cuerpo, ""]
        for n, c in relleno[corte:]:
            L += [f"def {n}{firma}", c, ""]
        (sub / "servicio.py").write_text("\n".join(L))
    return {"esperado": {s: v[0] for s, v in _CUATRO.items()},
            "minimo": _MINIMO, "archivo": F._ARCHIVO}


def pedir(d: Path) -> str:
    return (
        f"En {d} hay CUATRO subdirectorios independientes. Cada uno tiene un "
        f"servicio.py de ~537 lineas con muchas funciones correctas y EXACTAMENTE "
        f"UNA con un defecto real. Son cuatro analisis independientes entre si: "
        f"conviene repartirlos en subagentes en paralelo en vez de leerlos uno "
        f"detras del otro. Cuando tengas los cuatro resultados, consolidalos tú "
        f"en UN UNICO archivo {d}/{F._ARCHIVO}, con EXACTAMENTE cuatro lineas, una "
        f"por servicio, en el formato:\n"
        f"    nombre_del_directorio:nombre_exacto_de_la_funcion_defectuosa\n"
        f"Sin encabezado, sin numeracion, sin texto alrededor. El archivo es el "
        f"entregable: si no existe, la tarea no esta hecha."
    )


def revisar(d: Path, verdad: dict, texto: str):
    # El oraculo del grande sirve tal cual: no asume 16, usa verdad['esperado'].
    ok, det = F.revisar_fanout(d, verdad, texto)
    return ok, det.replace("/16", "/4")


if __name__ == "__main__":
    E.ESCENARIOS.clear()
    E.ESCENARIOS["fanout4"] = (montar, pedir, revisar)
    sys.argv = [sys.argv[0], "fanout4"]
    codigo = E.main()
    print("DELEGACION", F._resumen_delegacion(E.GRABACION))
    sys.exit(codigo)
