#!/bin/bash

echo "=== All Docker Containers ==="
sudo docker ps | head -25

echo ""
echo "=== Checking for backend ==="
sudo docker ps | grep backend && echo BACKEND_RUNNING || echo backend_not_found

echo ""
echo "=== Checking for keycloak ==="
sudo docker ps | grep keycloak && echo KEYCLOAK_RUNNING || echo keycloak_not_found

echo ""
echo "=== Daemon logs (last 30 lines) ==="
tail -30 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log
