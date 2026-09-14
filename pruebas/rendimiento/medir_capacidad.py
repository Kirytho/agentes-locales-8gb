# -*- coding: utf-8 -*-
"""medir_capacidad.py - Cuantas peticiones por minuto soporta el intermediario.

POR QUE EXISTE (18/08/2026)

Todo lo medido hasta ahora es en tokens por segundo, que es la unidad del
motor. La pregunta de operacion es otra: **cuantas peticiones por minuto
sostiene el sistema**. No se deduce de los tok/s sin fijar dos cosas: cuanto
mide un pedido y cuantos agentes hay trabajando.

Metodo: lazo cerrado. C trabajadores envian pedidos uno tras otro durante
SEGUNDOS; al terminar se cuentan las respuestas completas. Eso da la capacidad
SOSTENIDA, no un pico: cada trabajador envia el siguiente solo cuando el
anterior volvio, asi que la cola nunca crece sin limite.

OJO CON LA CACHE: si todos los pedidos fueran iguales, el intermediario
contestaria de cache y el numero saldria absurdo. Cada pedido lleva un
identificador distinto dentro.

Uso:
    python3 pruebas/rendimiento/medir_capacidad.py [segundos]
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "http://127.0.0.1:8086/v1/chat/completions"
SEGUNDOS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
# Niveles de agentes. Estaban fijos en 1 y 4, de cuando la pregunta era si el
# sistema aguantaba la carga. Desde el 20/08 hay otra: llama.cpp cambia de kernel
# por encima de 8 peticiones simultaneas y el caudal salta 53-73% (ESTADO.md
# seccion 22). Ese salto se vio en RAFAGAS; falta saber si sobrevive a la carga
# sostenida, donde la cantidad de peticiones en vuelo fluctua y puede caer por
# debajo de 9 seguido.
NIVELES = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "1,4").split(",")]
MAX_TOKENS = 128

# Contexto de ~600 tokens: un pedido de trabajo real lleva codigo pegado, no
# una linea suelta. Medido en resultado_contexto.md: 700-1300 tokens de prompt.
CODIGO = """
def procesar_lote(registros, tamano=100, reintentos=3):
    resultados, fallidos = [], []
    for i in range(0, len(registros), tamano):
        lote = registros[i:i + tamano]
        for intento in range(reintentos):
            try:
                respuesta = cliente.enviar(lote, timeout=30)
                resultados.extend(respuesta.items)
                break
            except TimeoutError:
                if intento == reintentos - 1:
                    fallidos.extend(lote)
                time.sleep(2 ** intento)
            except ValueError as e:
                registrar(f"lote {i} invalido: {e}")
                fallidos.extend(lote)
                break
    return resultados, fallidos
""" * 3

ESCENARIOS = [
    # (nombre, modelo, plantilla del pedido)
    ("codigo (GPU)", "principal",
     "Revisa esta funcion y dime que problema tiene el manejo de errores.\n" + CODIGO),
    ("razonamiento (RAM)", "qwen3",
     "Analiza el diseno de esta funcion: que decisiones tomo el autor y cuales "
     "cambiarias, con el porque.\n" + CODIGO),
    ("mezcla por ruteo", "auto",
     "Explica que hace esta funcion y como la probarias.\n" + CODIGO),
]


def trabajador(modelo, plantilla, hasta, contador, lock, latencias, errores):
    n = 0
    while time.time() < hasta:
        n += 1
        marca = f"[peticion {threading.get_ident()}-{n}]"  # rompe la cache
        cuerpo = json.dumps({
            "model": modelo,
            "messages": [{"role": "user", "content": f"{marca}\n{plantilla}"}],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        }).encode()
        req = urllib.request.Request(
            URL, data=cuerpo, headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                d = json.loads(r.read())
            tok = d.get("usage", {}).get("completion_tokens", 0)
            with lock:
                contador[0] += 1
                contador[1] += tok
                latencias.append(time.time() - t0)
        except Exception as e:  # noqa: BLE001 - interesa cualquier fallo
            with lock:
                errores.append(str(e)[:90])


def medir(nombre, modelo, plantilla, agentes):
    contador = [0, 0]
    lock = threading.Lock()
    latencias, errores = [], []
    hasta = time.time() + SEGUNDOS
    t0 = time.time()
    hilos = [threading.Thread(target=trabajador,
                              args=(modelo, plantilla, hasta, contador, lock,
                                    latencias, errores))
             for _ in range(agentes)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    pared = time.time() - t0

    hechas, tokens = contador
    rpm = hechas / pared * 60
    lat = sorted(latencias)
    p50 = lat[len(lat) // 2] if lat else 0
    p95 = lat[int(len(lat) * 0.95)] if len(lat) > 1 else p50
    print(f"  {nombre:22s} {agentes} agente(s): "
          f"{rpm:6.1f} req/min · {hechas:3d} en {pared:.0f}s · "
          f"latencia {p50:5.1f}s (p95 {p95:5.1f}s) · {tokens / pared:5.1f} tok/s"
          + (f" · ERRORES {len(errores)}" if errores else ""))
    if errores:
        print(f"      {errores[0]}")
    return {"escenario": nombre, "modelo": modelo, "agentes": agentes,
            "rpm": rpm, "hechas": hechas, "segundos": pared,
            "p50": p50, "p95": p95, "tok_s": tokens / pared,
            "errores": len(errores)}


print(f"\n{'=' * 78}\n  Capacidad del intermediario · lazo cerrado · {SEGUNDOS}s por escenario"
      f"\n  pedido: ~600 tokens de prompt, {MAX_TOKENS} de respuesta\n{'=' * 78}")
res = []
for nombre, modelo, plantilla in ESCENARIOS:
    for agentes in NIVELES:
        res.append(medir(nombre, modelo, plantilla, agentes))

salida = AQUI / "resultado_capacidad.json"
salida.write_text(json.dumps({"segundos": SEGUNDOS, "max_tokens": MAX_TOKENS,
                              "escenarios": res}, ensure_ascii=False, indent=2),
                  encoding="utf-8")
print(f"\n  Crudos en {salida}\n")
