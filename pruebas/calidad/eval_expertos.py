# -*- coding: utf-8 -*-
"""
eval_expertos.py - ¿Un experto pequeño le gana a un generalista del mismo tamaño?

Prueba un backend ya iniciado y evalúa:
  - CÓDIGO: objetivo. Se extrae la función, se EJECUTA contra casos de prueba
    en un subproceso con timeout. No se juzga por apariencia.
  - RAZONAMIENTO: tambien objetivo desde 17/08/2026. Cada pregunta declara los
    conceptos que una respuesta correcta debe mencionar; se verifica por texto
    normalizado. Una de las 4 es una TRAMPA (premisa falsa) para medir si el
    modelo razona o si le sigue la corriente al que pregunta.

Uso:  python eval_expertos.py <puerto> <etiqueta>
Ej:   python eval_expertos.py 8083 especialista
"""
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUERTO = sys.argv[1] if len(sys.argv) > 1 else "8083"
ETIQUETA = sys.argv[2] if len(sys.argv) > 2 else "modelo"
URL = f"http://127.0.0.1:{PUERTO}/v1/chat/completions"

INSTRUCCION = ("Responde SOLO con el codigo Python pedido, dentro de un bloque "
               "```python. Sin explicaciones, sin ejemplos de uso.")

# ─── Batería de código: cada tarea se verifica EJECUTANDO ────────────────────
TAREAS = [
    {
        "id": "fizzbuzz",
        "prompt": "Escribe una funcion fizzbuzz(n) que devuelva una lista de strings del 1 al n, "
                  "donde los multiplos de 3 son 'Fizz', los de 5 'Buzz' y los de ambos 'FizzBuzz'. "
                  "El resto, el numero como string.",
        "tests": """
r = fizzbuzz(15)
assert len(r) == 15, r
assert r[0] == "1" and r[1] == "2"
assert r[2] == "Fizz" and r[4] == "Buzz" and r[14] == "FizzBuzz"
assert r[8] == "Fizz" and r[9] == "Buzz"
""",
    },
    {
        "id": "duracion",
        "prompt": "Escribe una funcion parsear_duracion(s) que reciba un string como '1h30m', '45m' o '2h' "
                  "y devuelva la cantidad total de MINUTOS como entero.",
        "tests": """
assert parsear_duracion("1h30m") == 90
assert parsear_duracion("45m") == 45
assert parsear_duracion("2h") == 120
assert parsear_duracion("3h15m") == 195
""",
    },
    {
        "id": "palindromo",
        "prompt": "Escribe una funcion es_palindromo(s) que devuelva True si el string es palindromo, "
                  "ignorando mayusculas, espacios y signos de puntuacion.",
        "tests": """
assert es_palindromo("Anita lava la tina") is True
assert es_palindromo("A man, a plan, a canal: Panama") is True
assert es_palindromo("hola mundo") is False
assert es_palindromo("") is True
""",
    },
    {
        "id": "aplanar",
        "prompt": "Escribe una funcion aplanar(lista) que reciba una lista con sublistas anidadas "
                  "a cualquier profundidad y devuelva una lista plana con todos los elementos.",
        "tests": """
assert aplanar([1, [2, 3], [4, [5, [6]]]]) == [1,2,3,4,5,6]
assert aplanar([]) == []
assert aplanar([[], [1], [[2]]]) == [1,2]
""",
    },
    {
        "id": "busqueda",
        "prompt": "Escribe una funcion buscar(lista, x) que haga busqueda BINARIA sobre una lista "
                  "ordenada y devuelva el indice de x, o -1 si no esta.",
        "tests": """
l = [1,3,5,7,9,11,13]
assert buscar(l, 7) == 3
assert buscar(l, 1) == 0
assert buscar(l, 13) == 6
assert buscar(l, 8) == -1
assert buscar([], 5) == -1
""",
    },
    {
        "id": "agrupar",
        "prompt": "Escribe una funcion agrupar_por(items, clave) que reciba una lista de diccionarios "
                  "y el nombre de una clave, y devuelva un diccionario que agrupe los items por el "
                  "valor de esa clave.",
        "tests": """
datos = [{"t":"a","v":1},{"t":"b","v":2},{"t":"a","v":3}]
r = agrupar_por(datos, "t")
assert set(r.keys()) == {"a","b"}
assert len(r["a"]) == 2 and len(r["b"]) == 1
assert r["a"][0]["v"] == 1 and r["a"][1]["v"] == 3
""",
    },
    # ─── Ampliacion a 25 tareas ──────────────────────────────────────────────
    # Con 6 tareas, una de diferencia no distingue capacidad de azar. Todas usan
    # SOLO la biblioteca estandar: importar pandas mediria que este instalado, no
    # la capacidad del modelo. Cada enunciado fija el comportamiento de los casos
    # que se prueban, para que un fallo sea un fallo y no un malentendido.
    {
        "id": "contar_palabras",
        "prompt": "Escribe una funcion contar_palabras(texto) que devuelva un diccionario con "
                  "cuantas veces aparece cada palabra. Ignora mayusculas y signos de puntuacion.",
        "tests": """
r = contar_palabras("Hola hola, mundo!")
assert r == {"hola": 2, "mundo": 1}, r
assert contar_palabras("") == {}
""",
    },
    {
        "id": "rotar",
        "prompt": "Escribe una funcion rotar(lista, n) que rote la lista n posiciones hacia la "
                  "DERECHA y devuelva una lista nueva. Si n es mayor que el largo, rota lo que "
                  "corresponda; si n es negativo, rota hacia la izquierda. Con lista vacia devuelve "
                  "lista vacia.",
        "tests": """
assert rotar([1,2,3,4,5], 2) == [4,5,1,2,3]
assert rotar([1,2,3,4,5], 7) == [4,5,1,2,3]
assert rotar([1,2,3,4,5], -1) == [2,3,4,5,1]
assert rotar([], 3) == []
assert rotar([1,2,3], 0) == [1,2,3]
""",
    },
    {
        "id": "romano",
        "prompt": "Escribe una funcion a_romano(n) que convierta un entero entre 1 y 3999 a numero "
                  "romano, usando la notacion sustractiva (4 es IV, 9 es IX, 40 es XL, 900 es CM).",
        "tests": """
assert a_romano(1) == "I"
assert a_romano(4) == "IV"
assert a_romano(14) == "XIV"
assert a_romano(40) == "XL"
assert a_romano(1994) == "MCMXCIV"
assert a_romano(3999) == "MMMCMXCIX"
""",
    },
    {
        "id": "desde_romano",
        "prompt": "Escribe una funcion desde_romano(s) que convierta un numero romano en mayusculas "
                  "al entero correspondiente. Debe manejar la notacion sustractiva (IV vale 4).",
        "tests": """
assert desde_romano("I") == 1
assert desde_romano("IV") == 4
assert desde_romano("XIV") == 14
assert desde_romano("MCMXCIV") == 1994
assert desde_romano("MMMCMXCIX") == 3999
""",
    },
    {
        "id": "racha",
        "prompt": "Escribe una funcion mayor_racha(lista) que encuentre la racha mas larga de "
                  "elementos consecutivos IGUALES y devuelva la tupla (elemento, longitud). "
                  "Si hay empate devuelve la primera. Con lista vacia devuelve None.",
        "tests": """
assert mayor_racha([1,1,2,2,2,3]) == (2,3)
assert mayor_racha([1,1,2,2]) == (1,2)
assert mayor_racha([5]) == (5,1)
assert mayor_racha([]) is None
""",
    },
    {
        "id": "camel",
        "prompt": "Escribe una funcion a_camel(s) que convierta un texto en snake_case a camelCase: "
                  "la primera palabra en minuscula y las siguientes con la inicial en mayuscula, "
                  "sin guiones bajos.",
        "tests": """
assert a_camel("hola_mundo_cruel") == "holaMundoCruel"
assert a_camel("hola") == "hola"
assert a_camel("") == ""
""",
    },
    {
        "id": "snake",
        "prompt": "Escribe una funcion a_snake(s) que convierta camelCase o PascalCase a snake_case: "
                  "todo en minusculas y un guion bajo antes de cada mayuscula interna. No debe "
                  "empezar con guion bajo.",
        "tests": """
assert a_snake("holaMundoCruel") == "hola_mundo_cruel"
assert a_snake("HolaMundo") == "hola_mundo"
assert a_snake("hola") == "hola"
assert a_snake("") == ""
""",
    },
    {
        "id": "primos",
        "prompt": "Escribe una funcion primos(n) que devuelva la lista ordenada de todos los numeros "
                  "primos menores o iguales a n. Si n es menor que 2 devuelve lista vacia.",
        "tests": """
assert primos(10) == [2,3,5,7]
assert primos(2) == [2]
assert primos(1) == []
assert primos(0) == []
assert len(primos(100)) == 25
""",
    },
    {
        "id": "mcd",
        "prompt": "Escribe una funcion mcd(a, b) que devuelva el maximo comun divisor de dos enteros "
                  "no negativos. El mcd de un numero con 0 es ese numero.",
        "tests": """
assert mcd(12,18) == 6
assert mcd(17,5) == 1
assert mcd(0,5) == 5
assert mcd(5,0) == 5
assert mcd(48,18) == 6
""",
    },
    {
        "id": "intervalos",
        "prompt": "Escribe una funcion fusionar(intervalos) que reciba una lista de tuplas (inicio, "
                  "fin) posiblemente desordenada y devuelva la lista de intervalos fusionados, "
                  "ordenada por inicio. Dos intervalos que se tocan en un extremo se fusionan.",
        "tests": """
assert fusionar([(1,3),(2,6),(8,10)]) == [(1,6),(8,10)]
assert fusionar([(5,7),(1,3),(2,4)]) == [(1,4),(5,7)]
assert fusionar([(1,2),(2,3)]) == [(1,3)]
assert fusionar([]) == []
assert fusionar([(1,5)]) == [(1,5)]
""",
    },
    {
        "id": "anagrama",
        "prompt": "Escribe una funcion es_anagrama(a, b) que devuelva True si los dos textos son "
                  "anagramas, ignorando mayusculas y espacios.",
        "tests": """
assert es_anagrama("Roma", "amor") is True
assert es_anagrama("la ruta natural", "natural la ruta") is True
assert es_anagrama("hola", "adios") is False
assert es_anagrama("", "") is True
""",
    },
    {
        "id": "comprimir",
        "prompt": "Escribe una funcion comprimir(s) que aplique codificacion por repeticiones: "
                  "'aaabb' se convierte en 'a3b2'. IMPORTANTE: devuelve la version comprimida solo "
                  "si es MAS CORTA que la original; si no lo es, devuelve la original sin cambios.",
        "tests": """
assert comprimir("aaabb") == "a3b2"
assert comprimir("abc") == "abc"
assert comprimir("aabb") == "aabb"
assert comprimir("") == ""
assert comprimir("aaaa") == "a4"
""",
    },
    {
        "id": "parentesis",
        "prompt": "Escribe una funcion balanceado(s) que devuelva True si los parentesis, corchetes "
                  "y llaves del texto estan correctamente balanceados y anidados. Un texto vacio "
                  "esta balanceado.",
        "tests": """
assert balanceado("({[]})") is True
assert balanceado("") is True
assert balanceado("(]") is False
assert balanceado("(") is False
assert balanceado(")(") is False
assert balanceado("([)]") is False
""",
    },
    {
        "id": "transpuesta",
        "prompt": "Escribe una funcion transpuesta(m) que reciba una matriz como lista de listas y "
                  "devuelva su transpuesta. Con matriz vacia devuelve lista vacia.",
        "tests": """
assert transpuesta([[1,2,3],[4,5,6]]) == [[1,4],[2,5],[3,6]]
assert transpuesta([[1]]) == [[1]]
assert transpuesta([]) == []
""",
    },
    {
        "id": "raiz_digital",
        "prompt": "Escribe una funcion raiz_digital(n) que sume los digitos de n y repita el proceso "
                  "hasta quedarse con un solo digito, que es el resultado. Para 9875: 9+8+7+5=29, "
                  "luego 2+9=11, luego 1+1=2.",
        "tests": """
assert raiz_digital(9875) == 2
assert raiz_digital(0) == 0
assert raiz_digital(9) == 9
assert raiz_digital(12345) == 6
""",
    },
    {
        "id": "sin_duplicados",
        "prompt": "Escribe una funcion sin_duplicados(lista) que elimine los elementos repetidos "
                  "CONSERVANDO el orden de la primera aparicion.",
        "tests": """
assert sin_duplicados([3,1,3,2,1]) == [3,1,2]
assert sin_duplicados([]) == []
assert sin_duplicados([1,1,1]) == [1]
assert sin_duplicados(["b","a","b"]) == ["b","a"]
""",
    },
    {
        "id": "n_mayor",
        "prompt": "Escribe una funcion n_esimo_mayor(lista, n) que devuelva el n-esimo valor mas "
                  "grande contando valores DISTINTOS (los repetidos cuentan una sola vez). "
                  "Si no hay suficientes valores distintos devuelve None.",
        "tests": """
assert n_esimo_mayor([5,3,9,1,9], 1) == 9
assert n_esimo_mayor([5,3,9,1,9], 2) == 5
assert n_esimo_mayor([5,3,9,1,9], 4) == 1
assert n_esimo_mayor([5,3,9,1,9], 5) is None
assert n_esimo_mayor([], 1) is None
""",
    },
    {
        "id": "bytes",
        "prompt": "Escribe una funcion formatear_bytes(n) que convierta una cantidad de bytes a "
                  "texto legible usando base 1024 y las unidades B, KB, MB, GB. Los bytes se "
                  "muestran sin decimales y las demas unidades con UN decimal. "
                  "Ejemplos: 0 da '0 B', 1023 da '1023 B', 1024 da '1.0 KB', 1536 da '1.5 KB'.",
        "tests": """
assert formatear_bytes(0) == "0 B"
assert formatear_bytes(1023) == "1023 B"
assert formatear_bytes(1024) == "1.0 KB"
assert formatear_bytes(1536) == "1.5 KB"
assert formatear_bytes(1048576) == "1.0 MB"
assert formatear_bytes(1073741824) == "1.0 GB"
""",
    },
    {
        "id": "lotes",
        "prompt": "Escribe una funcion en_lotes(lista, tamano) que parta la lista en sublistas de "
                  "ese tamano. El ultimo lote puede ser mas chico. Con lista vacia devuelve lista "
                  "vacia.",
        "tests": """
assert en_lotes([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]
assert en_lotes([1,2,3], 3) == [[1,2,3]]
assert en_lotes([1,2], 5) == [[1,2]]
assert en_lotes([], 3) == []
""",
    },
    {
        "id": "transpuesta",
        "prompt": "Escribe una funcion transpuesta(m) que reciba una matriz (lista de listas) "
                  "y devuelva su transpuesta. Si la matriz esta vacia, devuelve lista vacia.",
        "tests": """
assert transpuesta([[1,2,3],[4,5,6]]) == [[1,4],[2,5],[3,6]]
assert transpuesta([[1]]) == [[1]]
assert transpuesta([]) == []
assert transpuesta([[1,2],[3,4],[5,6]]) == [[1,3,5],[2,4,6]]
""",
    },
    {
        "id": "intervalos",
        "prompt": "Escribe una funcion fusionar(intervalos) que reciba una lista de tuplas "
                  "(inicio, fin) y devuelva la lista de intervalos fusionados, ordenados por "
                  "inicio. Dos intervalos que se tocan (ej. (1,3) y (3,5)) se fusionan.",
        "tests": """
assert fusionar([(1,3),(2,6),(8,10)]) == [(1,6),(8,10)]
assert fusionar([(1,4),(4,5)]) == [(1,5)]
assert fusionar([]) == []
assert fusionar([(5,6),(1,2)]) == [(1,2),(5,6)]
""",
    },
    {
        "id": "parentesis",
        "prompt": "Escribe una funcion balanceado(s) que devuelva True si los parentesis, "
                  "corchetes y llaves del string estan bien balanceados y anidados. "
                  "Los demas caracteres se ignoran.",
        "tests": """
assert balanceado("({[]})") is True
assert balanceado("(]") is False
assert balanceado("([)]") is False
assert balanceado("") is True
assert balanceado("a(b)c[d]") is True
assert balanceado("(") is False
""",
    },
    {
        "id": "mediana",
        "prompt": "Escribe una funcion mediana(nums) que devuelva la mediana de una lista de "
                  "numeros, SIN usar el modulo statistics. Con cantidad par de elementos, "
                  "devuelve el promedio de los dos centrales. Lista vacia: devuelve None.",
        "tests": """
assert mediana([3,1,2]) == 2
assert mediana([4,1,3,2]) == 2.5
assert mediana([5]) == 5
assert mediana([]) is None
""",
    },
    {
        "id": "top_frecuentes",
        "prompt": "Escribe una funcion top_frecuentes(texto, k) que devuelva las k palabras mas "
                  "frecuentes como lista de tuplas (palabra, cantidad), ordenadas por cantidad "
                  "descendente y, a igual cantidad, alfabeticamente. Las palabras se separan por "
                  "espacios y se comparan en minusculas.",
        "tests": """
assert top_frecuentes("a b a c b a", 2) == [("a",3),("b",2)]
assert top_frecuentes("Hola hola mundo", 1) == [("hola",2)]
assert top_frecuentes("x y", 5) == [("x",1),("y",1)]
assert top_frecuentes("", 3) == []
""",
    },
    {
        "id": "trozos",
        "prompt": "Escribe una funcion trozos(lista, n) que parta la lista en sublistas de "
                  "tamano n. La ultima puede ser mas corta. Si n <= 0, devuelve lista vacia.",
        "tests": """
assert trozos([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]
assert trozos([1,2,3], 3) == [[1,2,3]]
assert trozos([], 2) == []
assert trozos([1,2], 0) == []
""",
    },
    {
        "id": "dedup",
        "prompt": "Escribe una funcion dedup(lista) que elimine duplicados CONSERVANDO el orden "
                  "de la primera aparicion.",
        "tests": """
assert dedup([1,2,1,3,2]) == [1,2,3]
assert dedup([]) == []
assert dedup(["b","a","b"]) == ["b","a"]
""",
    },
    {
        "id": "binaria",
        "prompt": "Escribe una funcion binaria(lista, x) que busque x en una lista ORDENADA "
                  "usando busqueda binaria y devuelva su indice, o -1 si no esta.",
        "tests": """
assert binaria([1,3,5,7,9], 7) == 3
assert binaria([1,3,5], 1) == 0
assert binaria([1,3,5], 4) == -1
assert binaria([], 1) == -1
""",
    },
    {
        "id": "anidar",
        "prompt": "Escribe una funcion anidar(plano) que convierta un dict de claves con puntos "
                  "en un dict anidado. Ej: {'a.b': 1} -> {'a': {'b': 1}}.",
        "tests": """
assert anidar({"a.b": 1}) == {"a": {"b": 1}}
assert anidar({"a.b": 1, "a.c": 2}) == {"a": {"b": 1, "c": 2}}
assert anidar({"x": 5}) == {"x": 5}
assert anidar({}) == {}
""",
    },
    {
        "id": "rle",
        "prompt": "Escribe una funcion comprimir(s) que aplique run-length encoding: "
                  "'aaabb' -> 'a3b2'. Los caracteres que aparecen una sola vez tambien llevan "
                  "el 1: 'abc' -> 'a1b1c1'. String vacio devuelve string vacio.",
        "tests": """
assert comprimir("aaabb") == "a3b2"
assert comprimir("abc") == "a1b1c1"
assert comprimir("") == ""
assert comprimir("aaaa") == "a4"
""",
    },
    {
        "id": "anagrama",
        "prompt": "Escribe una funcion es_anagrama(a, b) que devuelva True si los dos strings son "
                  "anagramas, ignorando mayusculas y espacios.",
        "tests": """
assert es_anagrama("Roma", "amor") is True
assert es_anagrama("el aula", "la ruela") is False
assert es_anagrama("", "") is True
assert es_anagrama("abc", "abd") is False
""",
    },
    {
        "id": "movil",
        "prompt": "Escribe una funcion promedio_movil(nums, ventana) que devuelva la lista de "
                  "promedios moviles de tamano 'ventana'. Si la lista es mas corta que la "
                  "ventana, devuelve lista vacia.",
        "tests": """
assert promedio_movil([1,2,3,4], 2) == [1.5, 2.5, 3.5]
assert promedio_movil([1,2,3], 3) == [2.0]
assert promedio_movil([1], 2) == []
""",
    },
    {
        "id": "bytes_humano",
        "prompt": "Escribe una funcion formatear_bytes(n) que convierta un numero de bytes a "
                  "texto legible usando multiplos de 1024 y las unidades B, KB, MB, GB. "
                  "Con un decimal, salvo para B que va sin decimales. Ej: 1536 -> '1.5 KB'.",
        "tests": """
assert formatear_bytes(500) == "500 B"
assert formatear_bytes(1536) == "1.5 KB"
assert formatear_bytes(1048576) == "1.0 MB"
assert formatear_bytes(0) == "0 B"
""",
    },
    {
        "id": "query",
        "prompt": "Escribe una funcion parsear_query(s) que convierta un query string tipo "
                  "'a=1&b=2' en un dict {'a':'1','b':'2'}. Una clave sin valor ('c=') queda con "
                  "string vacio. String vacio devuelve dict vacio.",
        "tests": """
assert parsear_query("a=1&b=2") == {"a": "1", "b": "2"}
assert parsear_query("c=") == {"c": ""}
assert parsear_query("") == {}
assert parsear_query("x=10") == {"x": "10"}
""",
    },
    {
        "id": "islas",
        "prompt": "Escribe una funcion contar_islas(grid) que reciba una matriz de 0 y 1 y "
                  "devuelva cuantos grupos de 1 conectados hay. Se consideran conectados los "
                  "vecinos arriba, abajo, izquierda y derecha (no en diagonal).",
        "tests": """
assert contar_islas([[1,1,0],[0,1,0],[0,0,1]]) == 2
assert contar_islas([[0,0],[0,0]]) == 0
assert contar_islas([[1]]) == 1
assert contar_islas([]) == 0
assert contar_islas([[1,0,1],[0,0,0],[1,0,1]]) == 4
""",
    },
    {
        "id": "levenshtein",
        "prompt": "Escribe una funcion distancia(a, b) que calcule la distancia de edicion de "
                  "Levenshtein entre dos strings: el minimo de inserciones, borrados o "
                  "sustituciones para convertir uno en el otro.",
        "tests": """
assert distancia("casa", "cara") == 1
assert distancia("", "abc") == 3
assert distancia("abc", "abc") == 0
assert distancia("kitten", "sitting") == 3
""",
    },
    {
        "id": "password",
        "prompt": "Escribe una funcion validar_password(p) que devuelva True solo si el password "
                  "tiene al menos 8 caracteres, una mayuscula, una minuscula, un digito y un "
                  "caracter que no sea alfanumerico.",
        "tests": """
assert validar_password("Abcdef1!") is True
assert validar_password("abcdef1!") is False
assert validar_password("Abcdefg!") is False
assert validar_password("Abc1!") is False
assert validar_password("ABCDEF1!") is False
""",
    },
    {
        "id": "base_n",
        "prompt": "Escribe una funcion a_base(n, base) que convierta un entero no negativo a "
                  "string en la base dada (2 a 16), usando digitos 0-9 y letras minusculas a-f. "
                  "El cero devuelve '0'.",
        "tests": """
assert a_base(10, 2) == "1010"
assert a_base(255, 16) == "ff"
assert a_base(0, 8) == "0"
assert a_base(64, 8) == "100"
""",
    },
    {
        "id": "particion",
        "prompt": "Escribe una funcion pares_primero(nums) que devuelva una lista con los pares "
                  "primero y los impares despues, conservando el orden relativo original dentro "
                  "de cada grupo.",
        "tests": """
assert pares_primero([1,2,3,4,5,6]) == [2,4,6,1,3,5]
assert pares_primero([1,3,5]) == [1,3,5]
assert pares_primero([]) == []
""",
    },
    {
        "id": "interseccion",
        "prompt": "Escribe una funcion interseccion(a, b) que reciba dos listas ORDENADAS de "
                  "enteros y devuelva la lista ordenada de valores presentes en ambas, sin "
                  "repetidos.",
        "tests": """
assert interseccion([1,2,3,4],[2,4,6]) == [2,4]
assert interseccion([1,1,2],[1,2]) == [1,2]
assert interseccion([1],[2]) == []
assert interseccion([],[1]) == []
""",
    },
    {
        "id": "dias_entre",
        "prompt": "Escribe una funcion dias_entre(a, b) que reciba dos fechas en formato "
                  "'YYYY-MM-DD' y devuelva la cantidad de dias entre ellas como entero positivo. "
                  "Puedes usar el modulo datetime.",
        "tests": """
assert dias_entre("2026-01-01", "2026-01-31") == 30
assert dias_entre("2026-03-01", "2026-02-28") == 1
assert dias_entre("2026-01-01", "2026-01-01") == 0
assert dias_entre("2024-02-28", "2024-03-01") == 2
""",
    },
    {
        "id": "escapar_csv",
        "prompt": "Escribe una funcion campo_csv(s) que prepare un campo para CSV: si contiene "
                  "coma, comilla doble o salto de linea, lo devuelve entre comillas dobles y con "
                  "las comillas internas duplicadas. Si no, lo devuelve tal cual.",
        "tests": """
assert campo_csv("hola") == "hola"
assert campo_csv("a,b") == '"a,b"'
assert campo_csv('di "hola" ya') == '"di ""hola"" ya"'
assert campo_csv("") == ""
""",
    },
    {
        "id": "titulo",
        "prompt": "Escribe una funcion titular(s) que ponga en mayuscula la primera letra de "
                  "cada palabra, EXCEPTO 'de', 'del', 'la', 'las', 'el', 'los' e 'y' cuando no son "
                  "la primera palabra. Las demas letras quedan en minuscula.",
        "tests": """
assert titular("el senor de los anillos") == "El Senor de los Anillos"
assert titular("LA CASA") == "La Casa"
assert titular("y algo mas") == "Y Algo Mas"
assert titular("") == ""
""",
    },
    {
        "id": "aplanar_prof",
        "prompt": "Escribe una funcion aplanar_hasta(lista, profundidad) que aplane una lista "
                  "anidada solo hasta la profundidad indicada. Con profundidad 1 aplana un nivel; "
                  "con 0 devuelve la lista igual.",
        "tests": """
assert aplanar_hasta([1,[2,[3,[4]]]], 1) == [1,2,[3,[4]]]
assert aplanar_hasta([1,[2,[3]]], 2) == [1,2,3]
assert aplanar_hasta([1,[2]], 0) == [1,[2]]
assert aplanar_hasta([], 3) == []
""",
    },
    {
        "id": "romanos_suma",
        "prompt": "Escribe una funcion sumar_romanos(a, b) que reciba dos numeros romanos como "
                  "string (hasta 3999), los sume y devuelva el resultado tambien en romano.",
        "tests": """
assert sumar_romanos("X", "V") == "XV"
assert sumar_romanos("IV", "VI") == "X"
assert sumar_romanos("MM", "XXIV") == "MMXXIV"
assert sumar_romanos("I", "I") == "II"
""",
    },
    {
        "id": "cola_prioridad",
        "prompt": "Escribe una funcion atender(tareas) que reciba una lista de tuplas "
                  "(prioridad, nombre) y devuelva los nombres ordenados por prioridad ASCENDENTE "
                  "(1 es lo mas urgente). A igual prioridad, se conserva el orden de llegada.",
        "tests": """
assert atender([(2,"b"),(1,"a"),(2,"c")]) == ["a","b","c"]
assert atender([]) == []
assert atender([(3,"z"),(1,"y")]) == ["y","z"]
""",
    },
    {
        "id": "camino_dict",
        "prompt": "Escribe una funcion obtener(d, camino, defecto=None) que busque en un dict "
                  "anidado siguiendo un camino con puntos ('a.b.c') y devuelva el valor, o el "
                  "defecto si algun tramo no existe.",
        "tests": """
assert obtener({"a": {"b": 1}}, "a.b") == 1
assert obtener({"a": {"b": 1}}, "a.c") is None
assert obtener({"a": 1}, "a.b", "x") == "x"
assert obtener({}, "a", 0) == 0
""",
    },
    {
        "id": "reintentos",
        "prompt": "Escribe una funcion con_reintentos(fn, veces) que ejecute fn() y, si lanza "
                  "una excepcion, la reintente hasta 'veces' intentos en total. Si todos fallan, "
                  "vuelve a lanzar la ultima excepcion. Devuelve el resultado si alguno funciona.",
        "tests": """
estado = {"n": 0}
def falla_dos_veces():
    estado["n"] += 1
    if estado["n"] < 3:
        raise ValueError("todavia no")
    return "listo"
assert con_reintentos(falla_dos_veces, 3) == "listo"
assert estado["n"] == 3

def siempre_falla():
    raise RuntimeError("nunca")
try:
    con_reintentos(siempre_falla, 2)
    assert False, "deberia haber lanzado"
except RuntimeError:
    pass
""",
    },
]

