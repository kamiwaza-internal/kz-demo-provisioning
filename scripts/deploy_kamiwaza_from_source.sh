#!/bin/bash
#
# Deploy Kamiwaza from source (replaces .deb package installation)
# This script downloads Kamiwaza source, builds, and installs it
#
set -euo pipefail

# Default values
KAMIWAZA_SOURCE_URL="${KAMIWAZA_SOURCE_URL:-https://kamiwaza-provisioning-source.s3.us-west-2.amazonaws.com/kamiwaza-main.zip}"
KAMIWAZA_DEPLOYMENT_MODE="${KAMIWAZA_DEPLOYMENT_MODE:-full}"
KAMIWAZA_USER="${KAMIWAZA_USER:-kamiwaza}"
KAMIWAZA_INSTALL_DIR="/opt/kamiwaza"
WORK_DIR="/tmp/kamiwaza-install"

# Color output functions
log_info() {
    echo -e "\033[94m[INFO]\033[0m $1"
}

log_success() {
    echo -e "\033[92m[SUCCESS]\033[0m $1"
}

log_error() {
    echo -e "\033[91m[ERROR]\033[0m $1"
}

log_warn() {
    echo -e "\033[93m[WARN]\033[0m $1"
}

# Error handler
error_exit() {
    log_error "$1"
    exit 1
}

log_info "=========================================="
log_info "Kamiwaza Source Installation"
log_info "=========================================="
log_info "Deployment Mode: $KAMIWAZA_DEPLOYMENT_MODE"
log_info "Source URL: $KAMIWAZA_SOURCE_URL"
log_info ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    error_exit "This script must be run as root (use sudo)"
fi

# ========================================
# System Requirements Validation
# ========================================
log_info "Validating system requirements..."

# Check OS and version
if [ -f /etc/os-release ]; then
    . /etc/os-release
    log_info "Detected OS: $ID $VERSION_ID"

    # This script is for RHEL 9 family only
    if [ "$ID" = "rhel" ] || [ "$ID" = "centos" ] || [ "$ID" = "rocky" ] || [ "$ID" = "almalinux" ]; then
        if [ "${VERSION_ID%%.*}" != "9" ]; then
            log_warn "This script is configured for RHEL 9 family"
            log_warn "Detected version: $VERSION_ID - installation may not work correctly"
        fi
        log_success "OS validation passed: $ID $VERSION_ID"
    else
        error_exit "Unsupported OS: $ID $VERSION_ID. This script requires RHEL 9 or compatible distribution."
    fi
else
    error_exit "Cannot detect OS version"
fi

# Check available RAM (minimum 16GB, recommended 32GB)
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_GB=$((TOTAL_RAM_KB / 1024 / 1024))
log_info "Total RAM: ${TOTAL_RAM_GB}GB"

if [ $TOTAL_RAM_GB -lt 16 ]; then
    error_exit "Insufficient RAM: ${TOTAL_RAM_GB}GB detected. Kamiwaza requires minimum 16GB RAM."
elif [ $TOTAL_RAM_GB -lt 32 ]; then
    log_warn "RAM: ${TOTAL_RAM_GB}GB detected. Kamiwaza recommends 32GB for optimal performance."
else
    log_success "RAM check passed: ${TOTAL_RAM_GB}GB"
fi

# Check available disk space (minimum 10GB free)
AVAILABLE_SPACE_KB=$(df / | tail -1 | awk '{print $4}')
AVAILABLE_SPACE_GB=$((AVAILABLE_SPACE_KB / 1024 / 1024))
log_info "Available disk space: ${AVAILABLE_SPACE_GB}GB"

if [ $AVAILABLE_SPACE_GB -lt 10 ]; then
    error_exit "Insufficient disk space: ${AVAILABLE_SPACE_GB}GB available. Kamiwaza requires minimum 10GB free space."
elif [ $AVAILABLE_SPACE_GB -lt 50 ]; then
    log_warn "Disk space: ${AVAILABLE_SPACE_GB}GB available. Consider having 50GB+ for better performance."
else
    log_success "Disk space check passed: ${AVAILABLE_SPACE_GB}GB available"
fi

# Check CPU architecture
ARCH=$(uname -m)
log_info "CPU Architecture: $ARCH"
if [ "$ARCH" != "x86_64" ]; then
    log_warn "Kamiwaza is primarily tested on x86_64 architecture. Detected: $ARCH"
fi

log_success "System requirements validation complete"
log_info ""

# Install required system dependencies
log_info "Installing system dependencies..."
log_info "Using dnf package manager for RHEL..."
dnf update -y -q

