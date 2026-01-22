#!/bin/bash

cd /opt/kamiwaza/kamiwaza

echo "=== Cleaning up stale processes ==="
pkill -f kamiwazad || true
rm -f /opt/kamiwaza/kamiwaza/kamiwazad.pid || true
sleep 3

echo ""
echo "=== Starting kamiwaza with proper environment ==="
sudo -u kamiwaza bash -c 'cd /opt/kamiwaza/kamiwaza && source env.sh && source .venv/bin/activate && export KAMIWAZA_MODE=full && export KAMIWAZA_LITE=false && kamiwaza start' > /var/log/kamiwaza-restart.log 2>&1 &

echo "Waiting 20 seconds..."
sleep 20

echo ""
tail -40 /var/log/kamiwaza-restart.log
