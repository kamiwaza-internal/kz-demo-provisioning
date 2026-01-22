#!/bin/bash

cd /opt/kamiwaza/kamiwaza

echo "=== Looking for docker compose files ==="
ls -la *.yml *.yaml 2>/dev/null

echo ""
echo "=== Checking for KAMIWAZA_LITE references in containers-up.sh ==="
grep KAMIWAZA_LITE containers-up.sh | head -10

echo ""
echo "=== Checking for KAMIWAZA_MODE references ==="
grep KAMIWAZA_MODE containers-up.sh | head -10

echo ""
echo "=== Checking current KAMIWAZA_MODE value ==="
echo "KAMIWAZA_MODE=$KAMIWAZA_MODE"
echo "KAMIWAZA_LITE=$KAMIWAZA_LITE"

echo ""
echo "=== Running kamiwaza status to see what should be running ==="
sudo -u kamiwaza bash -c 'cd /opt/kamiwaza/kamiwaza && source env.sh && source .venv/bin/activate && kamiwaza status' 2>&1 | head -50
