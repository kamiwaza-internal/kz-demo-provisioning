#!/bin/bash

echo "=== Container Count ==="
sudo docker ps | wc -l

echo ""
echo "=== All Containers ==="
sudo docker ps --format 'table {{.Names}}\t{{.Status}}' | head -20

echo ""
echo "=== Checking for Backend and Keycloak ==="
sudo docker ps | grep kamiwaza-backend && echo BACKEND_FOUND || echo backend_not_found
sudo docker ps | grep keycloak && echo KEYCLOAK_FOUND || echo keycloak_not_found

echo ""
echo "=== Recent daemon logs ==="
tail -30 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log
