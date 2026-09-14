#!/usr/bin/env bash
# Duelo de dos modelos en CODIGO, 5 ejecuciones cada uno, ALTERNADAS.
#
# POR QUE 5 Y NO 1: el 07/09/2026 se probo TurboQuant con UNA ejecucion, dio
# 21/25 contra 20/25 (p=1,0) y se reporto "no hay diferencia". Con 5 ejecuciones
# la diferencia aparecio y la confirmaron dos pruebas distintas. La regla de 5
# del proyecto existe por eso.
#
# POR QUE ALTERNADAS: si a mitad de camino cambia algo de la maquina (termica,
# memoria, otro proceso), alternando le pega parejo a los dos; en bloques le
# pegaria solo al segundo y apareceria como si ese modelo fuera peor.
set -u
cd "$(dirname "$0")/.."
A=${1:?falta modelo A}; B=${2:?falta modelo B}
CK=${3:-q4_0}; CV=${4:-q4_0}; CTX=${5:-16384}
SAL=logs/duelo_codigo.txt
exec 9>/tmp/.duelo.lock
flock -n 9 || { echo "ya hay un duelo corriendo"; exit 1; }
matar(){ for p in $(ss -lptnH "sport = :$1" | grep -o 'pid=[0-9]*'|cut -d= -f2|sort -u); do kill $p 2>/dev/null; done; }

vuelta(){ # $1 gguf  $2 etiqueta  $3 n
  grep -q "^D|$2|v$3|" "$SAL" 2>/dev/null && { echo "  (ya: $2 v$3)"; return; }
  matar 8080
  until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 800 ]; do sleep 2; done
  sleep 3
  PRINCIPAL_GGUF="../../$1" PRINCIPAL_CTX="$CTX" PRINCIPAL_CACHE_K="$CK" PRINCIPAL_CACHE_V="$CV" \
    setsid --fork nohup bash backends/principal/iniciar-linux.sh > /tmp/du.log 2>&1 </dev/null
  ok=0; for i in $(seq 1 50); do curl -sf -m 2 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 && { ok=1; break; }; sleep 3; done
  [ $ok = 0 ] && { echo "D|$2|v$3|NO CARGA" | tee -a "$SAL"; return; }
  L=logs/duelo_${2}_v$3
  timeout 900 python3 -u pruebas/calidad/eval_expertos.py 8080 > ${L}_exp.log 2>&1
  timeout 600 python3 -u pruebas/calidad/eval_scripts.py 8080 "$2" 1 > ${L}_scr.log 2>&1
  echo "D|$2|v$3|codigo=$(grep -oE 'CODIGO: [0-9]+/[0-9]+' ${L}_exp.log|head -1|cut -d' ' -f2)|sintaxis=$(grep -cE SyntaxError ${L}_exp.log)|scripts=$(grep -oE '[0-9]+/[0-9]+' ${L}_scr.log|tail -1)" | tee -a "$SAL"
}
for v in 1 2 3 4 5; do
  vuelta "modelos/K2-Horizon-7B-${A}.gguf" "$A" $v
  vuelta "modelos/K2-Horizon-7B-${B}.gguf" "$B" $v
done
echo FIN-DUELO
