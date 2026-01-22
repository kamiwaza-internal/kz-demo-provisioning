#!/bin/bash
#
# Fix and restart Kamiwaza on remote instance
# This script follows the official installation process
#

set -euo pipefail

HOST="${1:-100.53.110.232}"
MODE="${2:-full}"  # 'full' or 'lite'

echo "=========================================="
echo "Kamiwaza Repair Tool"
echo "=========================================="
echo "Target: $HOST"
echo "Mode: $MODE"
echo ""

# Create remote script to execute
REMOTE_SCRIPT=$(cat <<'EOF'
#!/bin/bash
set -euo pipefail

MODE="$1"

echo "[Step 1] Checking current state..."

# Stop any running Kamiwaza instances
echo "Stopping existing Kamiwaza services..."
if command -v kamiwaza &>/dev/null; then
    kamiwaza stop 2>/dev/null || true
fi

# Stop systemd service if exists
if systemctl list-unit-files | grep -q kamiwaza; then
    sudo systemctl stop kamiwaza 2>/dev/null || true
fi

# Stop all Kamiwaza Docker containers
echo "Stopping Docker containers..."
docker ps -a --format '{{.Names}}' | grep -E 'kamiwaza|keycloak|traefik|backend|celery' | while read container; do
    docker stop "$container" 2>/dev/null || true
done

sleep 5

echo "[Step 2] Checking Docker service..."
if ! systemctl is-active --quiet docker; then
    echo "Starting Docker..."
    sudo systemctl start docker
    sleep 3
fi

echo "[Step 3] Configuring deployment mode..."

# Set environment variables based on mode
if [ "$MODE" = "lite" ]; then
    export KAMIWAZA_LITE=true
    export KAMIWAZA_MODE="lite"
    export KAMIWAZA_USE_AUTH=false
    echo "Configuration: LITE mode (no authentication)"
else
    export KAMIWAZA_LITE=false
    export KAMIWAZA_MODE="full"
    export KAMIWAZA_USE_AUTH=true
    echo "Configuration: FULL mode (with Keycloak authentication)"
fi

# Update env.sh if it exists
if [ -f /opt/kamiwaza/kamiwaza/env.sh ]; then
    echo "Updating /opt/kamiwaza/kamiwaza/env.sh..."
    sudo sed -i "s/export KAMIWAZA_LITE=.*/export KAMIWAZA_LITE=$KAMIWAZA_LITE/" /opt/kamiwaza/kamiwaza/env.sh
    sudo sed -i "s/export KAMIWAZA_MODE=.*/export KAMIWAZA_MODE=\"$KAMIWAZA_MODE\"/" /opt/kamiwaza/kamiwaza/env.sh
    sudo sed -i "s/export KAMIWAZA_USE_AUTH=.*/export KAMIWAZA_USE_AUTH=$KAMIWAZA_USE_AUTH/" /opt/kamiwaza/kamiwaza/env.sh
fi

# Update systemd service if it exists
if [ -f /etc/systemd/system/kamiwaza.service ]; then
    echo "Updating systemd service..."
    sudo sed -i "s/Environment=\"KAMIWAZA_LITE=.*\"/Environment=\"KAMIWAZA_LITE=$KAMIWAZA_LITE\"/" /etc/systemd/system/kamiwaza.service
    sudo sed -i "s/Environment=\"KAMIWAZA_MODE=.*\"/Environment=\"KAMIWAZA_MODE=$KAMIWAZA_MODE\"/" /etc/systemd/system/kamiwaza.service
    sudo systemctl daemon-reload
fi

echo "[Step 4] Starting Kamiwaza..."

# Source env.sh if it exists
if [ -f /opt/kamiwaza/kamiwaza/env.sh ]; then
    source /opt/kamiwaza/kamiwaza/env.sh
fi

# Try starting via kamiwaza command
if command -v kamiwaza &>/dev/null; then
    echo "Starting with: KAMIWAZA_MODE=$KAMIWAZA_MODE kamiwaza start"
    KAMIWAZA_MODE="$KAMIWAZA_MODE" kamiwaza start > /var/log/kamiwaza-restart.log 2>&1 &

    echo "Waiting for startup (this may take 2-3 minutes)..."
    sleep 120

    echo "[Step 5] Checking status..."
    echo "Docker containers:"
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

    echo ""
    echo "Checking for expected services..."

    # Check for required containers
    BACKEND_COUNT=$(docker ps | grep -c backend || echo 0)
    KEYCLOAK_COUNT=$(docker ps | grep -c keycloak || echo 0)
    TRAEFIK_COUNT=$(docker ps | grep -c traefik || echo 0)

    echo "Backend containers: $BACKEND_COUNT (expected: 1+)"
    echo "Keycloak containers: $KEYCLOAK_COUNT (expected: 1 for full mode, 0 for lite)"
    echo "Traefik containers: $TRAEFIK_COUNT (expected: 1)"

    # Check listening ports
    echo ""
    echo "Listening on HTTPS (port 443):"
    sudo ss -tlnp | grep :443 || echo "Nothing listening on port 443"

    # If full mode, check Keycloak
    if [ "$MODE" = "full" ] && [ "$KEYCLOAK_COUNT" -gt 0 ]; then
        echo ""
        echo "Checking Keycloak health..."
        sleep 30  # Give Keycloak more time
        curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration > /dev/null 2>&1 && echo "✓ Keycloak responding" || echo "⚠ Keycloak not ready yet"
    fi

    echo ""
    echo "[Step 6] Recent logs:"
    tail -30 /var/log/kamiwaza-restart.log 2>/dev/null || echo "No restart log available"

    if [ -f /opt/kamiwaza/kamiwaza/logs/kamiwazad.log ]; then
        echo ""
        echo "Kamiwaza daemon log (last 20 lines):"
        tail -20 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log
    fi

    echo ""
    echo "=========================================="
    if [ "$TRAEFIK_COUNT" -gt 0 ] && [ "$BACKEND_COUNT" -gt 0 ]; then
        echo "✓ Kamiwaza appears to be starting successfully"
        echo "Wait another 2-3 minutes for full initialization"
        echo "Then access at: https://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')"
        echo "Default credentials: admin / kamiwaza"
    else
        echo "⚠ Some services may not have started correctly"
        echo "Check logs: tail -100 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log"
    fi
    echo "=========================================="

else
    echo "ERROR: kamiwaza command not found"
    echo "Kamiwaza may not be properly installed"
    exit 1
fi
EOF
)

# Execute on remote host
echo "Connecting to $HOST and executing repair script..."
echo "$REMOTE_SCRIPT" | ssh -o StrictHostKeyChecking=no "$HOST" "bash -s $MODE"

echo ""
echo "=========================================="
echo "Repair script completed!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Wait 2-3 minutes for full startup"
echo "2. Test connection: curl -k https://$HOST/"
echo "3. Check logs: ssh $HOST 'tail -100 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log'"
echo "4. View containers: ssh $HOST 'docker ps'"
echo ""