# Enable EPEL and CodeReady Builder for additional packages
dnf install -y -q epel-release
dnf config-manager --set-enabled crb || dnf config-manager --set-enabled powertools

# Core dependencies
log_info "Installing core build tools and libraries..."
dnf groupinstall -y -q "Development Tools"
dnf install -y -q \
    curl \
    wget \
    unzip \
    git \
    ca-certificates \
    gnupg \
    jq \
    rsync \
    > /dev/null 2>&1 || error_exit "Failed to install core dependencies"

# Python dependencies
log_info "Installing Python development libraries..."
dnf install -y -q \
    python3-devel \
    python3-pip \
    libpq-devel \
    openssl-devel \
    libffi-devel \
    > /dev/null 2>&1 || error_exit "Failed to install Python dependencies"

# Cairo and GObject libraries
log_info "Installing Cairo and GObject libraries..."
dnf install -y -q \
    cairo-devel \
    cairo-gobject-devel \
    gobject-introspection-devel \
    glib2-devel \
    pkgconfig \
    > /dev/null 2>&1 || error_exit "Failed to install Cairo/GObject libraries"

log_success "System dependencies installed"

# ========================================
# Docker Installation (required: version 20.10+)
# ========================================
if ! command -v docker &> /dev/null; then
    log_info "Installing Docker Engine (required: 20.10+)..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh > /dev/null 2>&1 || error_exit "Failed to install Docker"
    systemctl enable docker
    systemctl start docker
    log_success "Docker Engine installed"
else
    DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    log_info "Docker already installed (version: $DOCKER_VERSION)"

    # Verify Docker version is 20.10 or higher
    DOCKER_MAJOR=$(echo $DOCKER_VERSION | cut -d. -f1)
    DOCKER_MINOR=$(echo $DOCKER_VERSION | cut -d. -f2)

    if [ "$DOCKER_MAJOR" -lt 20 ] || ([ "$DOCKER_MAJOR" -eq 20 ] && [ "$DOCKER_MINOR" -lt 10 ]); then
        log_warn "Docker version $DOCKER_VERSION detected. Kamiwaza requires Docker 20.10+"
        log_warn "Consider upgrading Docker: curl -fsSL https://get.docker.com | sh"
    else
        log_success "Docker version check passed"
    fi
fi

# Verify Docker is running
if ! systemctl is-active --quiet docker; then
    log_info "Starting Docker service..."
    systemctl start docker || error_exit "Failed to start Docker"
fi

# Install Docker Compose v2 if not present (required)
if ! docker compose version &> /dev/null; then
    log_info "Installing Docker Compose v2..."
    DOCKER_COMPOSE_VERSION="v2.24.5"
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    # Verify installation
    if docker compose version &> /dev/null; then
        COMPOSE_VERSION=$(docker compose version --short)
        log_success "Docker Compose v2 installed (version: $COMPOSE_VERSION)"
    else
        error_exit "Docker Compose installation failed"
    fi
else
    COMPOSE_VERSION=$(docker compose version --short)
    log_info "Docker Compose already installed (version: $COMPOSE_VERSION)"
    log_success "Docker Compose check passed"
fi

# Create kamiwaza user if doesn't exist
if ! id "$KAMIWAZA_USER" &>/dev/null; then
    log_info "Creating kamiwaza user..."
    useradd -r -m -d "$KAMIWAZA_INSTALL_DIR" -s /bin/bash "$KAMIWAZA_USER"
    usermod -aG docker "$KAMIWAZA_USER"
    log_success "User $KAMIWAZA_USER created"
else
    log_info "User $KAMIWAZA_USER already exists"
    # Ensure user is in docker group
    usermod -aG docker "$KAMIWAZA_USER" || true
fi

# Create work directory and clean if exists
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Download Kamiwaza source
log_info "Downloading Kamiwaza source from $KAMIWAZA_SOURCE_URL..."
if ! wget -q --show-progress "$KAMIWAZA_SOURCE_URL" -O kamiwaza-source.zip; then
    error_exit "Failed to download Kamiwaza source from $KAMIWAZA_SOURCE_URL"
fi
log_success "Download complete"

# Extract source
log_info "Extracting source..."
unzip -q kamiwaza-source.zip || error_exit "Failed to extract source"
cd kamiwaza-main || error_exit "Source directory not found"
log_success "Source extracted"

# ========================================
# Python 3.10 Installation (required per Kamiwaza tarball docs)
# ========================================
if ! python3.10 --version &> /dev/null; then
    log_info "Installing Python 3.10 (required)..."
    dnf install -y -q python3.10 python3.10-devel python3.10-pip
    # Create alternatives for python3.10
    alternatives --install /usr/bin/python3.10 python3.10 /usr/bin/python3.10 1 || true
    log_success "Python 3.10 installed"
