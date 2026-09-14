# -*- coding: utf-8 -*-
"""
verificar_bateria.py - Comprueba que la bateria de eval_expertos.py este bien escrita.

Un test mal escrito invalida la evaluacion entera: haria fallar a un modelo que
respondio bien, o pasar a uno que respondio mal. Este script resuelve cada tarea
con una implementacion de referencia y la somete a los MISMOS tests, usando la
misma funcion probar(). Si algo no da 25/25, el defecto esta en el banco.

Uso: python verificar_bateria.py
"""
import sys
from pathlib import Path

# pruebas/ se reorganizo en carpetas el 07/09/2026: los bancos de calidad
# viven en pruebas/calidad/. Sin esta linea el import de abajo no los
# encuentra desde otra subcarpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "calidad"))
from eval_expertos import TAREAS, probar

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REFERENCIA = {
"fizzbuzz": '''
def fizzbuzz(n):
    r = []
    for i in range(1, n+1):
        if i % 15 == 0: r.append("FizzBuzz")
        elif i % 3 == 0: r.append("Fizz")
        elif i % 5 == 0: r.append("Buzz")
        else: r.append(str(i))
    return r
''',
"duracion": '''
import re
def parsear_duracion(s):
    h = re.search(r"(\\d+)h", s)
    m = re.search(r"(\\d+)m", s)
    return (int(h.group(1))*60 if h else 0) + (int(m.group(1)) if m else 0)
''',
"palindromo": '''
def es_palindromo(s):
    t = "".join(c.lower() for c in s if c.isalnum())
    return t == t[::-1]
''',
"aplanar": '''
def aplanar(lista):
    r = []
    for x in lista:
        if isinstance(x, list): r.extend(aplanar(x))
        else: r.append(x)
    return r
''',
"busqueda": '''
def buscar(lista, x):
    lo, hi = 0, len(lista)-1
    while lo <= hi:
        m = (lo+hi)//2
        if lista[m] == x: return m
        if lista[m] < x: lo = m+1
        else: hi = m-1
    return -1
''',
"agrupar": '''
def agrupar_por(items, clave):
    r = {}
    for it in items: r.setdefault(it[clave], []).append(it)
    return r
''',
"contar_palabras": '''
import re
def contar_palabras(texto):
    r = {}
    for p in re.findall(r"[\\w']+", texto.lower()):
        r[p] = r.get(p, 0) + 1
    return r
''',
"rotar": '''
def rotar(lista, n):
    if not lista: return []
    n %= len(lista)
    return lista[-n:] + lista[:-n] if n else list(lista)
''',
"romano": '''
def a_romano(n):
    pares = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
             (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
    r = ""
    for v, s in pares:
        while n >= v: r += s; n -= v
    return r
''',
"desde_romano": '''
def desde_romano(s):
    v = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    tot = 0
    for i, c in enumerate(s):
        if i+1 < len(s) and v[c] < v[s[i+1]]: tot -= v[c]
        else: tot += v[c]
    return tot
''',
"racha": '''
def mayor_racha(lista):
    if not lista: return None
    mejor_e, mejor_n = lista[0], 1
    e, n = lista[0], 1
    for x in lista[1:]:
        if x == e: n += 1
        else: e, n = x, 1
        if n > mejor_n: mejor_e, mejor_n = e, n
    return (mejor_e, mejor_n)
''',
"camel": '''
def a_camel(s):
    partes = s.split("_")
    return partes[0] + "".join(p.capitalize() for p in partes[1:])
''',
"snake": '''
import re
def a_snake(s):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()
''',
"primos": '''
def primos(n):
    if n < 2: return []
    crib = [True]*(n+1); crib[0] = crib[1] = False
    for i in range(2, int(n**0.5)+1):
        if crib[i]:
            for j in range(i*i, n+1, i): crib[j] = False
    return [i for i, e in enumerate(crib) if e]
''',
"mcd": '''
def mcd(a, b):
    while b: a, b = b, a % b
    return a
''',
"intervalos": '''
def fusionar(intervalos):
    if not intervalos: return []
    r = []
    for ini, fin in sorted(intervalos):
        if r and ini <= r[-1][1]: r[-1] = (r[-1][0], max(r[-1][1], fin))
        else: r.append((ini, fin))
    return r
''',
"anagrama": '''
def es_anagrama(a, b):
    return sorted(a.lower().replace(" ", "")) == sorted(b.lower().replace(" ", ""))
''',
"comprimir": '''
def comprimir(s):
    if not s: return s
    r, act, n = "", s[0], 1
    for c in s[1:]:
        if c == act: n += 1
        else: r += act + str(n); act, n = c, 1
    r += act + str(n)
    return r if len(r) < len(s) else s
''',
"parentesis": '''
def balanceado(s):
    pares = {")":"(", "]":"[", "}":"{"}
    pila = []
    for c in s:
        if c in "([{": pila.append(c)
        elif c in pares:
            if not pila or pila.pop() != pares[c]: return False
    return not pila
''',
"transpuesta": '''
def transpuesta(m):
    if not m: return []
    return [list(f) for f in zip(*m)]
''',
"raiz_digital": '''
def raiz_digital(n):
    while n > 9: n = sum(int(d) for d in str(n))
    return n
''',
"sin_duplicados": '''
def sin_duplicados(lista):
    vistos, r = set(), []
    for x in lista:
        if x not in vistos: vistos.add(x); r.append(x)
    return r
''',
"n_mayor": '''
def n_esimo_mayor(lista, n):
    d = sorted(set(lista), reverse=True)
    return d[n-1] if 0 < n <= len(d) else None
''',
"bytes": '''
def formatear_bytes(n):
    if n < 1024: return f"{n} B"
    for u in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or u == "GB": return f"{n:.1f} {u}"
''',
"lotes": '''
def en_lotes(lista, tamano):
    return [lista[i:i+tamano] for i in range(0, len(lista), tamano)]
''',
"transpuesta": '''
def transpuesta(m):
    if not m:
        return []
    return [list(f) for f in zip(*m)]
''',

"intervalos": '''
def fusionar(intervalos):
    if not intervalos:
        return []
    ordenados = sorted(intervalos)
    salida = [ordenados[0]]
    for ini, fin in ordenados[1:]:
        pi, pf = salida[-1]
        if ini <= pf:
            salida[-1] = (pi, max(pf, fin))
        else:
            salida.append((ini, fin))
    return salida
''',

"parentesis": '''
def balanceado(s):
    pares = {")": "(", "]": "[", "}": "{"}
    pila = []
    for c in s:
        if c in "([{":
            pila.append(c)
        elif c in pares:
            if not pila or pila.pop() != pares[c]:
                return False
    return not pila
''',

"mediana": '''
def mediana(nums):
    if not nums:
        return None
    o = sorted(nums)
    n = len(o)
    if n % 2:
        return o[n // 2]
    return (o[n // 2 - 1] + o[n // 2]) / 2
''',

"top_frecuentes": '''
def top_frecuentes(texto, k):
    cuenta = {}
    for p in texto.lower().split():
        cuenta[p] = cuenta.get(p, 0) + 1
    orden = sorted(cuenta.items(), key=lambda par: (-par[1], par[0]))
    return orden[:k]
''',

"trozos": '''
def trozos(lista, n):
    if n <= 0:
        return []
    return [lista[i:i + n] for i in range(0, len(lista), n)]
''',

"dedup": '''
def dedup(lista):
    vistos = set()
    salida = []
    for x in lista:
        if x not in vistos:
            vistos.add(x)
            salida.append(x)
    return salida
''',

"binaria": '''
def binaria(lista, x):
    lo, hi = 0, len(lista) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if lista[mid] == x:
            return mid
        if lista[mid] < x:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',

"anidar": '''
def anidar(plano):
    salida = {}
    for clave, valor in plano.items():
        partes = clave.split(".")
        d = salida
        for p in partes[:-1]:
            d = d.setdefault(p, {})
        d[partes[-1]] = valor
    return salida
''',

"rle": '''
def comprimir(s):
    if not s:
        return ""
    salida = []
    actual = s[0]
    n = 1
    for c in s[1:]:
        if c == actual:
            n += 1
        else:
            salida.append(f"{actual}{n}")
            actual, n = c, 1
    salida.append(f"{actual}{n}")
    return "".join(salida)
''',

"anagrama": '''
def es_anagrama(a, b):
    na = sorted(a.lower().replace(" ", ""))
    nb = sorted(b.lower().replace(" ", ""))
    return na == nb
''',

"movil": '''
def promedio_movil(nums, ventana):
    if ventana <= 0 or len(nums) < ventana:
        return []
    return [sum(nums[i:i + ventana]) / ventana
            for i in range(len(nums) - ventana + 1)]
''',

"bytes_humano": '''
def formatear_bytes(n):
    if n < 1024:
        return f"{n} B"
    for unidad in ("KB", "MB", "GB"):
        n = n / 1024
        if n < 1024 or unidad == "GB":
            return f"{n:.1f} {unidad}"
    return f"{n:.1f} GB"
''',

"query": '''
def parsear_query(s):
    if not s:
        return {}
    salida = {}
    for par in s.split("&"):
        if not par:
            continue
        if "=" in par:
            k, v = par.split("=", 1)
        else:
            k, v = par, ""
        salida[k] = v
    return salida
''',
"islas": '''
def contar_islas(grid):
    if not grid:
        return 0
    filas, cols = len(grid), len(grid[0])
    visto = set()
    def marcar(f, c):
        pila = [(f, c)]
        while pila:
            x, y = pila.pop()
            if (x, y) in visto:
                continue
            if x < 0 or y < 0 or x >= filas or y >= cols:
                continue
            if grid[x][y] != 1:
                continue
            visto.add((x, y))
            pila.extend([(x+1,y), (x-1,y), (x,y+1), (x,y-1)])
    n = 0
    for f in range(filas):
        for c in range(cols):
            if grid[f][c] == 1 and (f, c) not in visto:
                marcar(f, c)
                n += 1
    return n
''',

"levenshtein": '''
def distancia(a, b):
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (ca != cb)))
        prev = cur
    return prev[-1]
