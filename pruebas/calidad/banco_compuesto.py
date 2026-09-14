# -*- coding: utf-8 -*-
"""banco_compuesto.py - Tareas con piezas independientes, para medir reparto.

POR QUE EXISTE (22/08/2026)

La bateria (`eval_expertos.TAREAS`) son funciones de 20 lineas: no hay nada que
repartir entre agentes. Este banco tiene tareas con VARIAS piezas que se pueden
escribir en paralelo, y sobre todo un test de INTEGRACION que solo pasa si las
interfaces que eligio cada pieza coinciden entre si.

Ese test de integracion es el punto. Cuando un solo agente escribe todo, las
interfaces le salen coherentes gratis. Cuando cuatro agentes escriben en
paralelo viendo solo su pieza, el riesgo real es que uno devuelva un dict donde
el otro espera una tupla. Los tests por pieza NO detectan eso; el de integracion
si.

Cada tarea trae:
  descripcion  el enunciado global, lo que veria un agente que hace todo
  piezas       [(nombre, spec)] lo que veria cada agente en el modo paralelo
  tests_pieza  {nombre: asserts} para puntuar cada pieza por separado
  integracion  asserts que encadenan las piezas entre si
  referencia   implementacion propia, para VALIDAR que los tests esten bien

La referencia existe porque ya paso una vez en este proyecto que un banco tenia
los tests mal y la medicion no valia. `validar_banco()` ejecuta todos los tests
contra las referencias antes de usar el banco.
"""