else
    PYTHON_VERSION=$(python3.10 --version | grep -oP '\d+\.\d+\.\d+')
    log_info "Python 3.10 already installed (version: $PYTHON_VERSION)"
    log_success "Python 3.10 check passed"
fi

# Verify Python 3.10 is functional
if ! python3.10 -c "import sys; sys.exit(0)" &> /dev/null; then
    error_exit "Python 3.10 installation verification failed"
fi

# ========================================
# Node.js 22 Installation (required per Kamiwaza docs)
# ========================================
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | grep -oP '\d+' | head -1)
    if [ "$NODE_VERSION" = "22" ]; then
        log_info "Node.js 22 already installed ($(node --version))"
        log_success "Node.js check passed"
    else
        log_warn "Node.js $NODE_VERSION detected. Kamiwaza requires Node.js 22"
        log_info "Installing Node.js 22..."
        curl -fsSL https://rpm.nodesource.com/setup_22.x | bash - > /dev/null 2>&1
        dnf install -y -q nodejs
        log_success "Node.js 22 installed ($(node --version))"
    fi
else
    log_info "Installing Node.js 22 (required)..."
    curl -fsSL https://rpm.nodesource.com/setup_22.x | bash - > /dev/null 2>&1
    dnf install -y -q nodejs
    log_success "Node.js 22 installed ($(node --version))"
fi

# Verify Node.js is functional
if ! node --version &> /dev/null; then
    error_exit "Node.js installation verification failed"
fi

# ========================================
# Additional Dependencies (per Kamiwaza docs)
# ========================================

# Install etcd v3.5+ (required)
if ! command -v etcd &> /dev/null; then
    log_info "Installing etcd v3.5+ (required)..."
    ETCD_VERSION="v3.5.12"
    wget -q "https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz"
    tar xzf "etcd-${ETCD_VERSION}-linux-amd64.tar.gz"
    mv "etcd-${ETCD_VERSION}-linux-amd64/etcd" /usr/local/bin/
    mv "etcd-${ETCD_VERSION}-linux-amd64/etcdctl" /usr/local/bin/
    rm -rf "etcd-${ETCD_VERSION}-linux-amd64"*
    log_success "etcd installed"
else
    ETCD_VERSION=$(etcd --version 2>/dev/null | head -1 | grep -oP '\d+\.\d+\.\d+' || echo "unknown")
    log_info "etcd already installed (version: $ETCD_VERSION)"
fi

# Install CockroachDB
if ! command -v cockroach &> /dev/null; then
    log_info "Installing CockroachDB..."
    wget -qO- https://binaries.cockroachdb.com/cockroach-v23.1.14.linux-amd64.tgz | tar xvz > /dev/null 2>&1
    cp -i cockroach-v23.1.14.linux-amd64/cockroach /usr/local/bin/
    rm -rf cockroach-v23.1.14.linux-amd64
    log_success "CockroachDB installed"
else
    log_info "CockroachDB already installed"
fi

# Install cfssl (Go CFSSL for certificate management - required per docs)
if ! command -v cfssl &> /dev/null; then
    log_info "Installing cfssl (certificate management)..."
    wget -q https://github.com/cloudflare/cfssl/releases/download/v1.6.4/cfssl_1.6.4_linux_amd64 -O /usr/local/bin/cfssl
    wget -q https://github.com/cloudflare/cfssl/releases/download/v1.6.4/cfssljson_1.6.4_linux_amd64 -O /usr/local/bin/cfssljson
    chmod +x /usr/local/bin/cfssl /usr/local/bin/cfssljson
    log_success "cfssl installed"
else
    log_info "cfssl already installed"
fi

# Install uv (Python package manager)
if ! command -v uv &> /dev/null; then
    log_info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="/root/.local/bin:$PATH"
    log_success "uv installed"
else
    log_info "uv already installed"
fi

# Ensure install directory exists and set ownership
mkdir -p "$KAMIWAZA_INSTALL_DIR"
chown -R "$KAMIWAZA_USER:$KAMIWAZA_USER" "$KAMIWAZA_INSTALL_DIR"

# Copy source to install directory
log_info "Copying source to $KAMIWAZA_INSTALL_DIR..."
rsync -a --exclude='.git' ./ "$KAMIWAZA_INSTALL_DIR/kamiwaza/"
chown -R "$KAMIWAZA_USER:$KAMIWAZA_USER" "$KAMIWAZA_INSTALL_DIR"
cd "$KAMIWAZA_INSTALL_DIR/kamiwaza"

