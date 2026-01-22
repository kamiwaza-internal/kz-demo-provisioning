#!/bin/bash
#
# Kamiwaza Official Installation Script for EC2 (RHEL 9)
# This script installs Kamiwaza using the official RPM package
#
# Usage: Run as root on EC2 instance startup (via user data)
# OS: Red Hat Enterprise Linux 9
#

set -euo pipefail

# Logging functions
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/kamiwaza-deployment.log
}

error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a /var/log/kamiwaza-deployment.log >&2
}

# Configuration - can be overridden via environment variables
KAMIWAZA_PACKAGE_URL="${KAMIWAZA_PACKAGE_URL:-https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/rpm/rhel9/x86_64/kamiwaza_v0.9.2_rhel9_x86_64-online_rc18.rpm}"
KAMIWAZA_USER="${KAMIWAZA_USER:-ec2-user}"
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

# Validate RHEL
if [ "$OS" != "rhel" ] && [ "$OS" != "centos" ] && [ "$OS" != "rocky" ]; then
    error "This script only supports Red Hat Enterprise Linux 9 and compatible distributions"
    error "Detected OS: $OS $VER"
    exit 1
fi

if [ "${VER%%.*}" != "9" ]; then
    error "This script only supports RHEL 9 family"
    error "Detected version: $VER"
    exit 1
fi

log "✓ OS validation passed: $OS $VER"

# Detect architecture
ARCH=$(uname -m)
log "Architecture: $ARCH"

# Step 1: Install prerequisites (per official RHEL guide)
log "Step 1: Installing prerequisite packages..."
dnf install -y -q net-tools gcc-c++ nodejs npm jq pkgconfig \
fontconfig-devel freetype-devel libX11-devel libXrender-devel \
libXext-devel libpng-devel libSM-devel pixman-devel libxcb-devel \
glib2-devel python3-devel libffi-devel gtk3-devel ca-certificates \
curl libcurl-devel cmake gnupg2 iptables pciutils dos2unix unzip \
coreutils systemd wget make gcc openssl sqlite ncurses-libs readline \
libffi xz-libs expat tk zlib-devel bzip2-devel openssl-devel \
ncurses-devel sqlite-devel readline-devel tk-devel xz-devel \
expat-devel libuuid-devel yum-utils device-mapper-persistent-data \
lvm2 git python3.12 python3.12-pip python3.12-devel vim

if [ $? -ne 0 ]; then
    log "⚠ Warning: Some prerequisite packages may have failed to install"
    log "Continuing with installation..."
fi
log "✓ Prerequisites installed"

# Step 1b: Update system packages
log "Running system update..."
dnf update -y -q
log "✓ System packages updated"

# Step 1c: Install and configure Docker (RHEL 9 compatible)
log "Setting up Docker for RHEL 9..."

# Check if Docker is already installed
if ! command -v docker &> /dev/null; then
    log "Docker not found, installing from Docker's official repository..."

    # Remove conflicting packages if any
    dnf remove -y docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine podman buildah 2>/dev/null || true

    # Install prerequisites
    dnf install -y dnf-plugins-core

    # Add Docker's official repository
    dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo

    # Install Docker Engine
    log "Installing Docker CE (Container Engine)..."
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    if [ $? -ne 0 ]; then
        error "Failed to install Docker CE"
        exit 1
    fi

    log "✓ Docker CE installed successfully"
else
    log "✓ Docker already installed"
fi

# Enable and start Docker service
log "Enabling and starting Docker service..."
systemctl enable docker
systemctl start docker

# Wait for Docker to be ready
log "Waiting for Docker daemon to be ready..."
for i in {1..30}; do
    if docker info >/dev/null 2>&1; then
        log "✓ Docker daemon is ready"
        break
    fi
    sleep 2
done

# Verify Docker is working
if ! docker info >/dev/null 2>&1; then
    error "Docker daemon is not responding"
    exit 1
fi

# Set Docker socket permissions (required for Kamiwaza)
log "Setting Docker socket permissions..."
chmod 666 /var/run/docker.sock