# ─── Batería de razonamiento: para juicio a ciegas ───────────────────────────
# Razonamiento, ahora PUNTUADO (17/08/2026). Antes estas 4 preguntas se hacian,
# se guardaban las respuestas "para juicio a ciegas"... y nadie las leia nunca.
# El campo `aciertos` del JSON medía SOLO codigo, asi que el backend de CPU
# --cuyo rol declarado es razonamiento-- se venia eligiendo con una bateria de
# programacion.
#
# El criterio es el mismo que el de codigo: objetivo y verificable, no "se ve
# bien". Cada pregunta declara grupos de conceptos; la respuesta acierta si
# menciona al menos uno de CADA grupo. Se normaliza (minusculas, sin acentos)
# para no castigar tildes ni mayusculas.
#
# Hay CINCO preguntas TRAMPA (marcadas con _TRAMPA en el id): su premisa es
# falsa y una respuesta correcta tiene que RECHAZARLA y ademas explicar el
# mecanismo real. Miden lo que una bateria de codigo no mide: si el modelo
# razona o si le sigue la corriente al que pregunta.
#
# AMPLIADA de 4 a 24 preguntas el 19/08/2026. Con 4 el puntaje era una moneda:
# probando el 2B en tres cuantizaciones dio 1/1/1, 4/2/1 y 0/2/2, y la
# cuantizacion MEJOR (Q8) obtuvo 0/4. No se habia notado antes porque todos los
# modelos evaluados sacaban 4/4: el techo tapaba el problema. Es el mismo
# problema que tenia la parte de codigo con 25 tareas, y la misma solucion.
#
# LAS LISTAS DE SINONIMOS SE VALIDARON contra las respuestas reales del 9B: la
# primera version daba 12/25 y al auditar, OCHO de esos fallos eran respuestas
# correctas que la lista no reconocia ("la tabla es muy pequeña" no matcheaba
# "tabla pequeña"; "rigidas" no matcheaba "rigidez"). Si se agregan preguntas
# nuevas hay que hacer lo mismo: correrlas contra un modelo que sepa el tema y
# leer los fallos uno por uno. Una regla mal escrita no se distingue de un
# modelo malo mirando solo el puntaje.
RAZONAMIENTO = [
    {
        "id": "indice_db",
        "prompt": "En 3 frases: por que un indice en una base de datos acelera las lecturas "
                  "pero enlentece las escrituras?",
        "debe": [
            # por que acelera leer: alguna estructura de busqueda
            ["arbol", "b-tree", "btree", "b+", "ordenad", "busqueda binaria",
             "estructura", "hash", "logaritm", "log(n", "sin recorrer", "escaneo completo",
             "full scan", "acceso directo", "localiza"],
            # por que enlentece escribir: hay que mantener el indice
            ["actualiz", "mantener", "manten", "reescrib", "recalcul", "reorganiz",
             "reconstru", "modificar el indice", "sobrecarga", "overhead", "coste adicional",
             "costo adicional", "trabajo extra", "tambien el indice", "cada insercion"],
        ],
    },
    {
        "id": "monolito_micro",
        "prompt": "En 3 frases: cuando conviene un monolito y cuando microservicios?",
        "debe": [
            # a favor del monolito
            ["equipo pequeno", "equipos pequenos", "pocas personas", "simple", "sencill",
             "inicio", "empezar", "temprana", "mvp", "menos complej", "una sola",
             "un solo", "monolito conviene", "baja escala", "proyecto pequeno"],
            # a favor de microservicios
            ["escalar", "escala", "escalab", "equipos grandes", "varios equipos",
             "independiente", "despliegu", "deploy", "dominios", "aislar fallos",
             "por separado", "autonom"],
        ],
    },
    {
        "id": "python_nativo_TRAMPA",
        "prompt": "En 3 frases: por que Python compila a codigo maquina nativo antes de "
                  "ejecutarse?",
        # La premisa es FALSA. Acertar exige DOS cosas, no una:
        #   g1: negar explicitamente la premisa
        #   g2: nombrar el mecanismo real (bytecode / VM)
        # Pedir solo una daba falsos positivos reales, verificados contra las
        # respuestas guardadas: coder-1_5b afirmaba la premisa entera pero decia
        # "o interpretador Python", y la palabra "interpret" sola le daba el OK;
        # `especialista` mencionaba "bytecode" pero llamandolo "codigo maquina",
        # es decir sin haber entendido nada. Exigiendo negacion + mecanismo, los dos
        # fallan como corresponde.
        "debe": [
            ["no compila", "nao compila", "no lo compila", "no se compila",
             "no compila directamente", "no genera codigo maquina",
             "no produce codigo maquina", "no es cierto", "es incorrect",
             "es falso", "premisa", "en realidad no", "realmente no",
             "no traduce a codigo maquina", "no a codigo maquina"],
            ["bytecode", "byte code", "codigo intermedio", "maquina virtual",
             "interpret", ".pyc", "vm de python"],
        ],
        "nota": "trampa: la premisa es falsa, la respuesta correcta la rechaza Y explica",
    },
    {
        "id": "indice_no_conviene",
        "prompt": "En 3 frases: cuando NO conviene crear un indice en una tabla?",
        "debe": [
            ["pequena", "pequenas", "pocos registros", "pocas filas",
             "poca cantidad", "escaneo completo es mas", "no hay suficientes datos",
             "tamano reducido", "muy pocos", "poco volumen"],
            ["muchas escrituras", "escritura frecuente", "insercion", "inserciones",
             "actualizaciones frecuentes", "se escribe mucho", "alta tasa de escritura",
             "baja cardinalidad", "poca cardinalidad", "pocos valores distintos",
             "selectivid", "columna que no se consulta", "no se usa en consultas",
             "dos valores", "sobrecarga al mantenimiento"],
        ],
    },
    {
        "id": "n_mas_1",
        "prompt": "En 3 frases: que es el problema N+1 en un ORM y como se corrige?",
        "debe": [
            ["una consulta por cada", "n consultas", "muchas consultas", "una query por",
             "consulta adicional por", "por cada registro", "por cada fila",
             "por cada elemento", "bucle de consultas", "multiples viajes"],
            ["join", "eager", "precarga", "prefetch", "select_related", "prefetch_related",
             "cargar de una", "una sola consulta", "carga anticipada", "traer todo junto",
             "in (", "batch"],
        ],
    },
    {
        "id": "desnormalizar",
        "prompt": "En 3 frases: por que a veces conviene desnormalizar una base de datos?",
        "debe": [
            ["join", "unione", "acelera la lectura", "lecturas mas rapid",
             "consultas mas rapid", "rendimiento de lectura", "menos consultas",
             "mas rapido leer", "rendimiento de las consultas"],
            ["duplica", "redundan", "inconsisten", "mantener sincron", "actualizar en varios",
             "espacio", "costo de escritura", "riesgo de", "desincroniz"],
        ],
    },
    {
        "id": "idempotencia",
        "prompt": "En 3 frases: por que importa que una operacion sea idempotente cuando hay reintentos?",
        "debe": [
            ["repetir", "repetida", "varias veces", "mas de una vez", "reintent", "duplicad",
             "dos veces", "multiples veces"],
            ["mismo resultado", "mismo efecto", "no duplica", "sin efectos adicionales",
             "no cambia el estado", "no se aplica dos veces", "seguro reintentar",
             "no altera el estado", "una sola vez", "sin consecuencias", "un solo cobro", "un solo registro",
             "efectos secundarios", "no produzcan efectos", "integridad"],
        ],
    },
    {
        "id": "reintento_sin_espera",
        "prompt": "En 3 frases: por que reintentar inmediatamente un servicio caido empeora las cosas, y que habria que hacer en su lugar?",
        "debe": [
            ["mas carga", "sobrecarga", "satura", "avalancha", "tormenta", "amplifica",
             "aumenta el trafico", "mas peticiones", "golpea mas", "empeora la congestion",
             "no le da tiempo", "impide que se recupere"],
            ["backoff", "espera", "esperar", "exponencial", "gradual", "jitter",
             "separar los intentos", "dar tiempo", "incremental"],
        ],
    },
    {
        "id": "cola_mensajes",
        "prompt": "En 3 frases: que gana y que pierde un sistema al meter una cola de mensajes entre dos servicios?",
        "debe": [
            ["desacopl", "absorbe picos", "amortigua", "no depende de que el otro",
             "asincron", "independiente", "aguanta picos", "tolerancia a fallos",
             "si el consumidor esta caido"],
            ["latencia", "demora", "complej", "mas piezas", "orden", "duplicad",
             "eventual", "no es inmediato", "mas dificil de depurar", "otra infraestructura"],
        ],
    },
    {
        "id": "deadlock_orden",
        "prompt": "En 3 frases: por que dos hilos que toman los mismos dos candados en distinto orden pueden quedarse bloqueados?",
        "debe": [
            ["espera circular", "circular", "cada uno espera", "se esperan mutuamente",
             "uno tiene a y espera b", "mutuamente", "abrazo mortal", "deadlock",
             "ninguno suelta", "bloqueo mutuo"],
            ["no puede avanzar", "no pueden avanzar", "ninguno", "no libera", "no sueltan",
             "no suelta", "retiene", "mantiene el candado", "indefinidamente",
             "bloqueados", "sin liberar", "mismo orden", "jerarquia"],
        ],
    },
    {
        "id": "condicion_carrera",
        "prompt": "En 3 frases: por que dos procesos que leen y escriben el mismo contador sin sincronizacion pueden perder incrementos?",
        "debe": [
            ["lee", "leen", "lectura", "leer el valor"],
            ["se pisa", "pisan", "se pierde", "sobrescrib", "mismo valor", "no es atomic",
             "no atomica", "entre la lectura y la escritura", "carrera", "intercalad",
             "ambos escriben"],
        ],
    },
    {
        "id": "gc_ciclos",
        "prompt": "En 3 frases: por que contar referencias no alcanza para liberar toda la memoria?",
        "debe": [
            ["ciclo", "ciclica", "ciclicas", "referencias mutuas", "se referencian entre si",
             "circular", "apuntan entre ellos", "bucle de referencias"],
            ["cero", "no se libera", "queda ocupada",
             "fuga", "leak", "recolector adicional", "detector de ciclos", "gc adicional",
             "sigue en memoria", "se mantienen vivos", "vivos mutuamente",
             "mantienen en memoria", "mantengan en memoria",
             "no podra liberar", "no puede liberar", "algoritmos adicionales",
             "no se recolecta", "siguen vivos"],
        ],
    },
    {
        "id": "hash_password_TRAMPA",
        "prompt": "En 3 frases: por que conviene cifrar las contrasenas con AES para poder recuperarlas si el usuario las olvida?",
        # TRAMPA: no se cifran, se hashean, y no se recuperan: se resetean.
        "debe": [
            ["no se cifra", "no conviene cifrar", "no se deben cifrar", "no es correcto",
             "no es lo correcto", "es un error", "mala practica", "no se recuperan",
             "no se debe poder recuperar", "premisa", "incorrect", "no deberia",
             "en realidad no", "es falso"],
            ["hash", "bcrypt", "argon", "scrypt", "pbkdf2", "una sola via", "unidirec",
             "irreversib", "no reversible"],
        ],
        "nota": "trampa: las contrasenas no se cifran ni se recuperan, se hashean y se resetean",
    },
    {
        "id": "async_cpu_TRAMPA",
        "prompt": "En 3 frases: por que usar asyncio acelera un calculo intensivo de CPU en Python?",
        # TRAMPA: asyncio no acelera CPU-bound; sirve para E/S. Ademas el GIL.
        "debe": [
            ["no acelera", "no lo acelera", "no mejora", "no sirve", "no ayuda",
             "no es correcto", "es falso", "premisa", "incorrect", "no aporta",
             "no va a acelerar", "en realidad no"],
            ["entrada/salida", "entrada y salida", "e/s", "i/o", "espera",
             "red", "disco", "gil", "un solo hilo", "concurrencia no es paralelismo",
             "multiprocessing", "procesos"],
        ],
        "nota": "trampa: asyncio sirve para E/S, no para CPU; ademas esta el GIL",
    },
    {
        "id": "https_servidor_TRAMPA",
        "prompt": "En 3 frases: por que HTTPS impide que un servidor comprometido lea los datos que le envian los usuarios?",
        # TRAMPA: HTTPS cifra en TRANSITO; el servidor descifra y ve todo.
        "debe": [
            ["no impide", "no lo impide", "no protege", "no evita", "es falso",
             "no es cierto", "premisa", "incorrect", "no garantiza", "en realidad no",
             "no sirve para eso"],
            ["en transito", "en el transporte", "entre el cliente y el servidor",
             "el servidor descifra", "el servidor ve", "llega descifrad", "extremo",
             "solo cifra la comunicacion", "una vez que llega", "en el servidor esta en claro",
             "texto plano en el servidor"],
        ],
        "nota": "trampa: HTTPS cifra el transporte; el servidor ve los datos en claro",
    },
    {
        "id": "paralelo_latencia_TRAMPA",
        "prompt": "En 3 frases: por que atender 4 peticiones en paralelo en el mismo modelo hace que cada una responda mas rapido que si fuera sola?",
        # TRAMPA: el agregado sube, la latencia INDIVIDUAL empeora.
        "debe": [
            ["no responde mas rapido", "no es mas rapido", "no acelera", "al contrario",
             "es falso", "no es cierto", "premisa", "incorrect", "en realidad no",
             "cada una tarda mas", "empeora", "mas lenta", "no mejora"],
            ["comparten", "compiten", "se reparte", "recurso", "ancho de banda",
             "memoria", "agregado", "rendimiento total", "throughput", "el total sube",
             "en conjunto", "capacidad total"],
        ],
        "nota": "trampa: la concurrencia sube el rendimiento AGREGADO y baja el individual",
    },
    {
        "id": "coseno_intencion",
        "prompt": "En 3 frases: por que dos preguntas con alta similitud de coseno pueden necesitar respuestas totalmente distintas?",
        "debe": [
            ["tema", "vocabulario", "palabras parecidas", "mismo dominio", "misma area",
             "superficial", "forma", "parecido lexico", "terminos similares",
             "mismos terminos", "cercan", "direccional", "alineacion", "conceptos"],
            ["intencion", "intencion distinta", "piden cosas distintas", "objetivo",
             "opuest", "contrari", "niega", "negacion", "instalar y desinstalar",
             "abrir y cerrar", "distinto proposito", "lo contrario"],
        ],
    },
    {
        "id": "contexto_largo",
        "prompt": "En 3 frases: por que una conversacion larga con un modelo se vuelve mas lenta en cada turno?",
        "debe": [
            ["historial", "contexto", "conversacion completa", "mensajes anteriores",
             "todo el historial", "acumula", "crece", "cada vez mas tokens"],
            ["procesar", "reprocesar", "releer", "prefill", "recalcul", "atencion",
             "mas tokens de entrada", "vuelve a leer", "cuadratic", "coste crece"],
        ],
    },
    {
        "id": "cuantizacion",
        "prompt": "En 3 frases: que se gana y que se pierde al cuantizar un modelo de 16 a 4 bits?",
        "debe": [
            ["menos memoria", "menos vram", "menos ram", "ocupa menos", "mas chico",
             "mas rapido", "cabe", "tamano", "acelera", "cuarta parte",
             "recursos limitados"],
            ["precision", "calidad", "exactitud", "degrada", "peor",
             "error", "aproxima", "redondea", "empeora"],
        ],
    },
    {
        "id": "moe_activos",
        "prompt": "En 3 frases: por que un modelo MoE de 30B puede generar mas rapido que un modelo denso de 27B?",
        "debe": [
            ["activa", "activos", "solo una parte", "subconjunto", "algunos expertos",
             "pocos expertos", "no usa todos", "parte de los parametros",
             "enrutador", "router", "seleccion"],
            ["por token", "cada token", "menos calculo", "menos operaciones",
             "menos lectura", "menos memoria leida", "mas rapido por token",
             "menos trabajo", "ancho de banda"],
        ],
    },
    {
        "id": "vram_vs_ram",
        "prompt": "En 3 frases: por que el mismo modelo corre mucho mas lento en RAM que en VRAM, y que operacion del modelo es la que queda limitada?",
        "debe": [
            ["ancho de banda", "velocidad de memoria", "bandwidth", "gb/s",
             "memoria mas lenta", "mas lenta la ram", "transferencia"],
            ["leer los pesos", "lee los pesos", "cada token", "limitado por memoria",
             "memory bound", "memory-bound", "acceso a memoria", "traer los pesos",
             "carga de pesos", "recorre los parametros", "no por calculo"],
        ],
    },
    {
        "id": "cache_invalidacion",
        "prompt": "En 3 frases: por que invalidar una cache es dificil?",
        "debe": [
            ["saber cuando", "detect", "identific", "determin",
             "que datos han cambiado", "enterarse", "cambio en el origen",
             "cambio la fuente", "quien avisa", "no sabe", "dificil saber",
             "retraso", "fuente original", "copias", "propagacion", "sincroniz"],
            ["obsolet", "desactualiz", "vieja", "stale", "incorrect", "inconsisten",
             "datos viejos", "respuesta vieja", "sirve algo que ya cambio"],
        ],
    },
    {
        "id": "log_errores",
        "prompt": "En 3 frases: por que es mala idea capturar una excepcion y no registrarla ni relanzarla?",
        "debe": [
            ["silencio", "silencia", "se pierde", "oculta", "invisible", "no se entera",
             "tapa", "esconde", "sin rastro", "desaparece"],
            ["depurar", "diagnostic", "investigar", "encontrar la causa", "debug",
             "no se sabe que fallo", "sigue como si nada", "estado inconsistente",
             "falla mas adelante", "error posterior"],
        ],
    },
    {
        "id": "prueba_unitaria_red",
        "prompt": "En 3 frases: por que una prueba unitaria no deberia depender de una llamada de red real?",
        "debe": [
            ["lenta", "lentas", "tarda", "demora", "inestable", "intermitente",
             "flaky", "falla a veces", "depende de", "no determinista", "poco fiable"],
            ["mock", "simula", "doble", "stub", "fake", "aislar", "aislada",
             "sin depender", "controlad", "reproducible", "determinista"],
        ],
    },
    {
        "id": "inyeccion_dependencias",
        "prompt": "En 3 frases: que problema resuelve la inyeccion de dependencias?",
        "debe": [
            ["acopl", "rigid", "hardcode", "instanciar dentro", "crear objetos",
             "crea sus propias", "fuertemente ligad", "implementaciones concretas",
             "dentro de cada clase", "sus propias implementaciones"],
            ["test", "prueba", "mock", "sustitu", "reemplaz", "intercambi",
             "cambiar la implementacion", "distintas implementaciones", "flexib"],
        ],
    },
]


