# -*- coding: utf-8 -*-
"""banco_compuesto_grande.py - Tareas con 10 y 12 piezas, para cruzar el umbral.

POR QUE EXISTE (22/08/2026)

`banco_compuesto.py` tiene tareas de 4 piezas y dio 20/20 de integracion. Pero
el umbral de kernel de llama.cpp esta en 9 pedidos simultaneos: con 4 piezas se
queda debajo y se pierde el salto (8 agentes 214,9 tok/s contra 10 agentes
352,7).

Para aprovecharlo hacen falta 9 piezas o mas. La pregunta es si la integracion
aguanta con esa granularidad: el 20/20 se logro con CUATRO funciones de frontera
natural, y no esta dicho que 10 o 12 agentes que no se ven entre si sigan
produciendo piezas que encajen.

Estas tareas son modulos con muchas funciones NATURALES (no una tarea pequeña
troceada a la fuerza), que es lo que se parece al trabajo real. Mismo formato
que el banco pequeño, mismo validador (`validar_banco_compuesto.py`).
"""

TAREAS_GRANDES = [
    {
        "id": "biblioteca",
        "n_piezas": 10,
        "descripcion": (
            "Escribe un modulo de gestion de biblioteca en Python. Un libro es un dict "
            "con las claves 'titulo' (str), 'autor' (str), 'anio' (int) y 'prestado' "
            "(bool). La biblioteca es una lista de libros. Implementa estas diez "
            "funciones:\n"
            "- crear_libro(titulo, autor, anio): devuelve el dict del libro con "
            "'prestado' en False.\n"
            "- agregar_libro(bib, libro): agrega el libro al final. Si ya hay uno con el "
            "mismo titulo, no lo agrega. Devuelve la biblioteca.\n"
            "- buscar_por_titulo(bib, titulo): devuelve el libro con ese titulo, o None.\n"
            "- buscar_por_autor(bib, autor): devuelve la lista de libros de ese autor, "
            "ordenada por anio ascendente.\n"
            "- prestar(bib, titulo): si el libro existe y no esta prestado, lo marca "
            "prestado y devuelve True. Si no, devuelve False.\n"
            "- devolver(bib, titulo): si el libro existe y esta prestado, lo desmarca y "
            "devuelve True. Si no, devuelve False.\n"
            "- disponibles(bib): lista de titulos no prestados, ordenada alfabeticamente.\n"
            "- prestados(bib): lista de titulos prestados, ordenada alfabeticamente.\n"
            "- contar_por_decada(bib): dict {decada: cantidad}, donde la decada es "
            "anio // 10 * 10.\n"
            "- mas_antiguo(bib): el libro de menor anio. Con biblioteca vacia devuelve "
            "None."
        ),
        "piezas": [
            ("crear_libro", "crear_libro(titulo, autor, anio): devuelve un dict con las claves 'titulo', 'autor', 'anio' y 'prestado', esta ultima en False."),
            ("agregar_libro", "agregar_libro(bib, libro): la biblioteca es una lista de dicts con claves 'titulo', 'autor', 'anio' y 'prestado'. Agrega el libro al final. Si ya hay uno con el mismo titulo, no lo agrega. Devuelve la biblioteca."),
            ("buscar_por_titulo", "buscar_por_titulo(bib, titulo): la biblioteca es una lista de dicts con clave 'titulo'. Devuelve el libro con ese titulo, o None si no esta."),
            ("buscar_por_autor", "buscar_por_autor(bib, autor): la biblioteca es una lista de dicts con claves 'autor' y 'anio'. Devuelve la lista de libros de ese autor, ordenada por anio ascendente."),
            ("prestar", "prestar(bib, titulo): la biblioteca es una lista de dicts con claves 'titulo' y 'prestado'. Si el libro existe y 'prestado' es False, lo pone en True y devuelve True. Si no existe o ya estaba prestado, devuelve False."),
            ("devolver", "devolver(bib, titulo): la biblioteca es una lista de dicts con claves 'titulo' y 'prestado'. Si el libro existe y 'prestado' es True, lo pone en False y devuelve True. Si no existe o no estaba prestado, devuelve False."),
            ("disponibles", "disponibles(bib): la biblioteca es una lista de dicts con claves 'titulo' y 'prestado'. Devuelve la lista de titulos con 'prestado' en False, ordenada alfabeticamente."),
            ("prestados", "prestados(bib): la biblioteca es una lista de dicts con claves 'titulo' y 'prestado'. Devuelve la lista de titulos con 'prestado' en True, ordenada alfabeticamente."),
            ("contar_por_decada", "contar_por_decada(bib): la biblioteca es una lista de dicts con clave 'anio'. Devuelve un dict {decada: cantidad} donde la decada se calcula como anio // 10 * 10."),
            ("mas_antiguo", "mas_antiguo(bib): la biblioteca es una lista de dicts con clave 'anio'. Devuelve el libro de menor anio. Con lista vacia devuelve None."),
        ],
        "tests_pieza": {
            "crear_libro": '''
l = crear_libro("A", "X", 1990)
assert l["titulo"] == "A" and l["autor"] == "X" and l["anio"] == 1990, l
assert l["prestado"] is False, l
''',
            "agregar_libro": '''
bib = agregar_libro([], {"titulo": "A", "autor": "X", "anio": 1, "prestado": False})
assert len(bib) == 1, bib
bib = agregar_libro(bib, {"titulo": "A", "autor": "Y", "anio": 2, "prestado": False})
assert len(bib) == 1, bib
bib = agregar_libro(bib, {"titulo": "B", "autor": "Y", "anio": 2, "prestado": False})
assert len(bib) == 2 and bib[1]["titulo"] == "B", bib
''',
            "buscar_por_titulo": '''
bib = [{"titulo": "A", "autor": "X", "anio": 1, "prestado": False},
       {"titulo": "B", "autor": "Y", "anio": 2, "prestado": False}]
assert buscar_por_titulo(bib, "B")["autor"] == "Y"
assert buscar_por_titulo(bib, "Z") is None
assert buscar_por_titulo([], "A") is None
''',
            "buscar_por_autor": '''
bib = [{"titulo": "A", "autor": "X", "anio": 2000, "prestado": False},
       {"titulo": "B", "autor": "X", "anio": 1990, "prestado": False},
       {"titulo": "C", "autor": "Y", "anio": 1980, "prestado": False}]
r = buscar_por_autor(bib, "X")
assert [x["titulo"] for x in r] == ["B", "A"], r
assert buscar_por_autor(bib, "Z") == []
''',
            "prestar": '''
bib = [{"titulo": "A", "autor": "X", "anio": 1, "prestado": False}]
assert prestar(bib, "A") is True
assert bib[0]["prestado"] is True
assert prestar(bib, "A") is False
assert prestar(bib, "Z") is False
''',
            "devolver": '''
bib = [{"titulo": "A", "autor": "X", "anio": 1, "prestado": True}]
assert devolver(bib, "A") is True
assert bib[0]["prestado"] is False
assert devolver(bib, "A") is False
assert devolver(bib, "Z") is False
''',
            "disponibles": '''
bib = [{"titulo": "Z", "autor": "X", "anio": 1, "prestado": False},
       {"titulo": "A", "autor": "X", "anio": 1, "prestado": False},
       {"titulo": "M", "autor": "X", "anio": 1, "prestado": True}]
assert disponibles(bib) == ["A", "Z"], disponibles(bib)
assert disponibles([]) == []
''',
            "prestados": '''
bib = [{"titulo": "Z", "autor": "X", "anio": 1, "prestado": True},
       {"titulo": "A", "autor": "X", "anio": 1, "prestado": True},
       {"titulo": "M", "autor": "X", "anio": 1, "prestado": False}]
assert prestados(bib) == ["A", "Z"], prestados(bib)
assert prestados([]) == []
''',
            "contar_por_decada": '''
bib = [{"titulo": "A", "autor": "X", "anio": 1995, "prestado": False},
       {"titulo": "B", "autor": "X", "anio": 1999, "prestado": False},
       {"titulo": "C", "autor": "X", "anio": 2001, "prestado": False}]
assert contar_por_decada(bib) == {1990: 2, 2000: 1}, contar_por_decada(bib)
assert contar_por_decada([]) == {}
''',
            "mas_antiguo": '''
bib = [{"titulo": "A", "autor": "X", "anio": 2000, "prestado": False},
       {"titulo": "B", "autor": "X", "anio": 1980, "prestado": False}]
assert mas_antiguo(bib)["titulo"] == "B", mas_antiguo(bib)
assert mas_antiguo([]) is None
''',
        },
        "integracion": '''
bib = []
bib = agregar_libro(bib, crear_libro("Rayuela", "Cortazar", 1963))
bib = agregar_libro(bib, crear_libro("Ficciones", "Borges", 1944))
bib = agregar_libro(bib, crear_libro("El Aleph", "Borges", 1949))
bib = agregar_libro(bib, crear_libro("Rayuela", "Otro", 1999))
assert len(bib) == 3, bib
assert [x["titulo"] for x in buscar_por_autor(bib, "Borges")] == ["Ficciones", "El Aleph"]
assert prestar(bib, "Ficciones") is True
assert prestar(bib, "Ficciones") is False
assert prestados(bib) == ["Ficciones"], prestados(bib)
assert disponibles(bib) == ["El Aleph", "Rayuela"], disponibles(bib)
assert devolver(bib, "Ficciones") is True
assert prestados(bib) == []
assert buscar_por_titulo(bib, "El Aleph")["anio"] == 1949
assert contar_por_decada(bib) == {1960: 1, 1940: 2}, contar_por_decada(bib)
assert mas_antiguo(bib)["titulo"] == "Ficciones", mas_antiguo(bib)
''',
        "referencia": '''
def crear_libro(titulo, autor, anio):
    return {"titulo": titulo, "autor": autor, "anio": anio, "prestado": False}

def agregar_libro(bib, libro):
    for l in bib:
        if l["titulo"] == libro["titulo"]:
            return bib
    bib.append(libro)
    return bib

def buscar_por_titulo(bib, titulo):
    for l in bib:
        if l["titulo"] == titulo:
            return l
    return None

def buscar_por_autor(bib, autor):
    return sorted((l for l in bib if l["autor"] == autor), key=lambda l: l["anio"])

def prestar(bib, titulo):
    l = buscar_por_titulo(bib, titulo)
    if l is None or l["prestado"]:
        return False
    l["prestado"] = True
    return True

def devolver(bib, titulo):
    l = buscar_por_titulo(bib, titulo)
    if l is None or not l["prestado"]:
        return False
    l["prestado"] = False
    return True

def disponibles(bib):
    return sorted(l["titulo"] for l in bib if not l["prestado"])

def prestados(bib):
    return sorted(l["titulo"] for l in bib if l["prestado"])

def contar_por_decada(bib):
    out = {}
    for l in bib:
        d = l["anio"] // 10 * 10
        out[d] = out.get(d, 0) + 1
    return out

def mas_antiguo(bib):
    if not bib:
        return None
    mejor = bib[0]
    for l in bib[1:]:
        if l["anio"] < mejor["anio"]:
            mejor = l
    return mejor
''',
    },
    {
        "id": "notas",
        "n_piezas": 12,
        "descripcion": (
            "Escribe un modulo de estadisticas de notas en Python. Una fila es un dict "
            "con las claves 'alumno' (str), 'materia' (str) y 'nota' (float). Implementa "
            "estas doce funciones:\n"
            "- parsear_fila(linea): la linea tiene formato 'alumno,materia,nota'. Devuelve "
            "el dict con 'nota' convertida a float. Si no tiene 3 partes o la nota no es "
            "un numero, devuelve None.\n"
            "- nota_valida(nota): True si la nota esta entre 0 y 10 inclusive.\n"
            "- promedio(notas): promedio de una lista de numeros. Con lista vacia "
            "devuelve 0.0.\n"
            "- maximo(notas): el mayor de una lista de numeros. Con lista vacia devuelve "
            "None.\n"
            "- minimo(notas): el menor de una lista de numeros. Con lista vacia devuelve "
            "None.\n"
            "- notas_de(filas, alumno): lista de las notas de ese alumno, en el orden en "
            "que aparecen.\n"
            "- agrupar_por_materia(filas): dict {materia: [filas de esa materia]}.\n"
            "- promedio_por_materia(filas): dict {materia: promedio de sus notas}.\n"
            "- aprobados(filas, corte): lista de alumnos distintos con al menos una nota "
            "mayor o igual al corte, ordenada alfabeticamente.\n"
            "- alumnos(filas): lista de alumnos distintos, ordenada alfabeticamente.\n"
            "- formatear_nota(nota): el numero como string con exactamente dos decimales.\n"
            "- resumen(filas): dict con las claves 'filas' (cantidad), 'alumnos' "
            "(cantidad de alumnos distintos) y 'promedio' (promedio de todas las notas)."
        ),
        "piezas": [
            ("parsear_fila", "parsear_fila(linea): la linea tiene formato 'alumno,materia,nota'. Devuelve un dict con las claves 'alumno' (str), 'materia' (str) y 'nota' (float). Si no tiene exactamente 3 partes separadas por coma, o la nota no se puede convertir a float, devuelve None."),
            ("nota_valida", "nota_valida(nota): devuelve True si el numero esta entre 0 y 10 inclusive, False si no."),
            ("promedio", "promedio(notas): recibe una lista de numeros. Devuelve el promedio. Con lista vacia devuelve 0.0."),
            ("maximo", "maximo(notas): recibe una lista de numeros. Devuelve el mayor. Con lista vacia devuelve None."),
            ("minimo", "minimo(notas): recibe una lista de numeros. Devuelve el menor. Con lista vacia devuelve None."),
            ("notas_de", "notas_de(filas, alumno): recibe una lista de dicts con claves 'alumno', 'materia' y 'nota'. Devuelve la lista de notas de ese alumno, en el orden en que aparecen."),
            ("agrupar_por_materia", "agrupar_por_materia(filas): recibe una lista de dicts con claves 'alumno', 'materia' y 'nota'. Devuelve un dict {materia: lista de las filas de esa materia}."),
            ("promedio_por_materia", "promedio_por_materia(filas): recibe una lista de dicts con claves 'alumno', 'materia' y 'nota'. Devuelve un dict {materia: promedio de las notas de esa materia}."),
            ("aprobados", "aprobados(filas, corte): recibe una lista de dicts con claves 'alumno', 'materia' y 'nota'. Devuelve la lista de alumnos distintos que tienen al menos una nota mayor o igual al corte, ordenada alfabeticamente."),
            ("alumnos", "alumnos(filas): recibe una lista de dicts con clave 'alumno'. Devuelve la lista de alumnos distintos, ordenada alfabeticamente."),
            ("formatear_nota", "formatear_nota(nota): recibe un numero y devuelve el string con exactamente dos decimales."),
            ("resumen", "resumen(filas): recibe una lista de dicts con claves 'alumno', 'materia' y 'nota'. Devuelve un dict con las claves 'filas' (cantidad de filas), 'alumnos' (cantidad de alumnos distintos) y 'promedio' (promedio de todas las notas, 0.0 si no hay filas)."),
        ],
        "tests_pieza": {
            "parsear_fila": """
r = parsear_fila("ana,mate,7.5")
assert r == {"alumno": "ana", "materia": "mate", "nota": 7.5}, r
assert parsear_fila("ana,mate") is None
assert parsear_fila("ana,mate,x") is None
""",
            "nota_valida": """
assert nota_valida(0) is True and nota_valida(10) is True
assert nota_valida(5.5) is True
assert nota_valida(-1) is False and nota_valida(11) is False
""",
            "promedio": """
assert abs(promedio([1, 2, 3]) - 2.0) < 1e-9
assert promedio([]) == 0.0
""",
            "maximo": """
assert maximo([1, 5, 3]) == 5
assert maximo([]) is None
""",
            "minimo": """
assert minimo([4, 1, 3]) == 1
assert minimo([]) is None
""",
            "notas_de": """
f = [{"alumno": "a", "materia": "m", "nota": 1.0},
     {"alumno": "b", "materia": "m", "nota": 2.0},
     {"alumno": "a", "materia": "n", "nota": 3.0}]
assert notas_de(f, "a") == [1.0, 3.0], notas_de(f, "a")
assert notas_de(f, "z") == []
""",
            "agrupar_por_materia": """
f = [{"alumno": "a", "materia": "m", "nota": 1.0},
     {"alumno": "b", "materia": "n", "nota": 2.0},
     {"alumno": "c", "materia": "m", "nota": 3.0}]
g = agrupar_por_materia(f)
assert set(g.keys()) == {"m", "n"}, g
assert len(g["m"]) == 2 and len(g["n"]) == 1, g
assert agrupar_por_materia([]) == {}
""",
            "promedio_por_materia": """
f = [{"alumno": "a", "materia": "m", "nota": 2.0},
     {"alumno": "b", "materia": "m", "nota": 4.0},
     {"alumno": "c", "materia": "n", "nota": 5.0}]
p = promedio_por_materia(f)
assert abs(p["m"] - 3.0) < 1e-9 and abs(p["n"] - 5.0) < 1e-9, p
assert promedio_por_materia([]) == {}
""",
            "aprobados": """
f = [{"alumno": "zoe", "materia": "m", "nota": 4.0},
     {"alumno": "ana", "materia": "m", "nota": 8.0},
     {"alumno": "zoe", "materia": "n", "nota": 9.0}]
assert aprobados(f, 6) == ["ana", "zoe"], aprobados(f, 6)
assert aprobados(f, 10) == []
""",
            "alumnos": """
f = [{"alumno": "zoe"}, {"alumno": "ana"}, {"alumno": "zoe"}]
assert alumnos(f) == ["ana", "zoe"], alumnos(f)
assert alumnos([]) == []
""",
            "formatear_nota": """
assert formatear_nota(7) == "7.00", formatear_nota(7)
assert formatear_nota(7.5) == "7.50", formatear_nota(7.5)
assert formatear_nota(7.456) == "7.46", formatear_nota(7.456)
""",
            "resumen": """
f = [{"alumno": "a", "materia": "m", "nota": 2.0},
     {"alumno": "b", "materia": "m", "nota": 4.0},
     {"alumno": "a", "materia": "n", "nota": 6.0}]
r = resumen(f)
assert r["filas"] == 3 and r["alumnos"] == 2, r
assert abs(r["promedio"] - 4.0) < 1e-9, r
""",
        },
        "integracion": """
lineas = ["ana,mate,8.0", "zoe,mate,4.0", "ana,lengua,6.0",
          "basura", "zoe,lengua,9.5", "ana,mate,x"]
filas = [f for f in (parsear_fila(l) for l in lineas) if f is not None]
assert len(filas) == 4, filas
assert all(nota_valida(f["nota"]) for f in filas)
assert alumnos(filas) == ["ana", "zoe"], alumnos(filas)
assert notas_de(filas, "ana") == [8.0, 6.0], notas_de(filas, "ana")
assert abs(promedio(notas_de(filas, "ana")) - 7.0) < 1e-9
assert maximo(notas_de(filas, "zoe")) == 9.5
assert minimo(notas_de(filas, "zoe")) == 4.0
g = agrupar_por_materia(filas)
assert len(g["mate"]) == 2 and len(g["lengua"]) == 2, g
p = promedio_por_materia(filas)
assert abs(p["mate"] - 6.0) < 1e-9, p
assert aprobados(filas, 6) == ["ana", "zoe"], aprobados(filas, 6)
assert aprobados(filas, 9) == ["zoe"], aprobados(filas, 9)
assert formatear_nota(p["mate"]) == "6.00", formatear_nota(p["mate"])
r = resumen(filas)
assert r["filas"] == 4 and r["alumnos"] == 2, r
assert abs(r["promedio"] - 6.875) < 1e-9, r
""",
        "referencia": """
def parsear_fila(linea):
    partes = linea.split(",")
    if len(partes) != 3:
        return None
    try:
        nota = float(partes[2])
    except ValueError:
        return None
    return {"alumno": partes[0], "materia": partes[1], "nota": nota}

def nota_valida(nota):
    return 0 <= nota <= 10

def promedio(notas):
    if not notas:
        return 0.0
    return sum(notas) / len(notas)

def maximo(notas):
    return max(notas) if notas else None

def minimo(notas):
    return min(notas) if notas else None

def notas_de(filas, alumno):
    return [f["nota"] for f in filas if f["alumno"] == alumno]

def agrupar_por_materia(filas):
    out = {}
    for f in filas:
        out.setdefault(f["materia"], []).append(f)
    return out

def promedio_por_materia(filas):
    return {m: promedio([f["nota"] for f in fs])
            for m, fs in agrupar_por_materia(filas).items()}

def aprobados(filas, corte):
    return sorted({f["alumno"] for f in filas if f["nota"] >= corte})

def alumnos(filas):
    return sorted({f["alumno"] for f in filas})

def formatear_nota(nota):
    return f"{nota:.2f}"

def resumen(filas):
    return {"filas": len(filas), "alumnos": len(alumnos(filas)),
            "promedio": promedio([f["nota"] for f in filas])}
""",
    },
]
