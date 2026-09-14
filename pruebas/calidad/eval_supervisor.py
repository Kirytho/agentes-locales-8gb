# -*- coding: utf-8 -*-
"""
eval_supervisor.py - ¿Sirve que el modelo grande de GPU supervise a los pequeños?

Idea del autor, alineada con la "cascada por incertidumbre" que recomienda la
literatura: el experto pequeño responde y el modelo capaz revisa la SALIDA, escalando
solo cuando la calidad no convence.

Este arnés lo mide de forma OBJETIVA porque hay verdad de referencia: el código de
los modelos pequeños ya fue verificado POR EJECUCIÓN en eval_expertos.py, así que se
sabe cuál está bien y cuál mal. El supervisor no lo sabe.

Métricas (las que importan según la literatura):
  - Deteccion       : de los errores REALES, cuantos atrapa
  - Falso descubrimiento: de los correctos, cuantos escala de mas
    (Cluster-Route-Escalate reporta 51% en su cascada; es el costo a vigilar)

Uso: python eval_supervisor.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
URL_SUP = "http://127.0.0.1:8080/v1/chat/completions"

# Las descripciones salen del propio banco: escribirlas aparte las desincroniza
# en cuanto se agrega una tarea.
from eval_expertos import TAREAS as _BANCO  # noqa: E402

TAREAS = {t["id"]: {"desc": t["prompt"]} for t in _BANCO}

PROMPT = """Eres un revisor de codigo experto. Evalua si el codigo resuelve CORRECTAMENTE la tarea.

TAREA PEDIDA:
{desc}

CODIGO PROPUESTO:
```python
{codigo}
```

Pensa en los casos borde. Responde UNICAMENTE con una palabra: CORRECTO o INCORRECTO."""


def supervisar(desc, codigo):
    body = json.dumps({
        "model": "supervisor",
        "messages": [{"role": "user", "content": PROMPT.format(desc=desc, codigo=codigo)}],
        "max_tokens": 12, "temperature": 0.0, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    r = urllib.request.Request(URL_SUP, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(r, timeout=300) as resp:
        d = json.loads(resp.read())
    ms = (time.time() - t0) * 1000
    txt = (d["choices"][0]["message"].get("content") or "").strip().upper()
    # veredicto: True = el supervisor lo da por bueno
    if "INCORRECTO" in txt:
        return False, ms, txt
    if "CORRECTO" in txt:
        return True, ms, txt
    return None, ms, txt or "(vacio)"


def main():
    casos = []
    for etiqueta in ("especialista", "control"):
        p = AQUI / f"resultado_experto_{etiqueta}.json"
        if not p.exists():
            print(f"falta {p.name}"); return
        d = json.loads(p.read_text(encoding="utf-8"))
        for item in d["codigo"]["detalle"]:
            casos.append({"modelo": etiqueta, "id": item["id"],
                          "real_ok": item["ok"], "codigo": item["codigo"]})

    print(f"\n{'='*70}\n  SUPERVISOR: Bonsai-27B (GPU) juzgando {len(casos)} codigos")
    print(f"  Verdad de referencia: verificada POR EJECUCION\n{'='*70}\n")
    print(f"{'modelo':<14}{'tarea':<12}{'real':<10}{'supervisor':<12}{'veredicto':<12}{'ms':>7}")

    vp = fn = fp = vn = nulos = 0   # sobre "detectar el error"
    tiempos = []
    for c in casos:
        ok_sup, ms, crudo = supervisar(TAREAS[c["id"]]["desc"], c["codigo"])
        tiempos.append(ms)
        real = "correcto" if c["real_ok"] else "ERRONEO"
        if ok_sup is None:
            dic, nulos = "?? " + crudo[:8], nulos + 1
        else:
            dic = "correcto" if ok_sup else "ESCALA"
            if not c["real_ok"] and not ok_sup: vp += 1; res = "ATRAPADO"
            elif not c["real_ok"] and ok_sup:   fn += 1; res = "SE ESCAPO"
            elif c["real_ok"] and not ok_sup:   fp += 1; res = "falso pos."
            else:                               vn += 1; res = "ok"
        print(f"{c['modelo']:<14}{c['id']:<12}{real:<10}{dic:<12}"
              f"{(res if ok_sup is not None else '-'):<12}{ms:>6.0f}")

    errores = vp + fn
    correctos = vn + fp
    print(f"\n{'='*70}\n  RESULTADO\n{'='*70}")
    print(f"  Codigos con error real : {errores}   -> atrapados {vp}, escapados {fn}")
    print(f"  Codigos correctos      : {correctos}   -> respetados {vn}, escalados de mas {fp}")
    if errores:
        print(f"\n  DETECCION            : {100*vp/errores:.0f}%  (de los errores reales)")
    if correctos:
        print(f"  FALSO DESCUBRIMIENTO : {100*fp/correctos:.0f}%  "
              f"(correctos escalados; la literatura reporta 51%)")
    if nulos:
        print(f"  Respuestas no parseables: {nulos}")
    print(f"  Costo de supervisar   : {sum(tiempos)/len(tiempos):.0f} ms por revision")


if __name__ == "__main__":
    main()
