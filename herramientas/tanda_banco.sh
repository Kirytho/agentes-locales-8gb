#!/usr/bin/env bash
# Una serie corta del banco, en PRIMER PLANO.
#
# Por que en primer plano: el 06/09/2026 el guardian de tareas en segundo plano
# del harness mato el barrido CUATRO veces por "poca memoria" -- la ultima con
# 19 GiB libres y presion 0,03%, es decir que no era memoria real del sistema. En
# primer plano no fallo una sola vez en 6 series seguidas.
#
# Por que 2 repeticiones: son 10 ejecuciones, ~250-400 s, por debajo del tope de
# 600 s por comando del harness.
#
# Por que vive en el repo y no en /tmp: la primera version estaba en el
# scratchpad de la sesion y se perdio al reiniciar la maquina.
#
#   uso: tanda_banco.sh <gguf> <etiqueta> <ctx> <n_tanda>
set -u
cd "$(dirname "$0")/.."
GG="$1"; ET="$2"; CTX="$3"; T="$4"
SAL=logs/fase3; mkdir -p $SAL
matar() { for p in $(ss -lptnH "sport = :$1" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do kill $p 2>/dev/null; done; }

# El intermediario tiene que estar activo: el grabador reenvia a 8086.
curl -sf -m 2 http://127.0.0.1:8086/v1/models >/dev/null 2>&1 || {
    ( cd intermediario && setsid --fork nohup python3 run.py > ../logs/orq.log 2>&1 < /dev/null )
    for _ in $(seq 1 40); do curl -sf -m 2 http://127.0.0.1:8086/v1/models >/dev/null 2>&1 && break; sleep 2; done; }

# El backend se inicia si no esta, o si el ctx con el que se ejecuta no es el pedido.
actual=$(curl -sf -m 2 http://127.0.0.1:8086/v1/models 2>/dev/null \
         | grep -o '"id":"principal"[^}]*"context_length":[0-9]*' | grep -o '[0-9]*$')
if [ "${actual:-0}" != "$CTX" ]; then
    matar 8080
    for _ in $(seq 1 40); do
        u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
        [ "$u" -lt 1200 ] && break; sleep 2; done
    PRINCIPAL_GGUF="../../$GG" PRINCIPAL_CTX="$CTX" setsid --fork nohup \
        bash backends/principal/iniciar-linux.sh > "$SAL/$ET.backend.log" 2>&1 < /dev/null
    for _ in $(seq 1 60); do curl -sf -m 2 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 && break; sleep 3; done
    actual=$(curl -sf -m 2 http://127.0.0.1:8086/v1/models 2>/dev/null \
             | grep -o '"id":"principal"[^}]*"context_length":[0-9]*' | grep -o '[0-9]*$')
fi
[ "${actual:-0}" = "$CTX" ] || { echo "ABORTA|$ET|ctx es ${actual:-nada}, se pedia $CTX"; exit 1; }

matar 8099; sleep 1
rm -rf "/tmp/f3_$ET"
BANCO_DIR="/tmp/f3_$ET" BANCO_GRABACION="/tmp/f3_$ET.jsonl" \
BANCO_REPES=2 BANCO_LIMITE=420 \
    python3 pruebas/calidad/eval_stack_completo.py \
    > "$SAL/$ET.t$T.log" 2>&1
grep -E "^(OK |MAL)" "$SAL/$ET.t$T.log" | sed 's/^/  /'

# El acumulado se rearma SOLO con series completas de 10: una serie cortada a
# la mitad deja los escenarios desparejos y hay que repetirla, no sumarla.
: > "$SAL/$ET.banco.log"
for f in $SAL/$ET.t*.log; do
    n=$(grep -cE '^(OK |MAL)' "$f")
    [ "$n" = "10" ] && grep -E '^(OK |MAL)' "$f" >> "$SAL/$ET.banco.log" \
                    || echo "  (tanda incompleta, $n corridas: $(basename $f) -- repetirla)"
done
awk '/^(OK |MAL)/{t++;if($1=="OK")o++} END{print "ACUMULADO|'"$ET"'|"o"/"t"|de 60"}' "$SAL/$ET.banco.log"
bpid=$(ss -lptnH 'sport = :8080' | grep -o 'pid=[0-9]*' | cut -d= -f2|head -1)
echo "RAM|$(free -g | sed -n 2p | awk '{print $7}')Gi libres|backend $(ps -o rss= -p ${bpid:-1} 2>/dev/null | awk '{printf "%.1f GB",$1/1048576}')"