TAREAS = [
    {
        "id": "inventario",
        "descripcion": (
            "Escribe un modulo de inventario en Python. El inventario es un dict que "
            "mapea nombre de producto (str) a un dict con las claves 'cantidad' (int) "
            "y 'precio' (float). Implementa estas cuatro funciones:\n"
            "- agregar_item(inv, nombre, cantidad, precio): agrega o suma cantidad a un "
            "producto existente y actualiza su precio. Devuelve el inventario.\n"
            "- quitar_item(inv, nombre, cantidad): resta cantidad. Si queda en 0 o menos, "
            "elimina el producto. Si no existe, no hace nada. Devuelve el inventario.\n"
            "- valor_total(inv): devuelve la suma de cantidad*precio de todos los productos.\n"
            "- bajo_stock(inv, umbral): devuelve la lista de nombres con cantidad menor "
            "al umbral, ordenada alfabeticamente."
        ),
        "piezas": [
            ("agregar_item", "agregar_item(inv, nombre, cantidad, precio): agrega o suma cantidad a un producto existente y actualiza su precio. Devuelve el inventario."),
            ("quitar_item", "quitar_item(inv, nombre, cantidad): resta cantidad. Si queda en 0 o menos, elimina el producto del dict. Si no existe, no hace nada. Devuelve el inventario."),
            ("valor_total", "valor_total(inv): devuelve la suma de cantidad*precio de todos los productos."),
            ("bajo_stock", "bajo_stock(inv, umbral): devuelve la lista de nombres con cantidad menor al umbral, ordenada alfabeticamente."),
        ],
        "tests_pieza": {
            "agregar_item": '''
inv = agregar_item({}, "pan", 5, 2.0)
assert inv["pan"]["cantidad"] == 5 and inv["pan"]["precio"] == 2.0, inv
inv = agregar_item(inv, "pan", 3, 2.5)
assert inv["pan"]["cantidad"] == 8 and inv["pan"]["precio"] == 2.5, inv
''',
            "quitar_item": '''
inv = {"pan": {"cantidad": 5, "precio": 2.0}}
inv = quitar_item(inv, "pan", 2)
assert inv["pan"]["cantidad"] == 3, inv
inv = quitar_item(inv, "pan", 3)
assert "pan" not in inv, inv
inv = quitar_item(inv, "nada", 1)
assert inv == {}, inv
''',
            "valor_total": '''
inv = {"a": {"cantidad": 2, "precio": 3.0}, "b": {"cantidad": 1, "precio": 4.0}}
assert abs(valor_total(inv) - 10.0) < 1e-9, valor_total(inv)
assert valor_total({}) == 0
''',
            "bajo_stock": '''
inv = {"z": {"cantidad": 1, "precio": 1.0}, "a": {"cantidad": 9, "precio": 1.0},
       "m": {"cantidad": 2, "precio": 1.0}}
assert bajo_stock(inv, 5) == ["m", "z"], bajo_stock(inv, 5)
assert bajo_stock(inv, 0) == []
''',
        },
        "integracion": '''
inv = {}
inv = agregar_item(inv, "pan", 10, 2.0)
inv = agregar_item(inv, "leche", 3, 1.5)
inv = agregar_item(inv, "pan", 5, 2.0)
assert abs(valor_total(inv) - 34.5) < 1e-9, valor_total(inv)
inv = quitar_item(inv, "pan", 14)
assert bajo_stock(inv, 4) == ["leche", "pan"], bajo_stock(inv, 4)
inv = quitar_item(inv, "pan", 1)
assert abs(valor_total(inv) - 4.5) < 1e-9, valor_total(inv)
''',
        "referencia": '''
def agregar_item(inv, nombre, cantidad, precio):
    if nombre in inv:
        inv[nombre]["cantidad"] += cantidad
        inv[nombre]["precio"] = precio
    else:
        inv[nombre] = {"cantidad": cantidad, "precio": precio}
    return inv

def quitar_item(inv, nombre, cantidad):
    if nombre not in inv:
        return inv
    inv[nombre]["cantidad"] -= cantidad
    if inv[nombre]["cantidad"] <= 0:
        del inv[nombre]
    return inv

def valor_total(inv):
    return sum(d["cantidad"] * d["precio"] for d in inv.values())

def bajo_stock(inv, umbral):
    return sorted(n for n, d in inv.items() if d["cantidad"] < umbral)
''',
    },
    {
        "id": "logs",
        "descripcion": (
            "Escribe un modulo para analizar logs en Python. Una linea de log tiene el "
            "formato 'NIVEL|timestamp|mensaje', por ejemplo 'ERROR|2026-01-05|fallo la "
            "conexion'. Implementa estas cuatro funciones:\n"
            "- parsear_linea(linea): devuelve un dict con las claves 'nivel' (str en "
            "mayusculas), 'fecha' (str) y 'mensaje' (str). Si la linea no tiene "
            "exactamente 3 partes separadas por '|', devuelve None.\n"
            "- filtrar_nivel(registros, nivel): recibe una lista de dicts como los que "
            "devuelve parsear_linea y devuelve solo los del nivel pedido.\n"
            "- contar_por_nivel(registros): devuelve un dict {nivel: cantidad}.\n"
            "- mas_grave(registros): devuelve el dict del registro de mayor gravedad, "
            "segun el orden ERROR > WARN > INFO > DEBUG. Si hay empate devuelve el "
            "primero. Con lista vacia devuelve None."
        ),
        "piezas": [
            ("parsear_linea", "parsear_linea(linea): la linea tiene formato 'NIVEL|timestamp|mensaje'. Devuelve un dict con las claves 'nivel' (str en mayusculas), 'fecha' (str) y 'mensaje' (str). Si la linea no tiene exactamente 3 partes separadas por '|', devuelve None."),
            ("filtrar_nivel", "filtrar_nivel(registros, nivel): recibe una lista de dicts con claves 'nivel', 'fecha' y 'mensaje'. Devuelve solo los del nivel pedido."),
            ("contar_por_nivel", "contar_por_nivel(registros): recibe una lista de dicts con claves 'nivel', 'fecha' y 'mensaje'. Devuelve un dict {nivel: cantidad}."),
            ("mas_grave", "mas_grave(registros): recibe una lista de dicts con claves 'nivel', 'fecha' y 'mensaje'. Devuelve el dict del registro de mayor gravedad segun ERROR > WARN > INFO > DEBUG. Si hay empate devuelve el primero. Con lista vacia devuelve None."),
        ],
        "tests_pieza": {
            "parsear_linea": '''
r = parsear_linea("ERROR|2026-01-05|fallo")
assert r == {"nivel": "ERROR", "fecha": "2026-01-05", "mensaje": "fallo"}, r
assert parsear_linea("basura") is None
assert parsear_linea("A|B") is None
''',
            "filtrar_nivel": '''
regs = [{"nivel": "ERROR", "fecha": "d", "mensaje": "m1"},
        {"nivel": "INFO", "fecha": "d", "mensaje": "m2"}]
assert filtrar_nivel(regs, "ERROR") == [regs[0]], filtrar_nivel(regs, "ERROR")
assert filtrar_nivel(regs, "DEBUG") == []
''',
            "contar_por_nivel": '''
regs = [{"nivel": "ERROR", "fecha": "d", "mensaje": "m"},
        {"nivel": "INFO", "fecha": "d", "mensaje": "m"},
        {"nivel": "ERROR", "fecha": "d", "mensaje": "m"}]
assert contar_por_nivel(regs) == {"ERROR": 2, "INFO": 1}, contar_por_nivel(regs)
assert contar_por_nivel([]) == {}
''',
            "mas_grave": '''
regs = [{"nivel": "INFO", "fecha": "d", "mensaje": "m1"},
        {"nivel": "ERROR", "fecha": "d", "mensaje": "m2"},
        {"nivel": "WARN", "fecha": "d", "mensaje": "m3"}]
assert mas_grave(regs)["mensaje"] == "m2", mas_grave(regs)
assert mas_grave([]) is None
''',
        },
        "integracion": '''
lineas = ["INFO|2026-01-01|arranco", "ERROR|2026-01-02|se cayo",
          "basura sin formato", "WARN|2026-01-03|lento",
          "ERROR|2026-01-04|otra vez"]
regs = [r for r in (parsear_linea(l) for l in lineas) if r is not None]
assert len(regs) == 4, len(regs)
assert contar_por_nivel(regs) == {"INFO": 1, "ERROR": 2, "WARN": 1}, contar_por_nivel(regs)
assert len(filtrar_nivel(regs, "ERROR")) == 2
assert mas_grave(regs)["mensaje"] == "se cayo", mas_grave(regs)
assert mas_grave(filtrar_nivel(regs, "WARN"))["mensaje"] == "lento"
''',
        "referencia": '''
_ORDEN = {"ERROR": 3, "WARN": 2, "INFO": 1, "DEBUG": 0}

def parsear_linea(linea):
    partes = linea.split("|")
    if len(partes) != 3:
        return None
    return {"nivel": partes[0].upper(), "fecha": partes[1], "mensaje": partes[2]}

def filtrar_nivel(registros, nivel):
    return [r for r in registros if r["nivel"] == nivel]

def contar_por_nivel(registros):
    out = {}
    for r in registros:
        out[r["nivel"]] = out.get(r["nivel"], 0) + 1
    return out

def mas_grave(registros):
    if not registros:
        return None
    mejor = registros[0]
    for r in registros[1:]:
        if _ORDEN.get(r["nivel"], -1) > _ORDEN.get(mejor["nivel"], -1):
            mejor = r
    return mejor
''',
    },
    {
        "id": "carrito",
        "descripcion": (
            "Escribe un modulo de carrito de compras en Python. Un carrito es una lista "
            "de dicts con las claves 'producto' (str), 'cantidad' (int) y 'precio' "
            "(float). Implementa estas cuatro funciones:\n"
            "- agregar(carrito, producto, cantidad, precio): si el producto ya esta, le "
            "suma la cantidad; si no, lo agrega al final. Devuelve el carrito.\n"
            "- subtotal(carrito): suma de cantidad*precio de todas las lineas.\n"
            "- aplicar_descuento(monto, porcentaje): devuelve el monto con el porcentaje "
            "descontado. Si el porcentaje no esta entre 0 y 100 devuelve el monto sin tocar.\n"
            "- resumen(carrito, porcentaje): devuelve un dict con las claves 'lineas' "
            "(cantidad de productos distintos), 'subtotal' y 'total' (el subtotal con el "
            "descuento aplicado)."
        ),
        "piezas": [
            ("agregar", "agregar(carrito, producto, cantidad, precio): el carrito es una lista de dicts con claves 'producto', 'cantidad' y 'precio'. Si el producto ya esta, le suma la cantidad; si no, lo agrega al final. Devuelve el carrito."),
            ("subtotal", "subtotal(carrito): el carrito es una lista de dicts con claves 'producto', 'cantidad' y 'precio'. Devuelve la suma de cantidad*precio de todas las lineas."),
            ("aplicar_descuento", "aplicar_descuento(monto, porcentaje): devuelve el monto con el porcentaje descontado. Si el porcentaje no esta entre 0 y 100 devuelve el monto sin tocar."),
            ("resumen", "resumen(carrito, porcentaje): el carrito es una lista de dicts con claves 'producto', 'cantidad' y 'precio'. Devuelve un dict con las claves 'lineas' (cantidad de productos distintos), 'subtotal' y 'total' (el subtotal con el descuento aplicado). Puedes usar las funciones subtotal(carrito) y aplicar_descuento(monto, porcentaje), que ya existen."),
        ],
        "tests_pieza": {
            "agregar": '''
c = agregar([], "pan", 2, 1.5)
assert c == [{"producto": "pan", "cantidad": 2, "precio": 1.5}], c
c = agregar(c, "pan", 3, 1.5)
assert len(c) == 1 and c[0]["cantidad"] == 5, c
c = agregar(c, "leche", 1, 2.0)
assert len(c) == 2 and c[1]["producto"] == "leche", c
''',
            "subtotal": '''
c = [{"producto": "a", "cantidad": 2, "precio": 3.0},
     {"producto": "b", "cantidad": 1, "precio": 4.0}]
assert abs(subtotal(c) - 10.0) < 1e-9, subtotal(c)
assert subtotal([]) == 0
''',
            "aplicar_descuento": '''
assert abs(aplicar_descuento(100.0, 10) - 90.0) < 1e-9
assert abs(aplicar_descuento(100.0, 0) - 100.0) < 1e-9
assert abs(aplicar_descuento(100.0, 150) - 100.0) < 1e-9
assert abs(aplicar_descuento(100.0, -5) - 100.0) < 1e-9
''',
            "resumen": '''
c = [{"producto": "a", "cantidad": 2, "precio": 3.0},
     {"producto": "b", "cantidad": 1, "precio": 4.0}]
r = resumen(c, 10)
assert r["lineas"] == 2, r
assert abs(r["subtotal"] - 10.0) < 1e-9, r
assert abs(r["total"] - 9.0) < 1e-9, r
''',
        },
        "integracion": '''
c = []
c = agregar(c, "pan", 2, 1.5)
c = agregar(c, "leche", 1, 2.0)
c = agregar(c, "pan", 2, 1.5)
assert len(c) == 2, c
assert abs(subtotal(c) - 8.0) < 1e-9, subtotal(c)
r = resumen(c, 25)
assert r["lineas"] == 2 and abs(r["subtotal"] - 8.0) < 1e-9, r
assert abs(r["total"] - 6.0) < 1e-9, r
assert abs(aplicar_descuento(subtotal(c), 25) - r["total"]) < 1e-9
''',
        "referencia": '''
def agregar(carrito, producto, cantidad, precio):
    for linea in carrito:
        if linea["producto"] == producto:
            linea["cantidad"] += cantidad
            return carrito
    carrito.append({"producto": producto, "cantidad": cantidad, "precio": precio})
    return carrito

def subtotal(carrito):
    return sum(l["cantidad"] * l["precio"] for l in carrito)

def aplicar_descuento(monto, porcentaje):
    if porcentaje < 0 or porcentaje > 100:
        return monto
    return monto * (1 - porcentaje / 100)

def resumen(carrito, porcentaje):
    s = subtotal(carrito)
    return {"lineas": len(carrito), "subtotal": s,
            "total": aplicar_descuento(s, porcentaje)}
''',
    },
    {
        "id": "texto",
        "descripcion": (
            "Escribe un modulo de estadisticas de texto en Python. Implementa estas "
            "cuatro funciones:\n"
            "- normalizar(texto): devuelve el texto en minusculas y sin los signos "
            ".,;:!? (los reemplaza por nada). Los espacios se mantienen.\n"
            "- palabras(texto): devuelve la lista de palabras del texto ya normalizado, "
            "separando por espacios y descartando las vacias.\n"
            "- frecuencias(lista_palabras): devuelve un dict {palabra: cantidad}.\n"
            "- top_n(frecs, n): recibe el dict de frecuencias y devuelve la lista de las "
            "n palabras mas frecuentes como tuplas (palabra, cantidad), ordenadas por "
            "cantidad descendente y, en caso de empate, alfabeticamente."
        ),
        "piezas": [
            ("normalizar", "normalizar(texto): devuelve el texto en minusculas y sin los signos .,;:!? (los reemplaza por nada). Los espacios se mantienen."),
            ("palabras", "palabras(texto): recibe un texto ya normalizado (minusculas, sin signos de puntuacion). Devuelve la lista de palabras separando por espacios y descartando las vacias."),
            ("frecuencias", "frecuencias(lista_palabras): recibe una lista de strings. Devuelve un dict {palabra: cantidad}."),
            ("top_n", "top_n(frecs, n): recibe un dict {palabra: cantidad}. Devuelve la lista de las n palabras mas frecuentes como tuplas (palabra, cantidad), ordenadas por cantidad descendente y, en caso de empate, alfabeticamente."),
        ],
        "tests_pieza": {
            "normalizar": '''
assert normalizar("Hola, Mundo!") == "hola mundo", repr(normalizar("Hola, Mundo!"))
assert normalizar("A.B;C:D?E!F,G") == "abcdefg", repr(normalizar("A.B;C:D?E!F,G"))
assert normalizar("") == ""
''',
            "palabras": '''
assert palabras("hola mundo") == ["hola", "mundo"]
assert palabras("  a   b  ") == ["a", "b"], palabras("  a   b  ")
assert palabras("") == []
''',
            "frecuencias": '''
assert frecuencias(["a", "b", "a"]) == {"a": 2, "b": 1}
assert frecuencias([]) == {}
''',
            "top_n": '''
f = {"a": 3, "b": 5, "c": 3}
assert top_n(f, 2) == [("b", 5), ("a", 3)], top_n(f, 2)
assert top_n(f, 3) == [("b", 5), ("a", 3), ("c", 3)], top_n(f, 3)
assert top_n({}, 2) == []
''',
        },
        "integracion": '''
texto = "El perro corre. El gato duerme! El perro ladra?"
p = palabras(normalizar(texto))
assert "perro" in p and "." not in "".join(p), p
f = frecuencias(p)
assert f["el"] == 3 and f["perro"] == 2, f
t = top_n(f, 2)
assert t[0] == ("el", 3), t
assert t[1] == ("perro", 2), t
assert len(top_n(f, 100)) == len(f)
''',
        "referencia": '''
def normalizar(texto):
    out = texto.lower()
    for c in ".,;:!?":
        out = out.replace(c, "")
    return out

def palabras(texto):
    return [p for p in texto.split(" ") if p]

def frecuencias(lista_palabras):
    out = {}
    for p in lista_palabras:
        out[p] = out.get(p, 0) + 1
    return out

def top_n(frecs, n):
    return sorted(frecs.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
''',
    },
]
