# Kamiwaza Installation Troubleshooting Guide

## Quick Reference: Installation Process

Based on the [official Kamiwaza documentation](https://docs.kamiwaza.ai/installation/installation_process), here are the key installation steps and troubleshooting tips.

## Installation Methods

### Ubuntu (22.04/24.04) - via APT
```bash
# 1. Add repository (replace with actual repo URL)
echo "deb [signed-by=/usr/share/keyrings/kamiwaza-archive-keyring.gpg] ..." | sudo tee /etc/apt/sources.list.d/kamiwaza.list

# 2. Import GPG key
curl -fsSL <gpg-key-url> | sudo gpg --dearmor -o /usr/share/keyrings/kamiwaza-archive-keyring.gpg

# 3. Install
sudo apt update
sudo apt install kamiwaza
```

### Linux/macOS - via Tarball
```bash
# Prerequisites: Docker Engine with Compose v2, Python 3.10, Node.js 22
./install.sh --community
# Access: https://localhost
```

### Enterprise Deployment
```bash
# Option 1: Terraform (automated)
# - Uses cloud-init for first-boot.sh
# - Systemd manages services

# Option 2: Manual
./cluster-manual-prep.sh --head  # for head node
./cluster-manual-prep.sh --worker  # for worker nodes
```

## Current Issue: Instance at 100.53.110.232

### Problem
- Connection refused on port 443
- Kamiwaza web interface not accessible

### Likely Causes
1. **Kamiwaza not started** - Services may not have started after installation
2. **Docker containers not running** - Core services (backend, Keycloak, Traefik) not up
3. **Configuration mismatch** - Deployment mode (lite vs full) not properly set
4. **Systemd service issues** - Service may have failed or not enabled

## Diagnostic Steps

### 1. Check if SSH is accessible
```bash
ssh 100.53.110.232
```

### 2. Run diagnostic script
```bash
./scripts/diagnose_and_fix_kamiwaza.sh 100.53.110.232
```

### 3. Manual checks on the instance

#### Check Docker status
```bash
systemctl status docker
docker ps
```

Expected containers for **full mode**:
- `backend` (1 or more)
- `keycloak` (1)
- `traefik` (1)
- `celery-*` (workers)
- `flower` (optional)

Expected containers for **lite mode**:
- `backend` (1 or more)
- `traefik` (1)
- `celery-*` (workers)

#### Check if anything is listening on port 443
```bash
sudo ss -tlnp | grep :443
```

#### Check Kamiwaza logs
```bash
# Deployment log
tail -100 /var/log/kamiwaza-deployment.log

# Startup log
tail -100 /var/log/kamiwaza-startup.log

# Daemon log (if exists)
tail -100 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log

# Systemd journal
sudo journalctl -u kamiwaza -n 100 --no-pager
```

#### Check configuration
```bash
# Check env.sh
cat /opt/kamiwaza/kamiwaza/env.sh | grep -E "KAMIWAZA_LITE|KAMIWAZA_MODE|KAMIWAZA_USE_AUTH"

# Expected for full mode:
# export KAMIWAZA_LITE=false
# export KAMIWAZA_MODE="full"
# export KAMIWAZA_USE_AUTH=true

# Expected for lite mode:
# export KAMIWAZA_LITE=true
# export KAMIWAZA_MODE="lite"
# export KAMIWAZA_USE_AUTH=false
```

## Repair Actions

### Option 1: Use automated repair script
```bash
# For full mode (with Keycloak authentication)
./scripts/fix_kamiwaza_remote.sh 100.53.110.232 full

# For lite mode (no authentication)
./scripts/fix_kamiwaza_remote.sh 100.53.110.232 lite
```

### Option 2: Manual repair on instance

```bash
# SSH into the instance
ssh 100.53.110.232

# Stop any running Kamiwaza
kamiwaza stop  # or: sudo systemctl stop kamiwaza

# Stop Docker containers
docker ps -a | grep -E 'kamiwaza|keycloak|traefik' | awk '{print $1}' | xargs docker stop

# Configure for full mode
export KAMIWAZA_MODE="full"
export KAMIWAZA_LITE=false

# Update env.sh
sudo sed -i 's/export KAMIWAZA_LITE=true/export KAMIWAZA_LITE=false/' /opt/kamiwaza/kamiwaza/env.sh
sudo sed -i 's/export KAMIWAZA_MODE="lite"/export KAMIWAZA_MODE="full"/' /opt/kamiwaza/kamiwaza/env.sh
sudo sed -i 's/export KAMIWAZA_USE_AUTH=false/export KAMIWAZA_USE_AUTH=true/' /opt/kamiwaza/kamiwaza/env.sh

# Source configuration
source /opt/kamiwaza/kamiwaza/env.sh

# Start Kamiwaza
kamiwaza start

# Monitor startup (takes 2-3 minutes)
watch -n 10 'docker ps'

# Check logs
tail -f /opt/kamiwaza/kamiwaza/logs/kamiwazad.log
```

### Option 3: Complete reinstall (if repair fails)

```bash
# On the instance
ssh 100.53.110.232

# Stop and remove everything
kamiwaza stop || true
sudo systemctl stop kamiwaza || true
docker ps -a | awk '{print $1}' | xargs docker stop
docker ps -a | awk '{print $1}' | xargs docker rm

# If using .deb package
sudo apt remove --purge kamiwaza
sudo rm -rf /opt/kamiwaza

# Re-run installation
# Download our deployment script
wget https://path-to-your-script/deploy_kamiwaza_full.sh
chmod +x deploy_kamiwaza_full.sh

# Run installation
sudo KAMIWAZA_DEPLOYMENT_MODE=full ./deploy_kamiwaza_full.sh
```

## Common Issues and Solutions

### Issue: "Connection refused" on port 443
**Cause**: Traefik (reverse proxy) not running or not configured correctly
**Solution**:
```bash
docker ps | grep traefik
# If not running, restart Kamiwaza
kamiwaza restart
```

### Issue: "Backend not found" or 502 errors
**Cause**: Backend containers not running
**Solution**:
```bash
docker ps | grep backend
# Should see at least one backend container
# If not, check logs:
docker logs $(docker ps -a | grep backend | awk '{print $1}' | head -1)
```

### Issue: Keycloak login fails in full mode
**Cause**: Keycloak hostname misconfiguration (set to localhost instead of public IP)
**Solution**:
```bash
# Check current Keycloak issuer
curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration | grep issuer

# If it shows "localhost", need to fix KC_HOSTNAME in docker-compose.yml
# See lines 251-318 in deploy_kamiwaza_full.sh for automated fix
```

### Issue: Only partial services running
**Cause**: Resource constraints or failed container startup
**Solution**:
```bash
# Check which services failed
docker ps -a | grep -E 'Exited|Restarting'

# Check logs for failed containers
docker logs <container_id>

# Try restart
kamiwaza restart
```

## Verification

After repair, verify the installation:

```bash
# 1. Check all containers are running
docker ps
# Should see 5+ containers for full mode, 3+ for lite mode

# 2. Check port 443 is listening
sudo ss -tlnp | grep :443

# 3. Test local connectivity from instance
curl -k https://localhost/
# Should get HTML response, not connection refused

# 4. Test external connectivity
curl -k https://100.53.110.232/
# Should work if firewall allows

# 5. Access in browser
# https://100.53.110.232/
# Accept self-signed certificate warning
# Should see Kamiwaza login page (full mode) or direct UI (lite mode)
```

## Default Credentials (Full Mode)
- Username: `admin`
- Password: `kamiwaza`

## Useful Commands

```bash
# Start Kamiwaza
kamiwaza start

# Stop Kamiwaza
kamiwaza stop  # or: sudo systemctl stop kamiwaza

# Restart Kamiwaza
kamiwaza restart

# Check status
kamiwaza status  # if available
docker ps
systemctl status kamiwaza

# View logs
journalctl -u kamiwaza -f
tail -f /opt/kamiwaza/kamiwaza/logs/kamiwazad.log

# Run diagnostics (if available)
kamiwaza doctor
```

## Support Resources

- Official Documentation: https://docs.kamiwaza.ai
- Installation Guide: https://docs.kamiwaza.ai/installation/installation_process
- System Requirements: https://docs.kamiwaza.ai/installation/system_requirements
- Support: support@kamiwaza.ai
