#!/usr/bin/env bash
# Perfil de CODIGO completo sobre VARIOS modelos, uno tras otro.
#
# POR QUE EXISTE (09/09/2026): el objetivo es encontrar el modelo mas pequeño que
# programe bien, para que el MCP le delegue. `perfil_codigo.sh` mide UNO con los
# cuatro bancos; `barrer_codigo.sh` recorre varios pero solo con dos. Esto
# recorre varios con los cuatro, que es lo que hace falta para decidir.
#
# De MAS PEQUEÑO a MAS GRANDE a proposito: si uno de 3 GB ya sirve, los de 5 GB
# no hace falta medirlos, y la GPU se libera antes.
#
#   uso: barrer_perfiles.sh '<patron_gguf>' [CTX] [CACHE_K] [CACHE_V]
#   ej:  barrer_perfiles.sh 'modelos/*.gguf'
#        barrer_perfiles.sh 'modelos/pequenos/*.gguf' 16384 q8_0 q8_0
#
# Salta los que ya estan en logs/perfil_codigo.txt, asi que se puede cortar y
# retomar. Para volver a medir uno, borra su linea de ese archivo.
set -u
cd "$(dirname "$0")/.."
PAT=${1:?falta el patron de gguf, entre comillas simples}
CTX=${2:-16384}; CK=${3:-q4_0}; CV=${4:-q4_0}
SAL=logs/perfil_codigo.txt

ARCHIVOS=$(ls -Sr $PAT 2>/dev/null)
[ -z "$ARCHIVOS" ] && { echo "no hay ningun .gguf que coincida con: $PAT"; exit 2; }
echo "  a medir: $(echo "$ARCHIVOS" | wc -l) modelos, ctx $CTX, cache $CK/$CV"

for F in $ARCHIVOS; do
  Q=$(basename "$F" .gguf)
  # Dos carpetas pueden traer el MISMO nombre de archivo -- mismo modelo, otro
  # cuantizador (p.ej. uno comun y uno con imatrix). La etiqueta es la clave con
  # la que se guarda y se omite lo ya medido, asi que sin esto la segunda
  # carpeta se omitia entera como "ya medida" y los logs se pisaban. Encontrado
  # el 11/09/2026 antes de barrer Spark: 21 archivos, 16 nombres distintos.
  # Lo que vive directo en modelos/ conserva el nombre, para no romper lo medido.
  DIR=$(basename "$(dirname "$F")")
  [ "$DIR" != "modelos" ] && Q="$Q@${DIR##*-}"
  if grep -q "^PERFIL|$Q|" "$SAL" 2>/dev/null; then
    echo "  (ya medido, se salta: $Q)"; continue
  fi
  echo "  -> $Q"
  herramientas/perfil_codigo.sh "$F" "$CTX" "$CK" "$CV" || echo "     (fallo, sigue)"
done

echo
herramientas/tabla_codigo.py
