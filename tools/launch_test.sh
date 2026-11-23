#!/bin/bash
# launch_test.sh: close SB, relaunch via Steam, report RUNS (DekCNS scan reached) / CRASH (new session died) / NOLAUNCH
L="$(python -c "import sys; sys.path.insert(0, r'$(dirname "$0")'); import cfg; print(cfg.SB_GAME)")/Binaries/Win64/ue4ss/UE4SS.log"
taskkill //IM SB-Win64-Shipping.exe //F >/dev/null 2>&1
for i in $(seq 1 20); do tasklist 2>/dev/null | grep -qi 'SB-Win64' || break; sleep 2; done
sleep 12
t0=$(date +%s); cmd //c start "" "steam://rungameid/3489700"
started=0
for i in $(seq 1 80); do
  sleep 3
  [ $(stat -c %Y $L) -ge $t0 ] && started=1
  if [ $started = 1 ] && grep -q 'PEFA] clock report' $L; then echo "RUNS after $((i*3))s"; exit 0; fi
  if [ $i -gt 20 ] && ! tasklist 2>/dev/null | grep -qi 'SB-Win64'; then
    [ $started = 1 ] && { echo "CRASH after $((i*3))s (log ends: $(tail -1 $L | cut -c30-90))"; exit 1; } || { echo "NOLAUNCH"; exit 2; }
  fi
done
echo "TIMEOUT"
