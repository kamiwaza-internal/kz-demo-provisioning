#!/bin/bash

echo "=== Running containers-up.sh manually to see error ==="
cd /opt/kamiwaza/kamiwaza
sudo -u kamiwaza bash -c 'source env.sh && source .venv/bin/activate && bash containers-up.sh --reset-etcd' 2>&1 | head -100