''',

"password": '''
def validar_password(p):
    if len(p) < 8:
        return False
    tiene_may = any(c.isupper() for c in p)
    tiene_min = any(c.islower() for c in p)
    tiene_dig = any(c.isdigit() for c in p)
    tiene_sim = any(not c.isalnum() for c in p)
    return tiene_may and tiene_min and tiene_dig and tiene_sim
''',

"base_n": '''
def a_base(n, base):
    if n == 0:
        return "0"
    digitos = "0123456789abcdef"
    salida = []
    while n:
        salida.append(digitos[n % base])
        n //= base
    return "".join(reversed(salida))
''',

"particion": '''
def pares_primero(nums):
    return [x for x in nums if x % 2 == 0] + [x for x in nums if x % 2 != 0]
''',

"interseccion": '''
def interseccion(a, b):
    sb = set(b)
    salida = []
    for x in a:
        if x in sb and (not salida or salida[-1] != x):
            salida.append(x)
    return salida
''',

"dias_entre": '''
from datetime import date
def dias_entre(a, b):
    fa = date.fromisoformat(a)
    fb = date.fromisoformat(b)
    return abs((fb - fa).days)
''',

"escapar_csv": '''
def campo_csv(s):
    if any(c in s for c in [",", chr(34), chr(10)]):
        interno = s.replace(chr(34), chr(34) * 2)
        return chr(34) + interno + chr(34)
    return s
