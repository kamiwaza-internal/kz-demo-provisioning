#!/bin/bash
#
# Kamiwaza Official Installation Script for EC2
# This script follows the official Kamiwaza .deb installation instructions
#
# Usage: Run as root on EC2 instance startup (via user data)
# OS: Ubuntu 22.04 or 24.04 LTS ONLY
# Reference: https://docs.kamiwaza.ai/installation/linux_macos_tarball
#

set -euo pipefail

# Ensure non-interactive mode for all apt/dpkg operations
export DEBIAN_FRONTEND=noninteractive

# Logging functions
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/kamiwaza-deployment.log
}

error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a /var/log/kamiwaza-deployment.log >&2
}

# Configuration - can be overridden via environment variables
KAMIWAZA_PACKAGE_URL="${KAMIWAZA_PACKAGE_URL:-https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/kamiwaza_v0.9.2_noble_x86_64_build3.deb}"
KAMIWAZA_USER="${KAMIWAZA_USER:-ubuntu}"
KAMIWAZA_DEPLOYMENT_MODE="${KAMIWAZA_DEPLOYMENT_MODE:-full}"

# Start deployment
log "=========================================="
log "Kamiwaza Official Installation Starting"
log "=========================================="
log "Package URL: $KAMIWAZA_PACKAGE_URL"
log "User: $KAMIWAZA_USER"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VER=$VERSION_ID
    log "Detected OS: $OS $VER"
else
    error "Cannot detect OS"
    exit 1
fi

# Validate Ubuntu
if [ "$OS" != "ubuntu" ]; then
    error "This script only supports Ubuntu 22.04 or 24.04 LTS"
    error "Detected OS: $OS $VER"
    error "For other operating systems, please use the tarball installation method"
    exit 1
fi

if [ "$VER" != "22.04" ] && [ "$VER" != "24.04" ]; then
    error "This script only supports Ubuntu 22.04 or 24.04 LTS"
    error "Detected version: $VER"
    exit 1
fi

log "✓ OS validation passed: Ubuntu $VER"

# Detect architecture
ARCH=$(uname -m)
log "Architecture: $ARCH"

# Step 1: Update system packages (per official instructions)
log "Step 1: Running 'sudo apt update'..."
apt-get update -y
log "✓ System packages updated"

# Step 2: Download Kamiwaza .deb package (per official instructions)
log "Step 2: Downloading Kamiwaza package..."
PACKAGE_FILENAME=$(basename "$KAMIWAZA_PACKAGE_URL")
wget "$KAMIWAZA_PACKAGE_URL" -P /tmp

if [ $? -ne 0 ]; then
    error "Failed to download Kamiwaza package from $KAMIWAZA_PACKAGE_URL"
    exit 1
fi
log "✓ Package downloaded to /tmp/$PACKAGE_FILENAME"

# Step 3: Install Kamiwaza package (per official instructions)
log "Step 3: Installing Kamiwaza with 'sudo apt install -f -y /tmp/$PACKAGE_FILENAME'..."

# CRITICAL: Set KAMIWAZA_LITE environment variable BEFORE installation
# The .deb package's postinst script reads this variable to configure the mode
if [ "$KAMIWAZA_DEPLOYMENT_MODE" = "lite" ]; then
    log "Setting KAMIWAZA_LITE=true for lite mode installation..."
    export KAMIWAZA_LITE=true
    export DEBIAN_FRONTEND=noninteractive
    echo "kamiwaza kamiwaza/mode string lite" | debconf-set-selections
else
    log "Setting KAMIWAZA_LITE=false for full mode installation..."
    export KAMIWAZA_LITE=false
    export DEBIAN_FRONTEND=noninteractive
    echo "kamiwaza kamiwaza/mode string full" | debconf-set-selections
fi

apt install -f -y "/tmp/$PACKAGE_FILENAME"

if [ $? -ne 0 ]; then
    error "Failed to install Kamiwaza package"
    exit 1
fi
log "✓ Kamiwaza package installed successfully"

# Clean up temp file
rm -f "/tmp/$PACKAGE_FILENAME"
log "✓ Cleaned up temporary package file"

# Step 4: Start Kamiwaza (per official instructions)
log "Step 4: Starting Kamiwaza with 'kamiwaza start'..."