# Add ec2-user to docker group (optional but useful)
usermod -aG docker $KAMIWAZA_USER 2>/dev/null || true

log "✓ Docker configured and running successfully"

# Step 2: Download Kamiwaza RPM package
log "Step 2: Downloading Kamiwaza RPM package..."
PACKAGE_FILENAME=$(basename "$KAMIWAZA_PACKAGE_URL")

# Use curl instead of wget for better RHEL 9 compatibility (curl is pre-installed)
if ! curl -L -o "/tmp/$PACKAGE_FILENAME" "$KAMIWAZA_PACKAGE_URL"; then
    error "Failed to download Kamiwaza package from $KAMIWAZA_PACKAGE_URL"
    exit 1
fi

# Verify the file was downloaded
if [ ! -f "/tmp/$PACKAGE_FILENAME" ]; then
    error "Package file not found at /tmp/$PACKAGE_FILENAME after download"
    exit 1
fi

log "✓ Package downloaded to /tmp/$PACKAGE_FILENAME"

# Step 3: Install Kamiwaza RPM package
log "Step 3: Installing Kamiwaza RPM package (per official RHEL guide)..."

# Set required environment variables BEFORE installation (per official guide)
export KAMIWAZA_ACCEPT_LICENSE=yes
export KAMIWAZA_LICENSE_KEY=""

# Set KAMIWAZA_LITE environment variable BEFORE installation
if [ "$KAMIWAZA_DEPLOYMENT_MODE" = "lite" ]; then
    log "Setting KAMIWAZA_LITE=true for lite mode installation..."
    export KAMIWAZA_LITE=true
else
    log "Setting KAMIWAZA_LITE=false for full mode installation..."
    export KAMIWAZA_LITE=false
fi

log "Installing with license acceptance..."
log "Command: sudo -E KAMIWAZA_ACCEPT_LICENSE=yes KAMIWAZA_LICENSE_KEY=\"\" dnf install -y /tmp/$PACKAGE_FILENAME"

# Install RPM with environment variables (per official guide)
sudo -E dnf install -y "/tmp/$PACKAGE_FILENAME"

if [ $? -ne 0 ]; then
    error "Failed to install Kamiwaza RPM package"
    exit 1
fi
log "✓ Kamiwaza RPM package installed successfully"

# Clean up temp file
rm -f "/tmp/$PACKAGE_FILENAME"
log "✓ Cleaned up temporary package file"

# Step 3b: Configure KAMIWAZA_ORIGIN (REQUIRED per official guide)
log "Step 3b: Configuring KAMIWAZA_ORIGIN (required)..."

