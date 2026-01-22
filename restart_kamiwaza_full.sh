#!/bin/bash

echo "Stopping existing Kamiwaza process..."
sudo -u kamiwaza bash -c 'cd /opt/kamiwaza/kamiwaza && source .venv/bin/activate && kamiwaza stop'
sleep 5

echo "Killing any remaining processes..."
pkill -f kamiwazad || true
pkill -f kamiwaza || true
sleep 3

echo ""
echo "Checking env.sh..."
cat /opt/kamiwaza/kamiwaza/env.sh

echo ""
echo "Starting Kamiwaza in FULL mode..."
sudo -u kamiwaza bash -c 'cd /opt/kamiwaza/kamiwaza && source env.sh && source .venv/bin/activate && kamiwaza start' > /var/log/kamiwaza-fullmode.log 2>&1 &

echo "Waiting 15 seconds..."
sleep 15

echo ""
echo "Startup logs:"
tail -40 /var/log/kamiwaza-fullmode.log