# Check if kamiwaza command exists
if ! command -v kamiwaza &> /dev/null; then
    error "kamiwaza command not found after installation"
    error "The .deb package may not have installed correctly"
    exit 1
fi

log "✓ kamiwaza command found"

# Run kamiwaza start with the specified deployment mode
# Note: KAMIWAZA_MODE is the correct environment variable per Kamiwaza support
if [ "$KAMIWAZA_DEPLOYMENT_MODE" = "lite" ]; then
    log "Running 'kamiwaza start' in LITE mode as user $KAMIWAZA_USER..."
    export KAMIWAZA_MODE="lite"
else
    log "Running 'kamiwaza start' in FULL mode as user $KAMIWAZA_USER..."
    export KAMIWAZA_MODE="full"
fi

# Set environment variables for deployment mode
# KAMIWAZA_MODE="full" enables full stack deployment with Keycloak authentication
# KAMIWAZA_MODE="lite" enables lightweight deployment without authentication
# Using sudo -E to preserve environment variables
log "Deployment mode: $KAMIWAZA_DEPLOYMENT_MODE (KAMIWAZA_MODE=$KAMIWAZA_MODE)"
sudo -E -u $KAMIWAZA_USER bash -c "KAMIWAZA_MODE=$KAMIWAZA_MODE kamiwaza start" 2>&1 | tee -a /var/log/kamiwaza-startup.log &
KAMIWAZA_PID=$!

log "✓ Kamiwaza start command initiated (PID: $KAMIWAZA_PID)"

# Wait for services to initialize with proper health checking
log "Waiting for Kamiwaza services to initialize..."
log "This may take several minutes as Docker images are pulled and containers start..."

# Function to check service health
check_kamiwaza_status() {
    sudo -u $KAMIWAZA_USER bash -c "kamiwaza status" 2>/dev/null
}

# Function to count running services
count_running_services() {
    check_kamiwaza_status | grep -c "RUNNING" || echo "0"
}

# Function to check for error state
check_for_errors() {
    check_kamiwaza_status | grep -q "ERROR"
}

# Wait up to 5 minutes for initial startup
MAX_WAIT=300
ELAPSED=0
SLEEP_INTERVAL=15

while [ $ELAPSED -lt $MAX_WAIT ]; do
    sleep $SLEEP_INTERVAL
    ELAPSED=$((ELAPSED + SLEEP_INTERVAL))

    RUNNING_COUNT=$(count_running_services)
    log "Status check ($ELAPSED/${MAX_WAIT}s): $RUNNING_COUNT/5 services running"

    # Check if all 5 services are running
    if [ "$RUNNING_COUNT" -eq 5 ]; then
        log "✓ All 5 services are running!"
        break
    fi

    # Check for error state after first minute
    if [ $ELAPSED -ge 60 ] && check_for_errors; then
        log "⚠ Detected services in ERROR state, attempting restart..."
        sudo -E -u $KAMIWAZA_USER bash -c "KAMIWAZA_MODE=$KAMIWAZA_MODE kamiwaza restart" 2>&1 | tee -a /var/log/kamiwaza-startup.log
        sleep 30
    fi
done

# Final status check
FINAL_RUNNING=$(count_running_services)
log "Final service count: $FINAL_RUNNING/5 services running"

if [ "$FINAL_RUNNING" -lt 5 ]; then
    log "⚠ Warning: Not all services started successfully"
    log "Current status:"
    check_kamiwaza_status | tee -a /var/log/kamiwaza-deployment.log
    log ""
    log "Attempting one final restart to recover..."
    sudo -E -u $KAMIWAZA_USER bash -c "KAMIWAZA_MODE=$KAMIWAZA_MODE kamiwaza restart" 2>&1 | tee -a /var/log/kamiwaza-startup.log
    sleep 60

    FINAL_RUNNING=$(count_running_services)
    log "After restart: $FINAL_RUNNING/5 services running"
fi

# Step 5: Verify deployment
log "Step 5: Verifying deployment..."

# Get instance public IP
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || echo "unknown")
PRIVATE_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4 || echo "unknown")

