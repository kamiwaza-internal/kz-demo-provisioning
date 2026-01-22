#!/bin/bash

echo "=== Fixing permissions ==="_
cd /opt/kamiwaza/kamiwaza
sudo chown -R kamiwaza:kamiwaza .
ls -la | head -15

echo ""
echo "=== Stopping kamiwaza ==="
sudo -u kamiwaza bash -c 'cd /opt/kamiwaza/kamiwaza && source .venv/bin/activate && kamiwaza stop' || true
sleep 5
pkill -f kamiwazad || true
sleep 3

echo ""
echo "=== Restarting in FULL mode ==="
sudo -u kamiwaza bash -c 'cd /opt/kamiwaza/kamiwaza && source env.sh && source .venv/bin/activate && kamiwaza start' > /var/log/kamiwaza-fixed.log 2>&1 &

echo "Waiting 15 seconds..."
sleep 15

tail -30 /var/log/kamiwaza-fixed.log
