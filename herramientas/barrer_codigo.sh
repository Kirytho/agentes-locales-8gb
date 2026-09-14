#!/usr/bin/env bash
# Barrido de CODIGO puro sobre las cuantizaciones de un modelo.
#
# CONTEXTO (08/09/2026): el plan es un servidor MCP que le delegue a un modelo
# local la PROGRAMACION y el USO DE HERRAMIENTAS, mientras el razonamiento se
# queda en el harness (Claude Code / opencode). Hermes queda descartado.
#
# ESO CAMBIA DOS COSAS respecto de los barridos anteriores:
#
# 1. NO SE MIDE RAZONAMIENTO. Solo la seccion de CODIGO de eval_expertos, que
#    se verifica EJECUTANDO, mas eval_scripts (script operativo ejecutado).
#    Ninguna opina: las dos ejecutan el codigo y comparan contra la respuesta
#    calculada. Es el unico tipo de medida que no se puede fabricar, y ayer
#    quedo claro que fabricar con formato correcto es lo que hacen estos
#    modelos cuando fallan.
#
# 2. EL CONTEXTO ES PEQUEÑO. Sin Hermes no hay piso de 64.000 ni su presupuesto
#    fijo de ~22.700 tokens. Medido: el enunciado de una tarea de codigo son
#    52-131 chars (~32 tokens). Con 16.384 sobra para el enunciado, el prompt
#    de sistema y un archivo. Y con ventana pequeña ENTRAN TODAS las
#    cuantizaciones, incluidas las dos que el piso de Hermes dejaba fuera.
#
#   uso: barrer_codigo.sh <patron_gguf> <CACHE_K> <CACHE_V> <CTX>
#   ej:  barrer_codigo.sh 'modelos/barrido_bits/K2-Horizon-7B-*.gguf' q8_0 q8_0 16384
set -u
cd "$(dirname "$0")/.."
PAT=${1:?falta el patron de gguf}
CK=${2:-q8_0}; CV=${3:-q8_0}; CTX=${4:-16384}
SAL=logs/codigo_${CK}_${CV}_${CTX}.txt
exec 9>/tmp/.barrer_codigo.lock
flock -n 9 || { echo "ya hay un barrido corriendo"; exit 1; }
matar(){ for p in $(ss -lptnH "sport = :$1" | grep -o 'pid=[0-9]*'|cut -d= -f2|sort -u); do kill $p 2>/dev/null; done; }

# De mas pequeño a mas grande: si el de 1 bit ya sirve, no hace falta el de 5 GB.
for F in $(ls -Sr $PAT 2>/dev/null); do
  q=$(basename "$F" .gguf)
  grep -q "^COD|$q|" "$SAL" 2>/dev/null && { echo "  (ya medido: $q)"; continue; }
  GB=$(stat -c%s "$F" | awk '{printf "%.2f",$1/1073741824}')
  matar 8080
  until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 800 ]; do sleep 2; done
  sleep 3
  PRINCIPAL_GGUF="../../$F" PRINCIPAL_CTX="$CTX" PRINCIPAL_CACHE_K="$CK" PRINCIPAL_CACHE_V="$CV" \
      setsid --fork nohup bash backends/principal/iniciar-linux.sh > /tmp/bc.log 2>&1 </dev/null
  ok=0
  for i in $(seq 1 50); do curl -sf -m 2 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 && { ok=1; break; }; sleep 3; done
  [ $ok = 0 ] && { echo "COD|$q|$GB GB|NO CARGA" | tee -a "$SAL"; continue; }
  V=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  L=logs/cod_${q}_${CK}${CV}
  timeout 900 python3 -u pruebas/calidad/eval_expertos.py 8080 > ${L}_exp.log 2>&1
  timeout 600 python3 -u pruebas/calidad/eval_scripts.py 8080 "$q" 1 > ${L}_scr.log 2>&1
  # El banco YA IMPRIME el resumen: "  CODIGO: 44/53". Leerlo es lo correcto.
  # NO contar verbos a mano: el 08/09/2026 se conto `OK` cuando la seccion de
  # codigo escribe `PASA`, asi que TODOS los modelos salieron 0 y estuve por
  # descartar la familia entera. Q2_K daba 44/53.
  CO=$(grep -oE "CODIGO: [0-9]+/[0-9]+" ${L}_exp.log | head -1 | cut -d' ' -f2)
  RZ=$(grep -oE "RAZONAMIENTO: [0-9]+/[0-9]+" ${L}_exp.log | head -1 | cut -d' ' -f2)
  SX=$(grep -cE 'SyntaxError' ${L}_exp.log)
  SC=$(grep -oE "[0-9]+/[0-9]+" ${L}_scr.log | tail -1)
  echo "COD|$q|$GB GB|${V} MiB|codigo=${CO:-cortado}|sintaxis_rota=${SX}|razonar=${RZ:--}|scripts=${SC:-?}" | tee -a "$SAL"
done
echo "FIN-CODIGO"
