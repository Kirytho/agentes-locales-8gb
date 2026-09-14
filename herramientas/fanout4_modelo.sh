#!/usr/bin/env bash
# Una ejecucion de abanico para UN modelo. La metrica que importa es
# delegate_task, no el puntaje: los dos pilotos con Q4_K_M dieron 0/16 y la
# pregunta abierta es si ALGUN modelo reparte el trabajo cuando se lo piden.
# Cada modelo va a su ctx MAXIMO medido en fase 1, porque el techo de ramas
# sale de la reserva compartida de KV (~11.308 tokens por subagente).
#   uso: fanout_modelo.sh <gguf> <etiqueta> <ctx> <rep>
set -u
cd "$(dirname "$0")/.."
GG="$1"; ET="$2"; CTX="$3"; REP="${4:-1}"
SAL=logs/fanout4; mkdir -p $SAL
matar() { for p in $(ss -lptnH "sport = :$1" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do kill $p 2>/dev/null; done; }

curl -sf -m 2 http://127.0.0.1:8086/v1/models >/dev/null 2>&1 || {
    ( cd intermediario && setsid --fork nohup python3 run.py > ../logs/orq.log 2>&1 < /dev/null )
    for _ in $(seq 1 40); do curl -sf -m 2 http://127.0.0.1:8086/v1/models >/dev/null 2>&1 && break; sleep 2; done; }

actual=$(curl -sf -m 2 http://127.0.0.1:8086/v1/models 2>/dev/null \
         | grep -o '"id":"principal"[^}]*"context_length":[0-9]*' | grep -o '[0-9]*$')
if [ "${actual:-0}" != "$CTX" ]; then
    matar 8080
    # nvidia-smi reporta la VRAM liberada ANTES de que el driver termine de
    # soltarla. IQ4_XS fallo DOS veces con cudaMalloc out of memory a un ctx
    # que ya habia corrido 60 veces el mismo dia; con la GPU realmente vacia
    # cargo a la primera. El umbral de 1200 MiB era demasiado alto: en reposo
    # el escritorio usa ~590 MiB, asi que 1200 daba por libre una GPU que
    # todavia tenia ~600 MiB del proceso anterior. Umbral 700 + 3 s de gracia.
    for _ in $(seq 1 60); do
        u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
        [ "$u" -lt 700 ] && break; sleep 2; done
    sleep 3
    PRINCIPAL_GGUF="../../$GG" PRINCIPAL_CTX="$CTX" setsid --fork nohup \
        bash backends/principal/iniciar-linux.sh > "$SAL/$ET.backend.log" 2>&1 < /dev/null
    for _ in $(seq 1 60); do curl -sf -m 2 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 && break; sleep 3; done
    actual=$(curl -sf -m 2 http://127.0.0.1:8086/v1/models 2>/dev/null \
             | grep -o '"id":"principal"[^}]*"context_length":[0-9]*' | grep -o '[0-9]*$')
fi
[ "${actual:-0}" = "$CTX" ] || { echo "FANOUT|$ET|NO CARGA a ctx $CTX|OOM:$(grep -ci 'out of memory' $SAL/$ET.backend.log)"; exit 1; }

matar 8099; sleep 1
D=/tmp/fanc_${ET}_r$REP
rm -rf $D
BANCO_DIR=$D BANCO_GRABACION=$D.jsonl \
BANCO_REPES=1 BANCO_LIMITE=900 \
    python3 pruebas/calidad/eval_fanout_pequeno.py > "$SAL/$ET.r$REP.log" 2>&1

python3 - "$ET" "$CTX" "$REP" "$D.jsonl" "$SAL/$ET.r$REP.log" <<'PY'
import json,sys,collections,re
et,ctx,rep,cable,log=sys.argv[1:6]
n=collections.Counter()
try:
    for ln in open(cable):
        try: d=json.loads(ln)
        except: continue
        for tc in ((d.get('respuesta') or {}).get('tool_calls') or []):
            n[tc.get('nombre')]+=1
except FileNotFoundError: pass
txt=open(log).read()
m=re.search(r'^(OK |MAL) fanout +([\d.]+)s.*?(\d+)/16|no escribio', txt, re.M)
seg=re.search(r'([\d.]+)s', txt.split('\n')[0]) if txt else None
ok = txt.count('\nOK  fanout')>0 or txt.startswith('OK  fanout')
corto = 'NO TERMINO' in txt
det=re.search(r'22786=\d+\s+(.*)', txt)
print(f"FANOUT|{et}|ctx={ctx}|rep={rep}|delegate={n.get('delegate_task',0)}"
      f"|read_file={n.get('read_file',0)}|terminal={n.get('terminal',0)}"
      f"|exec={n.get('execute_code',0)}|{'CORTO' if corto else 'termino'}"
      f"|{(det.group(1)[:60] if det else '?')}")
PY
