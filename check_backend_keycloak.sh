#!/bin/bash

echo "=== Checking if backend/keycloak images exist ==="
sudo docker images | grep backend
sudo docker images | grep keycloak

echo ""
echo "=== Checking for ANY backend or keycloak containers (running or stopped) ==="
sudo docker ps -a | grep backend
sudo docker ps -a | grep keycloak

echo ""
echo "=== Full docker ps -a (all containers) ==="
sudo docker ps -a --format 'table {{.Names}}\t{{.Status}}' | head -30

echo ""
echo "=== Check env.sh to confirm FULL mode ==="
cat /opt/kamiwaza/kamiwaza/env.sh
