#!/usr/bin/env bash
# Barrido COMPLETO de programacion: los 4 bancos x 5 repeticiones, por modelo.
#
# POR QUE EXISTE (11/09/2026): una repeticion sobre 13 tareas no alcanza para
# elegir -- el 09/09 dio vuelta la conclusion dos veces, en direcciones opuestas.
# perfil_codigo.sh ejecuta cada banco UNA vez; esto ejecuta los cuatro cinco veces.
#
#   funciones  eval_expertos, SOLO la seccion de codigo (53 funciones) x5
#   scripts    eval_scripts, 4 scripts operativos ejecutados x5
#   edicion    eval_edicion, 13 ediciones con regresion x5
#   formato    eval_formato_edicion, las 13 en bloques Y en entero x5
#
# CRIBA, FIJADA ANTES DE MEDIR: una primera edicion de 1 repeticion. Menos de
# 7/13 = roto, y no se le ejecuta nada mas. Un modelo roto es LENTO -- genera
# basura hasta agotar los tokens -- y cinco repeticiones de eso no informan.
#
# Un modelo por vez, de menor a mayor. Se omiten los que ya tienen su linea en
# logs/barrido_5rep.txt, asi que se puede cortar y retomar. Si se corta a mitad
# de un modelo, ese modelo se vuelve a ejecutar entero.
#
#   uso: PRINCIPAL_EXTRA="--reasoning off" barrer_5rep.sh '<patron_gguf>' [CTX] [K] [V]
set -u
cd "$(dirname "$0")/.."
PAT=${1:?falta el patron de gguf, entre comillas simples}
CTX=${2:-16384}; CK=${3:-q4_0}; CV=${4:-q4_0}
REPES=${REPES:-5}
SAL=logs/barrido_5rep.txt
PY=python3
exec 9>/tmp/.barrer_5rep.lock
flock -n 9 || { echo "ya hay un barrido de 5 repeticiones corriendo"; exit 1; }

# Por PID y filtrando por el nombre exacto del proceso: nunca pkill -f, que el
# 08/09 mato la propia shell tres veces y el 09/09 un banco en curso.
matar() { for p in $(ps -eo pid,comm --no-headers | awk '$2=="llama-server"{print $1}'); do kill "$p" 2>/dev/null; done; }
vram() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits; }
cargar() {
  matar
  until [ "$(vram)" -lt 800 ]; do sleep 2; done; sleep 3
  PRINCIPAL_GGUF="../../$1" PRINCIPAL_CTX="$CTX" PRINCIPAL_CACHE_K="$CK" PRINCIPAL_CACHE_V="$CV" \
  PRINCIPAL_EXTRA="${PRINCIPAL_EXTRA:-}" \
    setsid --fork nohup bash backends/principal/iniciar-linux.sh > logs/b5_carga.log 2>&1 </dev/null
  for _ in $(seq 1 60); do
    curl -sf -m 2 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 && return 0; sleep 3
  done
  return 1
}

for F in $(ls -Sr $PAT 2>/dev/null); do
  Q=$(basename "$F" .gguf)
  DIR=$(basename "$(dirname "$F")")
  [ "$DIR" != "modelos" ] && Q="$Q@${DIR##*-}"
  if grep -q "^B5|$Q|" "$SAL" 2>/dev/null; then echo "  (ya medido: $Q)"; continue; fi
  GB=$(stat -c%s "$F" | awk '{printf "%.2f",$1/1073741824}')
  echo "  -> $Q  ($GB GB)  $(date +%H:%M)"
  if ! cargar "$F"; then echo "B5|$Q|$GB GB|NO CARGA" | tee -a "$SAL"; continue; fi
  V=$(vram)
  L=logs/b5_$Q

  timeout 1800 $PY -u pruebas/calidad/eval_edicion.py 8080 "$Q-criba" 1 > "${L}_criba.log" 2>&1
  CR=$(grep -oE 'EDICION: [0-9]+' "${L}_criba.log" | grep -oE '[0-9]+$')
  if [ "${CR:-0}" -lt 7 ]; then
    echo "B5|$Q|$GB GB|${V} MiB|ROTO|criba=${CR:-?}/13" | tee -a "$SAL"; continue
  fi

  timeout 7200 $PY -u pruebas/calidad/eval_edicion.py 8080 "$Q" "$REPES" > "${L}_edi.log" 2>&1
  EVAL_FORMATO_PUERTO=8080 EVAL_FORMATO_ETIQUETA="$Q" \
    timeout 7200 $PY -u pruebas/calidad/eval_formato_edicion.py "$REPES" > "${L}_fmt.log" 2>&1
  timeout 3600 $PY -u pruebas/calidad/eval_scripts.py 8080 "$Q" "$REPES" > "${L}_scr.log" 2>&1
  FA=0; FT=0
  for r in $(seq 1 "$REPES"); do
    EVAL_EXPERTOS_SOLO_CODIGO=1 timeout 2400 \
      $PY -u pruebas/calidad/eval_expertos.py 8080 "$Q-r$r" > "${L}_fun$r.log" 2>&1
    c=$(grep -oE 'CODIGO: [0-9]+/[0-9]+' "${L}_fun$r.log" | head -1 | cut -d' ' -f2)
    [ -n "$c" ] && { FA=$((FA + ${c%/*})); FT=$((FT + ${c#*/})); }
  done

  EDI=$(grep -oE 'EDICION: [0-9]+/[0-9]+' "${L}_edi.log" | head -1 | cut -d' ' -f2)
  ROM=$(grep -oE 'rompieron la regresion: [0-9]+' "${L}_edi.log" | grep -oE '[0-9]+$')
  read -r _ BF BA BP BR BC _ <<< "$(awk '/^  bloques /{print; exit}' "${L}_fmt.log")"
  read -r _ _ _ EP ER _ _ <<< "$(awk '/^  entero  /{print; exit}' "${L}_fmt.log")"
  SCR=$(grep -oE '[0-9]+/[0-9]+' "${L}_scr.log" | tail -1)
  echo "B5|$Q|$GB GB|${V} MiB|edicion=${EDI:-?}|rompio=${ROM:-?}|bloques_formato=${BF:-?}|bloques_aplica=${BA:-?}|bloques_pasa=${BP:-?}|bloques_rompio=${BR:-?}|bloques_chars=${BC:-?}|entero_pasa=${EP:-?}|entero_rompio=${ER:-?}|funciones=$FA/$FT|scripts=${SCR:-?}|criba=$CR/13" | tee -a "$SAL"
done
matar
echo "  barrido terminado $(date '+%F %H:%M')"
