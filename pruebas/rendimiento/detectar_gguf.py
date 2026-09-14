# -*- coding: utf-8 -*-
"""detectar_gguf.py - Que soporta un modelo, leyendo el archivo.

POR QUE (19/08/2026)

Probar todas las banderas en todos los modelos es multiplicativo y la mayoria no
aplica: `draft-mtp` necesita que el GGUF traiga los tensores `blk.N.nextn.*`, y
`-ncmoe` solo tiene sentido si el modelo es MoE. Preguntarselo al archivo antes
de probar ahorra la mayor parte del barrido.

Los nombres de tensores viven como texto plano en la cabecera del GGUF, asi que
alcanza con leer los primeros megabytes y buscar. No hace falta parsear el
formato entero ni instalar nada.
"""
import sys
from pathlib import Path

CABECERA = 32 * 1024 * 1024   # los nombres de tensores estan al principio


def detectar(ruta):
    ruta = Path(ruta)
    with open(ruta, "rb") as f:
        cabeza = f.read(CABECERA)
    if not cabeza.startswith(b"GGUF"):
        raise ValueError(f"{ruta.name} no parece un GGUF")

    # Buscar texto suelto en la cabecera da FALSOS POSITIVOS: el vocabulario del
    # tokenizador esta ahi tambien y contiene palabras como "expert" o "mtp", asi
    # que el 9B denso aparecia como MoE y con MTP (19/08/2026). Hay que mirar
    # solo los NOMBRES DE TENSORES, que siguen el patron `blk.<n>.<nombre>`.
    import re as _re
    tensores = set(_re.findall(rb"blk\.\d+\.[a-z_0-9.]+", cabeza))
    nombres = b" ".join(sorted(tensores))

    def hay(*marcas):
        return any(m.encode() in nombres for m in marcas)

    # Arquitectura: la clave `general.architecture` guarda el nombre justo despues.
    arq = "?"
    i = cabeza.find(b"general.architecture")
    if i >= 0:
        trozo = cabeza[i:i + 120]
        for cand in (b"qwen3moe", b"qwen3", b"qwen2moe", b"qwen2", b"llama",
                     b"gemma3", b"gemma2", b"phi3", b"mistral", b"deepseek2"):
            if cand in trozo:
                arq = cand.decode()
                break
    return {
        "archivo": ruta.name,
        "gb": round(ruta.stat().st_size / 2**30, 2),
        "arquitectura": arq,
        # MTP / eagle: capas de prediccion adicional dentro del propio modelo
        "mtp": hay("nextn"),
        "eagle": hay("eagle"),
        # MoE: tensores de expertos
        "moe": hay("_exps"),
        "n_tensores": len(tensores),
    }


def spec_aplicables(info):
    """Los --spec-type que tiene sentido probar en este modelo."""
    # Estos no necesitan nada del modelo ni un segundo modelo cargado.
    tipos = ["none", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod",
             "ngram-cache", "suffix", "copyspec", "recycle"]
    if info["mtp"]:
        tipos += ["draft-mtp", "draft-dflash", "dflash"]
    if info["eagle"]:
        tipos += ["draft-eagle3"]
    # draft-simple queda fuera a proposito: necesita un SEGUNDO modelo cargado
    # (-md), y en 8 GB de VRAM no entra junto al principal.
    return tipos


if __name__ == "__main__":
    for ruta in sys.argv[1:]:
        i = detectar(ruta)
        print(f"\n  {i['archivo']}  ({i['gb']} GB)")
        print(f"    arquitectura : {i['arquitectura']}")
        print(f"    MoE          : {'si' if i['moe'] else 'no'}"
              + ("   -> probar -ncmoe" if i["moe"] else ""))
        print(f"    MTP/nextn    : {'si' if i['mtp'] else 'no'}"
              + ("   -> probar draft-mtp" if i["mtp"] else "   (draft-mtp no aplica)"))
        print(f"    spec a probar: {len(spec_aplicables(i))} tipos")
