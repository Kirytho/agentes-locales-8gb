#!/usr/bin/env python3
"""Escenario de ABANICO: N analisis independientes que convergen en UN archivo.

Por que existe
--------------
Los 5 escenarios de `eval_stack_completo.py` son secuenciales de un solo
agente: ninguno pide abanico y ninguno puntua si lo hubo. En una muestra del
cable del barrido del 06/09/2026 -- 58 llamadas reales -- `delegate_task`
aparecio 2 veces, por iniciativa del modelo y no porque el banco lo pidiera.
La muestra es pequeña a proposito: el grabador TRUNCA el archivo en cada
ejecucion, asi que en disco solo queda el cable de la ultima. Los totales del
brazo salen de la linea CABLE del resumen (p.ej. 1.836 llamadas reales en los
5 primeros brazos), que no desglosa por herramienta. Sea cual sea la tasa
exacta, el punto no cambia: el paralelismo no se estaba MIDIENDO.

Eso deja sin probar lo unico para lo que sirve ganar VRAM bajando bits. El
contexto en llama.cpp con `--kv-unified` es una RESERVA COMPARTIDA, no ctx por
slot, y cada subagente de Hermes cuesta ~11.308 tokens (5.657 de prompt de
sistema + ~5.651 de contenido). El techo de subagentes es reserva / 11.308:

    IQ2_M  @196.608  ->  17 subagentes
    IQ3_M  @163.840  ->  14
    Q4_K_M  @98.304  ->   8
    Q5_K_M  @65.536  ->   5

Ese techo es la unica ventaja agentica real del 2 bits, y ningun escenario
la tocaba.

Tres decisiones de diseno, cada una para no medir otra cosa
----------------------------------------------------------
1. EL ORACULO PUNTUA SOBRE DISCO, NO SOBRE PROSA.  `informe` es el unico
   escenario que puntua sobre prosa y es justo donde IQ2_M obtiene 0/12 (contra
   5/12 del control). Si el resultado consolidado se puntuara leyendo la
   redaccion del modelo, un fallo de abanico y un fallo de redaccion darian
   el mismo cero y no habria forma de separarlos. Aqui se exige un archivo con
   formato estricto y se parsea.

2. EL TRABAJO POR RAMA TIENE QUE RESISTIR A `execute_code`.  `execute_code`
   es la herramienta mas usada del banco (26 de 58 llamadas). Si cada rama
   fuera "encontrar la fila anomala del CSV", el modelo escribe UN script que
   barre los 16 lotes de una y no delega nunca -- el escenario mediria
   programacion, no abanico. Por eso la unidad de trabajo es la misma que en
   `contexto`: cual de ~270 funciones es la defectuosa. Eso exige LEER, y
   leer no se paraleliza con un bucle.

3. EL TOTAL NO ENTRA EN UNA SOLA VENTANA, CADA RAMA SI.  Medido sobre el
   fixture real: 16 servicios, 613.502 chars, ~153.375 tokens en total y
   ~9.585 por servicio. Con ~11.308 de gasto fijo por subagente, cada rama
   cuesta ~20.900 tokens, y la reserva compartida da:

       ctx  65.536 -> 3 ramas a la vez, 16 servicios en 6 series
       ctx  98.304 -> 4
       ctx 163.840 -> 7
       ctx 196.608 -> 9

   Y como reserva secuencial: 153.375 NO entra en 65.536 ni en 98.304, si entra
   en 163.840 y en 196.608. Es decir que Q5_K_M, TB-8B y hasta Q4_K_M estan
   OBLIGADOS a delegar o a comprimir sin parar, mientras IQ2_M e IQ3_M pueden
   resolverlo de corrido. Esa asimetria es la que `contexto` no tiene: sus 8
   servicios (~45.205 tokens) entran en 65.536, asi que Q4_K_M ya obtenia 8/8
   en el piloto y no habia techo que superar. Por eso `contexto` no
   discrimino por contexto y este deberia.

   NOTA sobre `contexto`: arrastra las dos fugas que aqui se cerraron (la
   funcion defectuosa siempre en la posicion del medio, y con firma distinta
   a las otras 160). No se toco porque el barrido del 06/09 se estaba ejecutando
   sobre ese fixture y cambiarlo invalidaba los brazos ya cerrados; queda
   registrado para rehacerlo despues.

No ejecuta nada por su cuenta: reusa el arnes de eval_stack_completo (grabador,
huellas SHA-1 de la entrada, tope de tiempo, lectura del cable) inyectando el
escenario en su dict en memoria. No modifica ese archivo.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_stack_completo as E   # noqa: E402  (necesita el sys.path de arriba)


# 16 defectos: los 8 de `contexto` mas 8 nuevos. Cada nombre termina en dos
# letras unicas para que el oraculo no acierte por coincidencia de subcadena
# ("procesar" aparece en muchas; "procesar_cola_yt" en una sola).
_DEFECTOS = dict(E._BUGS)
_DEFECTOS.update({
    "pagos":       ("conciliar_saldo_yt",
                    "    saldo = 0.0\n"
                    "    for m in items:\n"
                    "        saldo += float(m.monto)   # float para dinero: 0.1+0.2 != 0.3, el arqueo no cierra\n"
                    "    return saldo"),
    "catalogo":    ("buscar_por_sku_vn",
                    "    for i in items:\n"
                    "        if i.sku == k: return i\n"
                    "    # sin return final: devuelve None y el llamador hace i.precio -> AttributeError"),
    "cache":       ("invalidar_clave_gm",
                    "    for k2 in list(sesiones):\n"
                    "        if k2.startswith(k):\n"
                    "            del sesiones[k2]\n"
                    "    return True   # borra por PREFIJO: invalidar 'user_1' se lleva 'user_10' y 'user_100'"),
    "colas":       ("procesar_cola_rf",
                    "    while pendientes:\n"
                    "        t = pendientes.pop(0)\n"
                    "        ejecutar(t)   # sin try: una tarea que falla mata el worker y pierde el resto de la cola"),
    "permisos":    ("tiene_acceso_wq",
                    "    if not k: return True   # sin rol => permitido: falla ABIERTO, deberia denegar\n"
                    "    return k in ('admin', 'editor')"),
    "importador":  ("parsear_linea_zj",
                    "    partes = linea.split(',')\n"
                    "    return {'id': partes[0], 'nombre': partes[1]}   # split crudo: un nombre con coma corre las columnas"),
    "reintentos":  ("esperar_backoff_ck",
                    "    import time\n"
                    "    time.sleep(2 ** n)   # sin tope: en el intento 20 duerme 12 dias"),
    "metricas":    ("promedio_movil_hd",
                    "    xs = list(xs)\n"
                    "    return sum(xs[-n:]) / n   # divide por n y no por lo que hay: con menos de n muestras subestima"),
})

_ARCHIVO = "hallazgos.txt"
_MINIMO = 12          # de 16. Mismo criterio proporcional que `contexto` (6 de 8).


def montar_fanout(d: Path) -> dict:
    import random
    # Semilla fija: todos los brazos tienen que ver EXACTAMENTE el mismo
    # fixture. Con relleno al azar la comparacion mediria la suerte del
    # relleno, no el modelo. Semilla 11 y no 7 para que no salga identico al
    # de `contexto`, que comparte los primeros 8 servicios.
    rnd = random.Random(11)
    # UNA SOLA firma para las 161 funciones, defectuosa incluida. Si la
    # defectuosa tuviera firma propia -- como pasa en `contexto` -- seria la
    # unica distinta entre 160 iguales y `grep "def.*items="` la encontraria
    # sin leer una linea. Eso convertiria el escenario en una prueba de grep,
    # que es exactamente lo que la decision 2 del encabezado quiere evitar.
    firma = ("(items=(), descuentos=(), precio=0, pendientes=None, correo='',"
             " d=None, f=None, ruta='', linea='', sesiones=None, msg=None,"
             " xs=(), s='', partes=(), n=0, k='', **kw):")
    for serv, (fn, cuerpo) in _DEFECTOS.items():
        sub = d / serv
        sub.mkdir(parents=True)
        L = ["import json", "import time", "", "TTL = 3600",
             "RUTA = '/var/log/app.log'", ""]
        relleno = [(f"{n}_{k}", c) for k in range(16) for n, c in E._RELLENO]
        rnd.shuffle(relleno)
        # Posicion al azar y distinta por servicio: si la defectuosa cayera
        # siempre en el medio, bastaria mirar el centro de cada archivo.
        corte = rnd.randrange(10, len(relleno) - 10)
        for n, c in relleno[:corte]:
            L += [f"def {n}{firma}", c, ""]
        L += [f"def {fn}{firma}", cuerpo, ""]
        for n, c in relleno[corte:]:
            L += [f"def {n}{firma}", c, ""]
        (sub / "servicio.py").write_text("\n".join(L))
    return {"esperado": {s: v[0] for s, v in _DEFECTOS.items()},
            "minimo": _MINIMO, "archivo": _ARCHIVO}


def pedir_fanout(d: Path) -> str:
    return (
        f"En {d} hay DIECISEIS subdirectorios independientes. Cada uno tiene un "
        f"servicio.py de ~537 lineas con muchas funciones correctas y EXACTAMENTE "
        f"UNA con un defecto real. Son dieciseis analisis independientes entre si: "
        f"conviene repartirlos en subagentes en paralelo en vez de leerlos uno "
        f"detras del otro. Cuando tengas los dieciseis resultados, consolidalos tú "
        f"en UN UNICO archivo {d}/{_ARCHIVO}, con EXACTAMENTE dieciseis lineas, una "
        f"por servicio, en el formato:\n"
        f"    nombre_del_directorio:nombre_exacto_de_la_funcion_defectuosa\n"
        f"Sin encabezado, sin numeracion, sin texto alrededor. El archivo es el "
        f"entregable: si no existe, la tarea no esta hecha."
    )


_LIMPIAR = re.compile(r"^[\s\-*\u2022\d.)\]]+")


def _norm_serv(bruto: str) -> str:
    """Nombre de servicio tolerante a envoltorio cosmetico.

    Se quitan numeracion, vinetas, ruta y mayusculas. NO es laxitud gratuita: si
    el oraculo exigiera el formato al pie de la letra, un modelo que encontro
    los 16 defectos y los numero sacaria cero, y el escenario estaria midiendo
    obediencia de formato en vez de abanico -- el mismo confundido que la
    decision 1 del encabezado quiere evitar. Lo estricto queda donde importa:
    la funcion tiene que coincidir EXACTA con la del servicio que le toca.
    """
    s = _LIMPIAR.sub("", bruto.strip()).strip()
    s = s.replace("\\", "/").rstrip("/")
    if "/" in s:                      # 'ruta/al/inventario' o 'inventario/servicio.py'
        partes = [p for p in s.split("/") if p and not p.endswith(".py")]
        s = partes[-1] if partes else s
    return s.strip().strip('"\'`').lower()


def revisar_fanout(d: Path, verdad: dict, texto: str):
    # Se puntua el ARCHIVO, nunca `texto`. Un modelo que narra los 16 hallazgos
    # en prosa pero no escribe el archivo NO consolido, que es justo lo que este
    # escenario mide. Ver decision 1 del encabezado.
    ruta = d / verdad["archivo"]
    if not ruta.exists():
        # Se informa cuantos nombro en prosa: distingue "no supo encontrarlos"
        # de "los encontro y no consolido", que son fallos distintos.
        en_prosa = sum(1 for f in verdad["esperado"].values() if f in (texto or ""))
        return False, f"no escribio {verdad['archivo']}; nombro {en_prosa}/16 en prosa"

    lineas = [l.strip() for l in ruta.read_text().splitlines() if l.strip()]
    esperado = verdad["esperado"]
    vistos, malos = {}, []
    for l in lineas:
        if ":" not in l:
            malos.append(l[:30]); continue
        serv, fn = l.split(":", 1)
        vistos[_norm_serv(serv)] = fn.strip()

    ok_serv = [s for s, fn in esperado.items()
               if vistos.get(s, "") == fn]
    faltan = [s for s in esperado if s not in vistos]
    errados = [f"{s}={vistos[s]}" for s in esperado
               if s in vistos and vistos[s] != esperado[s]]

    n, minimo = len(ok_serv), verdad["minimo"]
    det = f"{n}/16 correctos"
    if faltan:
        det += f"; sin linea {faltan[:4]}"
    if errados:
        det += f"; errados {errados[:3]}"
    if malos:
        det += f"; {len(malos)} lineas mal formadas"
    if len(lineas) != 16:
        det += f"; {len(lineas)} lineas (se pidieron 16)"
    return n >= minimo, det


def _resumen_delegacion(grabacion: Path) -> str:
    """Cuantas veces delego de verdad. Sale del cable, no de la respuesta."""
    dele = ramas = 0
    try:
        for ln in grabacion.read_text().splitlines():
            try:
                d = json.loads(ln)
            except Exception:
                continue
            for tc in ((d.get("respuesta") or {}).get("tool_calls") or []):
                if (tc.get("nombre") or tc.get("name")) == "delegate_task":
                    dele += 1
                    ramas += 1
    except FileNotFoundError:
        return "sin cable"
    return f"delegate_task={dele}"


if __name__ == "__main__":
    E.ESCENARIOS["fanout"] = (montar_fanout, pedir_fanout, revisar_fanout)
    # Solo este escenario, salvo que se pida otro explicitamente.
    if len(sys.argv) == 1:
        sys.argv.append("fanout")
    codigo = E.main()
    print("DELEGACION", _resumen_delegacion(E.GRABACION))
    sys.exit(codigo)
