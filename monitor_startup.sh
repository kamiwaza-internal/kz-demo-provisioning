#!/bin/bash

echo "=== Docker Containers ==="
sudo docker ps
echo ""
echo "=== Checking for FULL mode containers ==="
sudo docker ps | grep kamiwaza-backend && echo "BACKEND_FOUND" || echo "backend_not_yet"
sudo docker ps | grep keycloak && echo "KEYCLOAK_FOUND" || echo "keycloak_not_yet"
sudo docker ps | grep cockroach && echo "COCKROACH_FOUND" || echo "cockroach_not_yet"
echo ""
echo "=== Daemon Status ==="
tail -30 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log