''',

"titulo": '''
def titular(s):
    menores = {"de", "del", "la", "las", "el", "los", "y"}
    palabras = s.lower().split()
    salida = []
    for i, p in enumerate(palabras):
        if i > 0 and p in menores:
            salida.append(p)
        else:
            salida.append(p.capitalize())
    return " ".join(salida)
''',

"aplanar_prof": '''
def aplanar_hasta(lista, profundidad):
    if profundidad <= 0:
        return list(lista)
    salida = []
    for x in lista:
        if isinstance(x, list):
            salida.extend(aplanar_hasta(x, profundidad - 1))
        else:
            salida.append(x)
    return salida
''',

"romanos_suma": '''
def sumar_romanos(a, b):
    valores = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    def a_entero(r):
        total = 0
        for i, c in enumerate(r):
            v = valores[c]
            if i + 1 < len(r) and valores[r[i+1]] > v:
                total -= v
            else:
                total += v
        return total
    def a_romano(n):
        tabla = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
                 (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
        salida = []
        for valor, simbolo in tabla:
            while n >= valor:
                salida.append(simbolo)
                n -= valor
        return "".join(salida)
    return a_romano(a_entero(a) + a_entero(b))
''',

"cola_prioridad": '''
def atender(tareas):
    return [nombre for _, nombre in sorted(tareas, key=lambda t: t[0])]
''',

"camino_dict": '''
def obtener(d, camino, defecto=None):
    actual = d
    for parte in camino.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return defecto
        actual = actual[parte]
    return actual
''',

"reintentos": '''
def con_reintentos(fn, veces):
    ultimo = None
    for _ in range(veces):
        try:
            return fn()
        except Exception as e:
            ultimo = e
    raise ultimo
''',
}


def main():
    print(f"\n{'='*62}\n  VERIFICACION DEL BANCO: {len(TAREAS)} tareas\n{'='*62}\n")
    faltan = [t["id"] for t in TAREAS if t["id"] not in REFERENCIA]
    if faltan:
        print(f"  Sin implementacion de referencia: {faltan}\n")
    ok_total = 0
    for t in TAREAS:
        ref = REFERENCIA.get(t["id"])
        if ref is None:
            print(f"  ????  {t['id']}")
            continue
        ok, err = probar(ref, t["tests"])
        ok_total += ok
        print(f"  {'ok   ' if ok else 'FALLA'} {t['id']:<18} {err}")
    print(f"\n  {ok_total}/{len(TAREAS)} tests correctos")
    if ok_total != len(TAREAS):
        print("  >>> El defecto esta en el BANCO, no en los modelos.")
    return 0 if ok_total == len(TAREAS) else 1


if __name__ == "__main__":
    sys.exit(main())
