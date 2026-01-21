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
if [ "$KAMIWAZA_DEPLOYMENT_MODE" = "lite" ]; then
    log "Running 'kamiwaza start' in LITE mode as user $KAMIWAZA_USER..."
    export KAMIWAZA_LITE=true
    export KAMIWAZA_USE_AUTH=false
else
    log "Running 'kamiwaza start' in FULL mode as user $KAMIWAZA_USER..."
    export KAMIWAZA_LITE=false
    export KAMIWAZA_USE_AUTH=true
fi

# Set environment variables for deployment mode
# KAMIWAZA_LITE=true for lite mode, false for full stack
# KAMIWAZA_USE_AUTH=true enables Keycloak authentication (full mode only)
# Using -E flag to preserve environment variables through su
log "Deployment mode: $KAMIWAZA_DEPLOYMENT_MODE (KAMIWAZA_LITE=$KAMIWAZA_LITE, KAMIWAZA_USE_AUTH=$KAMIWAZA_USE_AUTH)"
su -E $KAMIWAZA_USER -c "kamiwaza start" 2>&1 | tee -a /var/log/kamiwaza-startup.log &
KAMIWAZA_PID=$!

log "✓ Kamiwaza start command initiated (PID: $KAMIWAZA_PID)"

# Wait a moment for services to initialize
log "Waiting for Kamiwaza to initialize..."
sleep 30

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
log "Deployment Mode: FULL (KAMIWAZA_LITE=false)"
log ""
log "Instance Information:"
log "  Public IP: $PUBLIC_IP"
log "  Private IP: $PRIVATE_IP"
log ""
log "Kamiwaza URLs:"
log "  HTTPS: https://$PUBLIC_IP"
log "  HTTP: http://$PUBLIC_IP (may redirect to HTTPS)"
log ""
log "Default Credentials:"
log "  Username: admin"
log "  Password: kamiwaza"
log ""
log "⏳ Note: Full mode may take 10-20 minutes to fully start"
log "   (includes all services: auth, vector DB, observability, etc.)"
log "   Monitor progress with: sudo tail -f /var/log/kamiwaza-startup.log"
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

- **Kamiwaza URL**: https://$PUBLIC_IP
- **Username**: admin
- **Password**: kamiwaza

⏳ **Note**: Kamiwaza may take 5-15 minutes after deployment to be fully accessible.

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
# Check running containers
docker ps | grep kamiwaza

# Check logs
sudo tail -f /var/log/kamiwaza-startup.log
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
