#!/bin/bash

echo "Creating env.sh and starting Kamiwaza in FULL mode..."

cd /opt/kamiwaza/kamiwaza
sudo -u kamiwaza cp env.sh.example env.sh
sudo -u kamiwaza bash -c 'echo "export KAMIWAZA_MODE=full" >> env.sh'
sudo -u kamiwaza bash -c 'echo "export KAMIWAZA_LITE=false" >> env.sh'

echo "env.sh contents:"
cat env.sh

echo ""
echo "Starting Kamiwaza..."
sudo -u kamiwaza bash -c "cd /opt/kamiwaza/kamiwaza && source env.sh && source .venv/bin/activate && kamiwaza start" > /var/log/kamiwaza-full.log 2>&1 &

echo "Waiting 20 seconds..."
sleep 20

echo "Startup logs:"
tail -50 /var/log/kamiwaza-full.log