# Try to detect public IP from EC2 metadata service
PUBLIC_IP=""
if curl -s -m 5 http://169.254.169.254/latest/meta-data/public-ipv4 &>/dev/null; then
    PUBLIC_IP=$(curl -s -m 5 http://169.254.169.254/latest/meta-data/public-ipv4)
    log "Detected EC2 public IP: $PUBLIC_IP"
fi

# If we couldn't get public IP, try to get private IP
if [ -z "$PUBLIC_IP" ]; then
    if curl -s -m 5 http://169.254.169.254/latest/meta-data/local-ipv4 &>/dev/null; then
        PUBLIC_IP=$(curl -s -m 5 http://169.254.169.254/latest/meta-data/local-ipv4)
        log "Using EC2 private IP: $PUBLIC_IP"
    fi
fi

# Fallback to hostname if no IP found
if [ -z "$PUBLIC_IP" ]; then
    PUBLIC_IP=$(hostname -I | awk '{print $1}')
    log "Using local IP: $PUBLIC_IP"
fi

KAMIWAZA_URL="https://${PUBLIC_IP}"
log "Setting KAMIWAZA_ORIGIN to: $KAMIWAZA_URL"

# Configure in /opt/kamiwaza/kamiwaza/env.sh
# Note: The official guide mentions /etc/kamiwaza/env.sh, but the RPM may create /opt/kamiwaza/kamiwaza/env.sh
ENV_FILE="/opt/kamiwaza/kamiwaza/env.sh"
if [ ! -f "$ENV_FILE" ]; then
    # Try alternative location
    ENV_FILE="/etc/kamiwaza/env.sh"
fi

if [ -f "$ENV_FILE" ]; then
    # Add or update KAMIWAZA_ORIGIN
    if grep -q "^export KAMIWAZA_ORIGIN=" "$ENV_FILE"; then
        sed -i "s|^export KAMIWAZA_ORIGIN=.*|export KAMIWAZA_ORIGIN=\"${KAMIWAZA_URL}\"|" "$ENV_FILE"
    else
        echo "export KAMIWAZA_ORIGIN=\"${KAMIWAZA_URL}\"" >> "$ENV_FILE"
    fi

    # Add KAMIWAZA_CORS_ORIGINS to match
    if grep -q "^export KAMIWAZA_CORS_ORIGINS=" "$ENV_FILE"; then
        sed -i "s|^export KAMIWAZA_CORS_ORIGINS=.*|export KAMIWAZA_CORS_ORIGINS=\"${KAMIWAZA_URL}\"|" "$ENV_FILE"
    else
        echo "export KAMIWAZA_CORS_ORIGINS=\"${KAMIWAZA_URL}\"" >> "$ENV_FILE"
    fi

    log "✓ KAMIWAZA_ORIGIN configured in $ENV_FILE"
else
    log "⚠ Warning: Could not find env.sh file to configure KAMIWAZA_ORIGIN"
fi

# Configure deployment mode
log "Configuring deployment mode..."

if [ "$KAMIWAZA_DEPLOYMENT_MODE" = "lite" ]; then
    log "Ensuring lite mode configuration..."
    # Make sure systemd service has KAMIWAZA_LITE=true
    if [ -f /etc/systemd/system/kamiwaza.service ]; then
        sed -i 's/Environment="KAMIWAZA_LITE=false"/Environment="KAMIWAZA_LITE=true"/' /etc/systemd/system/kamiwaza.service || true
    fi
    # Make sure env.sh has correct settings (check both possible locations)
    for env_file in /opt/kamiwaza/kamiwaza/env.sh /etc/kamiwaza/env.sh; do
        if [ -f "$env_file" ]; then
            sed -i 's/export KAMIWAZA_LITE=false/export KAMIWAZA_LITE=true/' "$env_file" || true
            sed -i 's/export KAMIWAZA_USE_AUTH=true/export KAMIWAZA_USE_AUTH=false/' "$env_file" || true
            log "  • Updated $env_file for lite mode"
        fi
    done
else
    log "Ensuring full mode configuration..."
    # Fix systemd service to use KAMIWAZA_LITE=false
    if [ -f /etc/systemd/system/kamiwaza.service ]; then
        sed -i 's/Environment="KAMIWAZA_LITE=true"/Environment="KAMIWAZA_LITE=false"/' /etc/systemd/system/kamiwaza.service || true
        log "  • Updated systemd service: KAMIWAZA_LITE=false"
    fi
    # Fix env.sh to enable authentication and disable lite mode (check both possible locations)
    for env_file in /opt/kamiwaza/kamiwaza/env.sh /etc/kamiwaza/env.sh; do
        if [ -f "$env_file" ]; then
            sed -i 's/export KAMIWAZA_LITE=true/export KAMIWAZA_LITE=false/' "$env_file" || true
            sed -i 's/export KAMIWAZA_USE_AUTH=false/export KAMIWAZA_USE_AUTH=true/' "$env_file" || true
            log "  • Updated $env_file: KAMIWAZA_LITE=false, KAMIWAZA_USE_AUTH=true"
        fi
    done
    # Reload systemd to pick up changes
    systemctl daemon-reload
fi

log "✓ Deployment mode configuration workaround applied"

# Step 4: Start Kamiwaza (per official instructions)
log "Step 4: Starting Kamiwaza with 'kamiwaza start'..."

# Check if kamiwaza command exists
if ! command -v kamiwaza &> /dev/null; then
    error "kamiwaza command not found after installation"
    error "The RPM package may not have installed correctly"
    error "Check installation logs: /var/log/kamiwaza-postinst-debug.log"
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

# Step 5.1: Fix Keycloak hostname configuration
# By default, Keycloak may be configured with 'localhost' which breaks OAuth login
# from external clients. We need to update it to use the public IP.
if [ "$PUBLIC_IP" != "unknown" ] && [ "$KAMIWAZA_DEPLOYMENT_MODE" = "full" ]; then
    log "Fixing Keycloak hostname configuration..."
    
    # Wait for Keycloak to be ready
    KEYCLOAK_READY=false
    for i in {1..30}; do
        if curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration >/dev/null 2>&1; then
            KEYCLOAK_READY=true
            break
        fi
        sleep 5
    done
    
    if [ "$KEYCLOAK_READY" = true ]; then
        # Check current issuer
        CURRENT_ISSUER=$(curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration 2>/dev/null | grep -o '"issuer":"[^"]*"' | head -1 || echo "")
        
        if echo "$CURRENT_ISSUER" | grep -q "localhost"; then
            log "Keycloak configured with localhost, updating to $PUBLIC_IP..."
            
            # Find docker-compose file
            COMPOSE_FILE=""
            for f in /opt/kamiwaza/docker-compose.yml /opt/kamiwaza/kamiwaza/docker-compose.yml; do
                if [ -f "$f" ]; then
                    COMPOSE_FILE="$f"
                    break
                fi
            done
            
            if [ -n "$COMPOSE_FILE" ]; then
                # Backup and update
                cp "$COMPOSE_FILE" "${COMPOSE_FILE}.backup"
                
                # Add or update KC_HOSTNAME environment variable
                if grep -q "KC_HOSTNAME" "$COMPOSE_FILE"; then
                    sed -i "s|KC_HOSTNAME=.*|KC_HOSTNAME=$PUBLIC_IP|g" "$COMPOSE_FILE"
                else
                    # Try to add it to the keycloak service section
                    sed -i "/keycloak:/,/environment:/{/environment:/a\\      - KC_HOSTNAME=$PUBLIC_IP\\n      - KC_HOSTNAME_STRICT=false}" "$COMPOSE_FILE" 2>/dev/null || true
                fi
                
                # Restart Keycloak
                KEYCLOAK_CONTAINER=$(docker ps --format '{{.Names}}' | grep -i keycloak | head -1 || echo "")
                if [ -n "$KEYCLOAK_CONTAINER" ]; then
                    log "Restarting Keycloak container to apply hostname fix..."
                    docker restart "$KEYCLOAK_CONTAINER" 2>/dev/null || true
                    sleep 30
                    
                    # Verify fix
                    NEW_ISSUER=$(curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration 2>/dev/null | grep -o '"issuer":"[^"]*"' | head -1 || echo "")
                    if echo "$NEW_ISSUER" | grep -q "$PUBLIC_IP"; then
                        log "✓ Keycloak hostname updated successfully to $PUBLIC_IP"
                    else
                        log "⚠ Keycloak hostname may still be localhost - login might require manual fix"
                    fi
                fi
            else
                log "⚠ Could not find docker-compose.yml to update Keycloak hostname"
            fi
        else
            log "✓ Keycloak already configured with correct hostname"
        fi
    else
        log "⚠ Keycloak not ready yet - skipping hostname fix"
    fi
fi

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
log "  sudo dnf remove kamiwaza"
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
sudo dnf remove kamiwaza
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

This deployment used the official Kamiwaza RPM package installation method:

1. \`sudo dnf update -y\`
2. \`curl -L -o /tmp/kamiwaza.rpm $KAMIWAZA_PACKAGE_URL\`
3. \`sudo dnf install -y /tmp/kamiwaza.rpm\`
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
