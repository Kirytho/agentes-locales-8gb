# -*- coding: utf-8 -*-
"""grabador_proxy.py - Registra el trafico entre el harness y el intermediario.

POR QUE EXISTE (28/08/2026)

Los bancos que teniamos le hablan al intermediario DIRECTO. Miden al modelo, no al
sistema: no pasan por el bucle de agente de Hermes, ni por sus 22 herramientas,
ni por sus skills, ni por el multi-turno. Y justamente el fallo que quedo sin
explicar --"gemma opera mal un harness"-- solo aparece con el stack completo.

Se descarto mirar los archivos de Hermes:
  - `~/.hermes/sessions/` solo guarda `request_dump_*.json` CUANDO HAY ERROR
    (`reason: max_retries_exhausted`). No hay transcripcion de una sesion sana.
  - El historial del intermediario guarda solo `role` y `content`. Las tool_calls
    no estan ahi, que es exactamente lo que hay que contar.

Asi que se graba EL CABLE. Este proceso se situa entre el harness y el intermediario:

    hermes  ->  :8099 (este grabador)  ->  :8086 (intermediario)  ->  :8080 (backend)

Ventajas de medir aqui y no dentro del intermediario:
  - No toca ni una linea del intermediario, asi que no puede alterar lo que mide.
  - Es agnostico del harness: sirve igual para opencode, kiro o warp, que es la
    propiedad que ya verifico `compat_openai.py`.
  - Ve la verdad del protocolo: que herramientas se ofrecieron, si el modelo
    devolvio `tool_calls` de verdad o las NARRO como texto, y el finish_reason.

Este archivo solo GRABA. No juzga: quien puntua es `eval_stack_completo.py`.

Uso:
    BANCO_GRABACION=/tmp/x.jsonl python3 \
        pruebas/instrumentos/grabador_proxy.py [puerto_escucha] [puerto_destino]
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

PUERTO = int(sys.argv[1] if len(sys.argv) > 1 else os.getenv("BANCO_GRABADOR_PUERTO", "8099"))
DESTINO = os.getenv("BANCO_GRABADOR_DESTINO", f"http://127.0.0.1:{sys.argv[2] if len(sys.argv) > 2 else '8086'}")
SALIDA = Path(os.getenv("BANCO_GRABACION", "/tmp/grabacion.jsonl"))

# Sin tope: una vuelta de agente puede tardar minutos si el modelo escribe mucho.
# Con tope, el grabador cortaria peticiones que el intermediario habria contestado bien y
# el banco leeria un fallo que en realidad causo el instrumento.
cliente = httpx.AsyncClient(timeout=httpx.Timeout(None))

app = FastAPI()
_n = 0


def _apuntar(registro: dict) -> None:
    with SALIDA.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _leer_pedido(cuerpo: bytes) -> dict:
    try:
        d = json.loads(cuerpo)
    except Exception:
        return {"ilegible": True, "bytes": len(cuerpo)}
    msgs = d.get("messages") or []
    sistema = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
    ultimo = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            ultimo = m.get("content") or ""
            break
    herramientas = [
        (t.get("function") or {}).get("name", "?") for t in (d.get("tools") or [])
    ]
    return {
        "modelo": d.get("model"),
        "stream": bool(d.get("stream")),
        "n_herramientas": len(herramientas),
        "herramientas": herramientas,
        "n_mensajes": len(msgs),
        "roles": [m.get("role") for m in msgs],
        "chars_sistema": len(sistema),
        "ultimo_usuario": ultimo[:4000],
    }


class _Acumulador:
    """Reconstruye la respuesta a partir de los trozos SSE.

    Las tool_calls llegan partidas: un trozo trae `function.name` y los
    siguientes van sumando `function.arguments` caracter a caracter, todos
    identificados por `index`. Si no se juntan por index, una sola llamada se
    cuenta como varias.
    """

    def __init__(self) -> None:
        self.contenido: list[str] = []
        self.razonamiento: list[str] = []
        self.llamadas: dict[int, dict] = {}
        self.finish = None
        self.error = None

    def trozo(self, dato: dict) -> None:
        # Un payload de error NO trae "choices": sin esta rama el error se
        # perdia entero y la ejecucion quedaba como "respuesta vacia".
        if dato.get("error") and self.error is None:
            self.error = dato["error"]
        for op in dato.get("choices") or []:
            if op.get("finish_reason"):
                self.finish = op["finish_reason"]
            delta = op.get("delta") or op.get("message") or {}
            if delta.get("content"):
                self.contenido.append(delta["content"])
            # Gemma a veces mete datos de tool call en reasoning_content; hay que
            # verlo, si no el banco culpa al modelo de "no llamar" cuando en
            # realidad llamo por el campo equivocado.
            if delta.get("reasoning_content"):
                self.razonamiento.append(delta["reasoning_content"])
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", 0)
                slot = self.llamadas.setdefault(i, {"nombre": "", "argumentos": ""})
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["nombre"] = fn["name"]
                if fn.get("arguments"):
                    slot["argumentos"] += fn["arguments"]

    def resultado(self) -> dict:
        return {
            "finish_reason": self.finish,
            "contenido": "".join(self.contenido),
            "razonamiento": "".join(self.razonamiento),
            "tool_calls": [self.llamadas[i] for i in sorted(self.llamadas)],
            # Sin este campo, un error BIEN propagado por el intermediario se grababa
            # como una respuesta vacia y parecia un fallo del modelo. Paso el
            # 07/09/2026: tres pedidos del abanico quedaron como
            # {"finish_reason": null, "contenido": ""} cuando en realidad
            # llevaban {"error": {"code": 500, "message": "Context size has
            # been exceeded."}}. Media tarde persiguiendo un bug de streaming
            # que no existia.
            "error": self.error,
        }


def _parsear_sse(linea: str, acc: _Acumulador) -> None:
    if not linea.startswith("data:"):
        return
    cuerpo = linea[5:].strip()
    if not cuerpo or cuerpo == "[DONE]":
        return
    try:
        acc.trozo(json.loads(cuerpo))
    except Exception:
        pass


@app.api_route("/{ruta:path}", methods=["GET", "POST", "DELETE", "PUT"])
async def espejo(ruta: str, req: Request):
    global _n
    cuerpo = await req.body()
    url = f"{DESTINO}/{ruta}"
    cabeceras = {k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length")}
    grabable = req.method == "POST" and "chat/completions" in ruta

    if not grabable:
        r = await cliente.request(req.method, url, content=cuerpo, headers=cabeceras,
                                  params=dict(req.query_params))
        return Response(content=r.content, status_code=r.status_code,
                        headers={"content-type": r.headers.get("content-type", "application/json")})

    _n += 1
    n, t0 = _n, time.time()
    pedido = _leer_pedido(cuerpo)

    if not pedido.get("stream"):
        r = await cliente.post(url, content=cuerpo, headers=cabeceras)
        acc = _Acumulador()
        try:
            acc.trozo(r.json())
        except Exception:
            pass
        _apuntar({"n": n, "segundos": round(time.time() - t0, 2), "estado": r.status_code,
                  "pedido": pedido, "respuesta": acc.resultado()})
        return Response(content=r.content, status_code=r.status_code,
                        headers={"content-type": r.headers.get("content-type", "application/json")})

    async def pasar():
        acc = _Acumulador()
        estado = 0
        try:
            async with cliente.stream("POST", url, content=cuerpo, headers=cabeceras) as r:
                estado = r.status_code
                async for linea in r.aiter_lines():
                    _parsear_sse(linea, acc)
                    if linea:
                        yield (linea + "\n\n").encode()
                    # Una linea vacia es el separador de evento SSE; ya lo
                    # ponemos nosotros arriba, reemitirla parte el stream.
        finally:
            _apuntar({"n": n, "segundos": round(time.time() - t0, 2), "estado": estado,
                      "pedido": pedido, "respuesta": acc.resultado()})

    return StreamingResponse(pasar(), media_type="text/event-stream")


if __name__ == "__main__":
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    print(f"[grabador] {PUERTO} -> {DESTINO}  graba en {SALIDA}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PUERTO, log_level="warning")