def _normalizar_resp(texto: str) -> str:
    """minusculas, sin acentos, espacios colapsados -- para comparar por concepto."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t)


# Palabras que niegan. Un concepto que empieza con una de estas NO admite hueco.
_NEGACIONES = ("no ", "nao ", "sin ", "nunca ", "jamas ", "tampoco ")


@functools.lru_cache(maxsize=8192)
def _patron_con_hueco(concepto: str):
    """Regex que permite hasta 2 palabras metidas entre las del concepto.

    POR QUE (24/08/2026): la comparacion era subcadena pelada, y eso reprobaba
    respuestas correctas por una palabra de relleno. Medido sobre las 1.834
    respuestas guardadas en pruebas/resultado_experto_*.json:

        "equipo pequeño"     no matcheaba  "el equipo ES pequeño"   (ornith-9b)
        "acceso a memoria"   no matcheaba  "acceso a LA memoria"    (ornith-9b)
        "palabras parecidas" no matcheaba  "palabras SON parecidas"

    Son 43 respuestas correctas reprobadas por relleno, ninguna por no entender.

    TRES RESTRICCIONES, cada una puesta DESPUES de ver el dano que evita:

    1. El hueco NO cruza puntuacion (solo espacios y palabras). Sin esto, en
       "Python NO es un lenguaje nativo; ... COMPILA a bytecode" el concepto
       "no compila" matcheaba de una oracion a la otra, y una respuesta que
       AFIRMA la premisa falsa aprobaba la trampa. Se rompian 9 trampas.

    2. Los conceptos que empiezan con negacion no admiten hueco. Meter palabras
       entre "no" y el verbo puede invertir el sentido, y las trampas se juegan
       enteras ahi: "no acelera" matcheo dentro de una respuesta que decia que
       si acelera.

    3. Cada token empieza en limite de palabra, y solo los de 3+ letras admiten
       sufijo libre. Sin esto el concepto "n consultas" matcheaba "NUMERO de
       consultas" y "reNDImiento en las consultas": la "n" pegaba al principio
       de cualquier palabra. Eran 17 aprobados de "n_mas_1", todos basura.

    La subcadena queda SIEMPRE como alternativa, asi el cambio solo puede
    convertir FALLA en PASA. Verificado: 0 regresiones sobre las 1.834.
    """
    piezas = concepto.split()
    if len(piezas) < 2 or concepto.startswith(_NEGACIONES):
        return None
    partes = []
    for t in piezas:
        ini = r"\b" if t[0].isalnum() else ""
        fin = r"\w*" if len(t) >= 3 and t[-1].isalnum() else (r"\b" if t[-1].isalnum() else "")
        partes.append(ini + re.escape(t) + fin)
    return re.compile(r" (?:[a-z0-9]+ ){0,2}".join(partes))


def _concepto_en(concepto: str, texto_normalizado: str) -> bool:
    """El concepto aparece: como subcadena, o con hasta 2 palabras intercaladas."""
    c = _normalizar_resp(concepto)
    if c in texto_normalizado:
        return True
    patron = _patron_con_hueco(c)
    return bool(patron and patron.search(texto_normalizado))


def puntuar_razonamiento(texto: str, pregunta: dict) -> tuple[bool, dict]:
    """True si la respuesta menciona al menos un concepto de CADA grupo de `debe`."""
    t = _normalizar_resp(_sin_pensamiento(texto))
    detalle = {}
    for i, grupo in enumerate(pregunta["debe"]):
        encontrado = next((c for c in grupo if _concepto_en(c, t)), None)
        detalle[f"g{i + 1}"] = encontrado or False
    return all(detalle.values()), detalle


# Instruccion de sistema opcional, para medir su efecto sin tocar el resto del
# banco. Con BANCO_EVAL_SISTEMA se pasa el texto; vacio = como siempre.
SISTEMA = os.getenv("BANCO_EVAL_SISTEMA", "")

# Tope de tareas, para cribar antes de gastar la bateria entera. Vacio = todas.
# Existe por atomic_ai (19/08/2026): con descomposicion cada tarea son varias
# llamadas al modelo y las 53 tareas pasan de una hora. Se criba con un
# subconjunto y solo si pasa el umbral se ejecuta completo. OJO: el subconjunto
# hay que usarlo en LAS DOS ramas de la comparacion, no comparar 15 contra 53.
LIMITE = int(os.getenv("BANCO_EVAL_LIMITE", "0")) or None

# Modo pensante. La bateria siempre lo envio APAGADO, asi que su efecto nunca se
# midio. Con BANCO_EVAL_THINKING=1 se enciende y se sube el tope de tokens: el
# pensamiento consume salida (se midio en julio que la variante Thinking gastaba
# 1.872 tokens en tareas triviales), y con 400 la respuesta final quedaria
# truncada -- se estaria midiendo el truncamiento, no el modelo.
PENSAR = os.getenv("BANCO_EVAL_THINKING", "0") == "1"
TOPE_PENSANDO = int(os.getenv("BANCO_EVAL_TOPE_THINKING", "1400"))


def _sin_pensamiento(texto: str) -> str:
    """Quita los bloques <think>...</think> antes de puntuar.

    Sin esto la medicion no vale: el puntuador busca conceptos en TODO el texto,
    asi que encontraria los conceptos dentro del razonamiento aunque la respuesta
    final diga otra cosa. Se puntua lo que el modelo RESPONDE, no lo que penso.
    """
    limpio = re.sub(r"<think>.*?</think>", " ", texto or "", flags=re.S | re.I)
    # Si el bloque quedo abierto (se corto por tope), lo que sigue es pensamiento
    # sin respuesta: mejor devolver vacio que puntuar un razonamiento a medias.
    if re.search(r"<think>", limpio, flags=re.I):
        return ""
    return limpio.strip()


def preguntar(prompt, max_tokens=400, temp=0.1):
    if PENSAR:
        max_tokens = max(max_tokens, TOPE_PENSANDO)
    mensajes = ([{"role": "system", "content": SISTEMA}] if SISTEMA else [])
    mensajes.append({"role": "user", "content": prompt})
    body = json.dumps({
        "model": ETIQUETA,
        "messages": mensajes,
        "max_tokens": max_tokens, "temperature": temp, "stream": False,
        "chat_template_kwargs": {"enable_thinking": PENSAR},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    msg = d["choices"][0]["message"]
    t = d.get("timings", {})
    tps = t.get("predicted_n", 0) / (t.get("predicted_ms", 1) / 1000)
    contenido = (msg.get("content") or "").strip()
    # Algunos modelos IGNORAN `enable_thinking: False` y devuelven su respuesta
    # en `reasoning_content`, dejando `content` vacio o cortado por limite de
    # tokens. Leyendo solo `content` sacaban CERO y parecia que el modelo era
    # malisimo: LFM2.5-2.6B dio 0/25 en razonamiento con 27/53 en codigo, que es
    # imposible. Era la medicion, no el modelo (23/08/2026).
    if not contenido:
        contenido = (msg.get("reasoning_content") or "").strip()
    return contenido, tps


def extraer_codigo(texto):
    texto = _sin_pensamiento(texto)
    m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
    return (m.group(1) if m else texto).strip()


def probar(codigo, tests):
    """Ejecuta el codigo + los tests en un subproceso aislado con timeout."""
    fuente = codigo + "\n\n" + tests + "\nprint('OK')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(fuente)
        ruta = f.name
    try:
        p = subprocess.run([sys.executable, ruta], capture_output=True,
                           text=True, timeout=15, encoding="utf-8", errors="replace")
        if p.returncode == 0 and "OK" in (p.stdout or ""):
            return True, ""
        err = (p.stderr or "").strip().splitlines()
        return False, (err[-1] if err else "sin salida")[:90]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (posible bucle infinito)"
    finally:
        Path(ruta).unlink(missing_ok=True)


def main():
    tareas = TAREAS[:LIMITE] if LIMITE else TAREAS
    preguntas = RAZONAMIENTO[:LIMITE] if LIMITE else RAZONAMIENTO
    # Solo la seccion de CODIGO. Para medir modelos que el MCP va a usar para
    # PROGRAMAR, las 25 preguntas de razonamiento son tiempo que no informa: el
    # razonamiento se lo queda el harness por diseño. No cambia como se puntua
    # el codigo -- la seccion de codigo se ejecuta igual y primero.
    if os.getenv("EVAL_EXPERTOS_SOLO_CODIGO"):
        preguntas = []
    print(f"\n{'='*64}\n  EVALUACION: {ETIQUETA}  (puerto {PUERTO})\n{'='*64}")
    if LIMITE:
        print(f"  SUBCONJUNTO: {len(tareas)} tareas y {len(preguntas)} preguntas "
              f"(de {len(TAREAS)} y {len(RAZONAMIENTO)})")

    # --- Código ---
    print("\n--- CODIGO (verificado por ejecucion) ---")
    aciertos, velocidades, detalle = 0, [], []
    for t in tareas:
        # 700 tokens: con 400 se cortaban las tareas largas (romano, intervalos) y
        # el fallo habria sido del limite, no del modelo.
        txt, tps = preguntar(f"{t['prompt']}\n\n{INSTRUCCION}", max_tokens=700)
        velocidades.append(tps)
        ok, err = probar(extraer_codigo(txt), t["tests"])
        aciertos += ok
        detalle.append({"id": t["id"], "ok": ok, "error": err, "codigo": extraer_codigo(txt)})
        print(f"  {'PASA ' if ok else 'FALLA'} {t['id']:<12} {tps:>5.1f} t/s   {err}")
    print(f"\n  CODIGO: {aciertos}/{len(tareas)}   velocidad media {sum(velocidades)/len(velocidades):.1f} t/s")

    # --- Razonamiento (se guarda sin etiquetar) ---
    print("\n--- RAZONAMIENTO (verificado por conceptos) ---")
    respuestas = []
    aciertos_raz = 0
    for preg in preguntas:
        txt, tps = preguntar(preg["prompt"], max_tokens=300, temp=0.3)
        ok_raz, det_raz = puntuar_razonamiento(txt, preg)
        aciertos_raz += ok_raz
        respuestas.append({
            "id": preg["id"], "pregunta": preg["prompt"], "respuesta": txt,
            "ok": ok_raz, "detalle": det_raz,
        })
        faltan = [g for g, v in det_raz.items() if not v]
        marca = "PASA " if ok_raz else "FALLA"
        extra = "" if ok_raz else f"  (no menciona: {', '.join(faltan)})"
        print(f"  {marca}  {preg['id']:24s} ({tps:.1f} t/s){extra}")

    print(f"\n  RAZONAMIENTO: {aciertos_raz}/{len(preguntas)}")

    salida = AQUI / f"resultado_experto_{ETIQUETA}.json"
    salida.write_text(json.dumps({
        "etiqueta": ETIQUETA,
        "codigo": {"aciertos": aciertos, "total": len(tareas), "detalle": detalle},
        "razonamiento_puntaje": {"aciertos": aciertos_raz, "total": len(preguntas)},
        "velocidad_media": sum(velocidades) / len(velocidades),
        "razonamiento": respuestas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {salida.name}")


if __name__ == "__main__":
    main()