# Check if Docker containers are running (Kamiwaza uses Docker internally)
if docker ps &> /dev/null; then
    CONTAINER_COUNT=$(docker ps | grep -c kamiwaza || true)
    log "✓ Docker accessible, found $CONTAINER_COUNT Kamiwaza containers"
fi

# Display completion information
log "=========================================="
log "Kamiwaza Installation Completed!"
log "=========================================="
log ""
log "Deployment Mode: $KAMIWAZA_DEPLOYMENT_MODE (KAMIWAZA_MODE=$KAMIWAZA_MODE)"
log ""
log "Service Status: $FINAL_RUNNING/5 services running"
log ""
log "Instance Information:"
log "  Public IP: $PUBLIC_IP"
log "  Private IP: $PRIVATE_IP"
log ""
log "Kamiwaza URLs:"
log "  HTTPS: https://$PUBLIC_IP (recommended)"
log "  Note: Only HTTPS (port 443) is available, HTTP (port 80) is not configured"
log ""
log "Default Credentials:"
log "  Username: admin"
log "  Password: kamiwaza"
log ""
if [ "$FINAL_RUNNING" -eq 5 ]; then
    log "✓ All services are running and ready to use!"
else
    log "⚠ Warning: Not all services started successfully"
    log "   You may need to manually run: kamiwaza restart"
    log "   Check status with: kamiwaza status"
    log "   Monitor logs: sudo tail -f /var/log/kamiwaza-startup.log"
fi
log ""
log "Management Commands:"
log "  Start:   kamiwaza start"
log "  Stop:    sudo systemctl stop kamiwaza (or kamiwaza stop if available)"
log "  Status:  docker ps | grep kamiwaza"
log ""
log "To remove Kamiwaza:"
log "  sudo apt remove --purge kamiwaza"
log ""
log "=========================================="

# Create a README file for the user
cat > /home/$KAMIWAZA_USER/README_KAMIWAZA.md <<EOF
# Kamiwaza Platform - Deployment Information

## Access Information

- **Kamiwaza URL**: https://$PUBLIC_IP (HTTPS only)
- **Username**: admin
- **Password**: kamiwaza

⚠️ **Important**:
- Only HTTPS (port 443) is available
- You will see a browser security warning about a self-signed certificate - this is normal
- Click "Advanced" and "Proceed" to access the UI

## Service Management

### Start Kamiwaza
\`\`\`bash
kamiwaza start
\`\`\`

### Stop Kamiwaza
\`\`\`bash
# Method will depend on how kamiwaza was started
# Check for available commands:
kamiwaza --help

# Or stop via systemctl if a service was created:
sudo systemctl stop kamiwaza
\`\`\`

### Check Status
\`\`\`bash
# Check Kamiwaza service status
kamiwaza status

# Check running containers
docker ps | grep kamiwaza

# Check logs
sudo tail -f /var/log/kamiwaza-startup.log

# Run diagnostics
kamiwaza doctor
\`\`\`

## Removal

### Complete Uninstall
\`\`\`bash
sudo apt remove --purge kamiwaza
\`\`\`

## Troubleshooting

### Check Docker Containers
\`\`\`bash
docker ps -a | grep kamiwaza
\`\`\`

### View Startup Logs
\`\`\`bash
sudo tail -f /var/log/kamiwaza-startup.log
\`\`\`

### Restart Kamiwaza
\`\`\`bash
# Stop any running instances first, then:
kamiwaza start
\`\`\`

## Installation Details

This deployment used the official Kamiwaza .deb package installation method:

1. \`sudo apt update\`
2. \`wget $KAMIWAZA_PACKAGE_URL -P /tmp\`
3. \`sudo apt install -f -y /tmp/$(basename $KAMIWAZA_PACKAGE_URL)\`
4. \`kamiwaza start\`

## Support

For issues and questions:
- Documentation: https://docs.kamiwaza.ai
- Email: support@kamiwaza.ai

EOF

chown $KAMIWAZA_USER:$KAMIWAZA_USER /home/$KAMIWAZA_USER/README_KAMIWAZA.md

log "✓ README created at /home/$KAMIWAZA_USER/README_KAMIWAZA.md"
log ""
log "Deployment script completed successfully!"
log "Monitor Kamiwaza startup: sudo tail -f /var/log/kamiwaza-startup.log"

exit 0