# Set environment variables for installation
export KAMIWAZA_ROOT="$KAMIWAZA_INSTALL_DIR/kamiwaza"
export PATH="/root/.local/bin:$PATH"

# Prepare installation flags
INSTALL_FLAGS="--i-accept-the-kamiwaza-license --head"

if [ "$KAMIWAZA_DEPLOYMENT_MODE" = "lite" ]; then
    INSTALL_FLAGS="$INSTALL_FLAGS --lite"
    export KAMIWAZA_LITE=true
    export KAMIWAZA_MODE="lite"
    log_info "Installing in LITE mode (no Keycloak)"
else
    INSTALL_FLAGS="$INSTALL_FLAGS --full"
    export KAMIWAZA_LITE=false
    export KAMIWAZA_MODE="full"
    log_info "Installing in FULL mode (with Keycloak)"
fi

# Run installation as kamiwaza user
log_info "Running Kamiwaza installation..."
log_info "Command: sudo -u $KAMIWAZA_USER bash ./install.sh $INSTALL_FLAGS"

# Make install script executable
chmod +x install.sh

# Run installation
if ! sudo -u "$KAMIWAZA_USER" bash -c "export PATH=/root/.local/bin:\$PATH && cd $KAMIWAZA_INSTALL_DIR/kamiwaza && ./install.sh $INSTALL_FLAGS"; then
    error_exit "Kamiwaza installation failed"
fi

log_success "Kamiwaza installation complete"

# Create systemd service
log_info "Creating systemd service..."
cat > /etc/systemd/system/kamiwaza.service <<EOF
[Unit]
Description=Kamiwaza AI Platform
After=network.target docker.service
Requires=docker.service

[Service]
Type=forking
User=$KAMIWAZA_USER
Group=$KAMIWAZA_USER
WorkingDirectory=$KAMIWAZA_INSTALL_DIR/kamiwaza
Environment="KAMIWAZA_ROOT=$KAMIWAZA_INSTALL_DIR/kamiwaza"
Environment="KAMIWAZA_LITE=$KAMIWAZA_LITE"
Environment="KAMIWAZA_MODE=$KAMIWAZA_MODE"
Environment="PATH=/usr/local/bin:/usr/bin:/bin:/root/.local/bin"
ExecStart=$KAMIWAZA_INSTALL_DIR/kamiwaza/startup/kamiwazad.sh start
ExecStop=$KAMIWAZA_INSTALL_DIR/kamiwaza/startup/kamiwazad.sh stop
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kamiwaza.service
log_success "Systemd service created"

# Start Kamiwaza
log_info "Starting Kamiwaza..."
systemctl start kamiwaza.service

# Wait for Kamiwaza to be ready
log_info "Waiting for Kamiwaza to start..."
for i in {1..60}; do
    if systemctl is-active --quiet kamiwaza.service; then
        log_success "Kamiwaza service is running"
        break
    fi
    if [ $i -eq 60 ]; then
        error_exit "Kamiwaza failed to start within 60 seconds"
    fi
    sleep 1
done

# Show service status
log_info "Kamiwaza service status:"
systemctl status kamiwaza.service --no-pager || true

# Cleanup
cd /
rm -rf "$WORK_DIR"

log_success "=========================================="
log_success "Kamiwaza Installation Complete!"
log_success "=========================================="
log_info "Installation directory: $KAMIWAZA_INSTALL_DIR/kamiwaza"
log_info "Service: kamiwaza.service"
log_info "Logs: journalctl -u kamiwaza.service -f"
log_info ""

# Display installed prerequisites summary
log_info "Installed Prerequisites Summary:"
log_info "  • Docker Engine: $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1) (required: 20.10+)"
log_info "  • Docker Compose: $(docker compose version --short) (required: v2)"
log_info "  • Python: $(python3.10 --version | grep -oP '\d+\.\d+\.\d+') (required: 3.10)"
log_info "  • Node.js: $(node --version) (required: v22)"
log_info "  • etcd: $(etcd --version 2>/dev/null | head -1 | grep -oP '\d+\.\d+\.\d+' || echo 'installed') (required: 3.5+)"
log_info "  • RAM: ${TOTAL_RAM_GB}GB (required: 16GB min, 32GB recommended)"
log_info "  • Disk Space: ${AVAILABLE_SPACE_GB}GB available (required: 10GB min)"
log_info ""
log_info "Management Commands:"
log_info "  • Check status: systemctl status kamiwaza"
log_info "  • View logs: sudo journalctl -u kamiwaza -f"
log_info "  • Restart: systemctl restart kamiwaza"
log_info "  • Stop: systemctl stop kamiwaza"
