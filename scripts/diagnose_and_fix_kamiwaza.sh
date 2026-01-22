#!/bin/bash
#
# Diagnose and fix Kamiwaza installation on remote instance
# Usage: ./diagnose_and_fix_kamiwaza.sh <hostname_or_ip>
#

set -euo pipefail

HOST="${1:-100.53.110.232}"

echo "=========================================="
echo "Kamiwaza Diagnostic and Repair Tool"
echo "=========================================="
echo "Target: $HOST"
echo ""

# Function to run command on remote host via SSH
remote_exec() {
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$HOST" "$@"
}

echo "[1/10] Checking SSH connectivity..."
if ! remote_exec "echo 'SSH OK'" &>/dev/null; then
    echo "❌ Cannot connect via SSH to $HOST"
    echo "Please ensure:"
    echo "  - SSH is accessible (check security groups)"
    echo "  - You have the correct SSH key configured"
    echo "  - Try: ssh $HOST"
    exit 1
fi
echo "✓ SSH connectivity OK"

echo ""
echo "[2/10] Checking OS and system info..."
remote_exec "uname -a && cat /etc/os-release | grep PRETTY_NAME"

echo ""
echo "[3/10] Checking if Kamiwaza is installed..."
if remote_exec "command -v kamiwaza" &>/dev/null; then
    echo "✓ Kamiwaza CLI found"
    KAMIWAZA_VERSION=$(remote_exec "kamiwaza --version 2>/dev/null || echo 'unknown'")
    echo "  Version: $KAMIWAZA_VERSION"
elif remote_exec "[ -d /opt/kamiwaza/kamiwaza ]" &>/dev/null; then
    echo "✓ Kamiwaza directory found at /opt/kamiwaza/kamiwaza"
else
    echo "❌ Kamiwaza not found"
    echo "Installation required. Run deployment script first."
    exit 1
fi

echo ""
echo "[4/10] Checking Docker status..."
if ! remote_exec "docker ps" &>/dev/null; then
    echo "❌ Docker not running or not accessible"
    echo "Attempting to start Docker..."
    remote_exec "sudo systemctl start docker"
    sleep 3
fi
echo "✓ Docker is running"

echo ""
echo "[5/10] Checking Docker containers..."
CONTAINER_COUNT=$(remote_exec "docker ps --format '{{.Names}}' | wc -l")
echo "Running containers: $CONTAINER_COUNT"
if [ "$CONTAINER_COUNT" -gt 0 ]; then
    echo "Container list:"
    remote_exec "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
else
    echo "⚠ No Docker containers running"
fi

echo ""
echo "[6/10] Checking for Kamiwaza processes..."
remote_exec "ps aux | grep -E 'kamiwaza|kamiwazad' | grep -v grep || echo 'No kamiwaza processes found'"

echo ""
echo "[7/10] Checking systemd service..."
if remote_exec "systemctl list-unit-files | grep kamiwaza" &>/dev/null; then
    echo "✓ Kamiwaza systemd service exists"
    echo "Service status:"
    remote_exec "systemctl status kamiwaza --no-pager -l" || echo "Service not active"
else
    echo "⚠ No kamiwaza systemd service found"
fi

echo ""
echo "[8/10] Checking logs..."
echo "Recent deployment log (last 20 lines):"
remote_exec "tail -20 /var/log/kamiwaza-deployment.log 2>/dev/null || echo 'No deployment log found'"
echo ""
echo "Recent startup log (last 20 lines):"
remote_exec "tail -20 /var/log/kamiwaza-startup.log 2>/dev/null || echo 'No startup log found'"

echo ""
echo "[9/10] Checking Kamiwaza directories and configuration..."
remote_exec "ls -la /opt/kamiwaza/ 2>/dev/null || echo 'Directory not found'"
if remote_exec "[ -f /opt/kamiwaza/kamiwaza/env.sh ]"; then
    echo "Environment configuration:"
    remote_exec "grep -E 'KAMIWAZA_LITE|KAMIWAZA_MODE|KAMIWAZA_USE_AUTH' /opt/kamiwaza/kamiwaza/env.sh 2>/dev/null || echo 'Config not found'"
fi

echo ""
echo "[10/10] Testing local connectivity..."
echo "Checking if nginx/traefik is listening on port 443:"
remote_exec "sudo ss -tlnp | grep :443 || echo 'Nothing listening on port 443'"
echo "Checking if any web server is running:"
remote_exec "sudo ss -tlnp | grep -E ':(80|443|8080)' || echo 'No web servers found'"

echo ""
echo "=========================================="
echo "Diagnosis complete!"
echo "=========================================="
echo ""
echo "RECOMMENDED ACTIONS:"
echo ""

# Determine what to do based on findings
if [ "$CONTAINER_COUNT" -eq 0 ]; then
    echo "1. No containers running - Kamiwaza needs to be started"
    echo "   Run: ssh $HOST 'sudo -u ubuntu bash -c \"export KAMIWAZA_MODE=full && kamiwaza start\"'"
    echo ""
elif [ "$CONTAINER_COUNT" -lt 5 ]; then
    echo "1. Only $CONTAINER_COUNT containers running (expected 5 for full mode)"
    echo "   Try restarting: ssh $HOST 'sudo -u ubuntu bash -c \"kamiwaza restart\"'"
    echo ""
fi

echo "2. Check if Keycloak is running (required for full mode):"
echo "   ssh $HOST 'docker ps | grep keycloak'"
echo ""
echo "3. Check logs for errors:"
echo "   ssh $HOST 'sudo journalctl -u kamiwaza -n 100 --no-pager'"
echo "   ssh $HOST 'tail -100 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log'"
echo ""
echo "4. Verify deployment mode configuration:"
echo "   ssh $HOST 'cat /opt/kamiwaza/kamiwaza/env.sh | grep -E \"KAMIWAZA\"'"
echo ""
echo "5. Manual start if needed:"
echo "   ssh $HOST"
echo "   sudo -i"
echo "   su - ubuntu"
echo "   export KAMIWAZA_MODE=full"
echo "   kamiwaza start"
echo ""
