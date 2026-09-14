#!/usr/bin/env bash
# Perfil de CODIGO de un modelo, en un comando.
#
# POR QUE EXISTE (08/09/2026): el objetivo es barrer muchos modelos de <=9B
# buscando el que mejor codifique por GB de VRAM. Medir uno a mano son tres
# bancos coordinados; esto lo deja en una linea y con salida comparable.
#
#   uso: perfil_codigo.sh <ruta.gguf> [CTX] [CACHE_K] [CACHE_V]
#
# Mide SOLO codigo, verificado POR EJECUCION -- ningun modelo opina:
#   funciones  eval_expertos, seccion CODIGO: 53 funciones desde cero
#   scripts    eval_scripts: script operativo de ~30 lineas, ejecutado
#   edicion    eval_edicion: 13 tareas sobre codigo que ya existe, con
#              tests de REGRESION que detectan si borra lo que funcionaba
#   formato    eval_formato_edicion: si sabe emitir bloques SEARCH/REPLACE.
#              No es un detalle de estilo: el que sabe edita archivos del
#              DOBLE de tamano, porque el archivo no vuelve en la respuesta.
#
# El razonamiento NO se mide: en el diseno del MCP se lo queda el harness
# (Claude Code / opencode) y el modelo local solo programa y usa herramientas.
set -u
cd "$(dirname "$0")/.."
GGUF=${1:?falta la ruta al .gguf}
CTX=${2:-16384}; CK=${3:-q4_0}; CV=${4:-q4_0}
[ -f "$GGUF" ] || { echo "no existe: $GGUF"; exit 2; }
Q=$(basename "$GGUF" .gguf)
# Dos carpetas pueden traer el MISMO nombre de archivo -- mismo modelo, otro
# cuantizador (p.ej. uno comun y uno con imatrix). La etiqueta es la clave con
# la que se guarda y se omite lo ya medido, asi que sin esto la segunda
# carpeta se omitia entera como "ya medida" y los logs se pisaban. Encontrado
# el 11/09/2026 antes de barrer Spark: 21 archivos, 16 nombres distintos.
# Lo que vive directo en modelos/ conserva el nombre, para no romper lo medido.
DIR=$(basename "$(dirname "$GGUF")")
[ "$DIR" != "modelos" ] && Q="$Q@${DIR##*-}"
GB=$(stat -c%s "$GGUF" | awk '{printf "%.2f",$1/1073741824}')
SAL=logs/perfil_codigo.txt
exec 9>/tmp/.perfil.lock
flock -n 9 || { echo "ya hay un perfil corriendo"; exit 1; }
matar(){ for p in $(ss -lptnH "sport = :$1" | grep -o 'pid=[0-9]*'|cut -d= -f2|sort -u); do kill $p 2>/dev/null; done; }

# El motor lo elige herramientas/elegir_motor.py leyendo general.architecture
# del GGUF. Si ninguno la conoce, avisa en vez de fallar a mitad de carga.
ARQ=$(python3 herramientas/elegir_motor.py --arch "$GGUF" 2>/dev/null)
python3 herramientas/elegir_motor.py "$GGUF" >/dev/null 2>&1 || {
  echo "PERFIL|$Q|$GB GB|arquitectura '$ARQ': ningun motor compilado la conoce" | tee -a "$SAL"; exit 1; }

matar 8080
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 800 ]; do sleep 2; done
sleep 3
PRINCIPAL_GGUF="../../$GGUF" PRINCIPAL_CTX="$CTX" PRINCIPAL_CACHE_K="$CK" PRINCIPAL_CACHE_V="$CV" PRINCIPAL_EXTRA="${PRINCIPAL_EXTRA:-}" \
  setsid --fork nohup bash backends/principal/iniciar-linux.sh > /tmp/perfil.log 2>&1 </dev/null
ok=0; for i in $(seq 1 60); do curl -sf -m 2 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 && { ok=1; break; }; sleep 3; done
[ $ok = 0 ] && { echo "PERFIL|$Q|$GB GB|NO CARGA a ctx $CTX|OOM=$(grep -ci 'out of memory' /tmp/perfil.log)" | tee -a "$SAL"; exit 1; }
VRAM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)

L=logs/perfil_${Q}
timeout 900  python3 -u pruebas/calidad/eval_expertos.py 8080          > ${L}_fun.log 2>&1
timeout 600  python3 -u pruebas/calidad/eval_scripts.py  8080 "$Q" 1   > ${L}_scr.log 2>&1
timeout 1500 python3 -u pruebas/calidad/eval_edicion.py  8080 "$Q" 1   > ${L}_edi.log 2>&1
# Cuarto banco (09/09/2026): si el modelo sabe emitir bloques SEARCH/REPLACE
# edita archivos del DOBLE de tamano, porque el archivo no vuelve en la
# respuesta. Es una propiedad del modelo independiente de lo bien que programe,
# y hasta hoy el barrido no la miraba. Aider lo mide como "percent using
# correct edit format" y envia a reescribir entero a los que no lo cumplen.
EVAL_FORMATO_PUERTO=8080 EVAL_FORMATO_ETIQUETA="$Q" \
  timeout 1500 python3 -u pruebas/calidad/eval_formato_edicion.py 1 > ${L}_fmt.log 2>&1

FUN=$(grep -oE 'CODIGO: [0-9]+/[0-9]+' ${L}_fun.log | head -1 | cut -d' ' -f2)
SX=$(grep -cE 'SyntaxError' ${L}_fun.log)
SCR=$(grep -oE '[0-9]+/[0-9]+' ${L}_scr.log | tail -1)
EDI=$(grep -oE 'EDICION: [0-9]+/[0-9]+' ${L}_edi.log | head -1 | cut -d' ' -f2)
ROM=$(grep -oE 'rompieron la regresion: [0-9]+' ${L}_edi.log | grep -oE '[0-9]+$')
# De la tabla final del banco de formato: la fila `bloques` trae
# formato/aplica/PASA y los caracteres generados.
FMT=$(awk '/^  bloques /{print $2; exit}'  ${L}_fmt.log)
FCH=$(awk '/^  bloques /{print $6; exit}'  ${L}_fmt.log)
ECH=$(awk '/^  entero  /{print $6; exit}'  ${L}_fmt.log)
echo "PERFIL|$Q|$GB GB|arq=$ARQ|ctx=$CTX|${VRAM} MiB|funciones=${FUN:-cortado}|sintaxis=$SX|scripts=${SCR:-?}|edicion=${EDI:-?}|rompio_regresion=${ROM:-?}|formato_bloques=${FMT:-?}|genera=${FCH:-?}/${ECH:-?}" | tee -a "$SAL"
