# Manual Steps to Fix Kamiwaza on 100.53.110.232

Since SSH credentials aren't configured in this environment, here are the manual steps you need to run directly on the instance.

## Instance Information
- **IP Address**: 100.53.110.232
- **Instance ID**: i-0c2b296db180519f7
- **Expected User**: ubuntu
- **OS**: Ubuntu 24.04

## How to Connect

### Option 1: Direct SSH (if you have the key)
```bash
ssh ubuntu@100.53.110.232
# or if using a specific key:
ssh -i /path/to/your-key.pem ubuntu@100.53.110.232
```

### Option 2: AWS Systems Manager (SSM) Session Manager
```bash
aws ssm start-session --target i-0c2b296db180519f7 --region us-east-1
```

### Option 3: AWS Console
1. Go to EC2 Console
2. Find instance i-0c2b296db180519f7
3. Click "Connect" → "Session Manager" or "EC2 Instance Connect"

## Once Connected - Run These Commands

### Step 1: Quick Diagnosis
```bash
# Check current status
echo "=== Checking Docker ==="
systemctl status docker

echo -e "\n=== Checking Containers ==="
docker ps

echo -e "\n=== Checking Port 443 ==="
sudo ss -tlnp | grep :443

echo -e "\n=== Checking Kamiwaza Service ==="
systemctl status kamiwaza --no-pager || echo "No systemd service"

echo -e "\n=== Checking Kamiwaza Command ==="
which kamiwaza
kamiwaza --version 2>/dev/null || echo "Command not found"

echo -e "\n=== Checking Installation Directory ==="
ls -la /opt/kamiwaza/
```

### Step 2: Check Configuration
```bash
# Check deployment mode configuration
if [ -f /opt/kamiwaza/kamiwaza/env.sh ]; then
    echo "=== Current Configuration ==="
    cat /opt/kamiwaza/kamiwaza/env.sh | grep -E "KAMIWAZA_LITE|KAMIWAZA_MODE|KAMIWAZA_USE_AUTH"
else
    echo "env.sh not found"
fi
```

### Step 3: Check Logs
```bash
echo "=== Recent Deployment Log ==="
tail -50 /var/log/kamiwaza-deployment.log 2>/dev/null

echo -e "\n=== Recent Startup Log ==="
tail -50 /var/log/kamiwaza-startup.log 2>/dev/null

echo -e "\n=== Kamiwaza Daemon Log ==="
tail -50 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log 2>/dev/null

echo -e "\n=== Systemd Journal ==="
sudo journalctl -u kamiwaza -n 50 --no-pager 2>/dev/null
```

### Step 4: Fix and Restart (FULL MODE)

```bash
#!/bin/bash
# Run this entire block

echo "=== Stopping Existing Services ==="
# Try to stop gracefully
kamiwaza stop 2>/dev/null || true
sudo systemctl stop kamiwaza 2>/dev/null || true

# Stop all containers
docker ps -a --format '{{.Names}}' | grep -E 'kamiwaza|keycloak|traefik|backend|celery' | while read container; do
    echo "Stopping $container..."
    docker stop "$container" 2>/dev/null || true
done

sleep 5

echo -e "\n=== Configuring for FULL mode ==="
export KAMIWAZA_MODE="full"
export KAMIWAZA_LITE=false
export KAMIWAZA_USE_AUTH=true

# Update env.sh if exists
if [ -f /opt/kamiwaza/kamiwaza/env.sh ]; then
    echo "Updating env.sh..."
    sudo sed -i 's/export KAMIWAZA_LITE=.*/export KAMIWAZA_LITE=false/' /opt/kamiwaza/kamiwaza/env.sh
    sudo sed -i 's/export KAMIWAZA_MODE=.*/export KAMIWAZA_MODE="full"/' /opt/kamiwaza/kamiwaza/env.sh
    sudo sed -i 's/export KAMIWAZA_USE_AUTH=.*/export KAMIWAZA_USE_AUTH=true/' /opt/kamiwaza/kamiwaza/env.sh

    # Source it
    source /opt/kamiwaza/kamiwaza/env.sh
fi

# Update systemd service if exists
if [ -f /etc/systemd/system/kamiwaza.service ]; then
    echo "Updating systemd service..."
    sudo sed -i 's/Environment="KAMIWAZA_LITE=.*"/Environment="KAMIWAZA_LITE=false"/' /etc/systemd/system/kamiwaza.service
    sudo sed -i 's/Environment="KAMIWAZA_MODE=.*"/Environment="KAMIWAZA_MODE=full"/' /etc/systemd/system/kamiwaza.service
    sudo systemctl daemon-reload
fi

echo -e "\n=== Starting Kamiwaza ==="
echo "This will take 2-3 minutes..."

# Start Kamiwaza
KAMIWAZA_MODE=full kamiwaza start > /tmp/kamiwaza-restart.log 2>&1 &

# Wait for startup
echo "Waiting 120 seconds for services to start..."
sleep 120

echo -e "\n=== Checking Status ==="
echo "Docker containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo -e "\n=== Checking Port 443 ==="
sudo ss -tlnp | grep :443 || echo "Nothing listening on port 443 yet"

echo -e "\n=== Recent startup log ==="
tail -30 /tmp/kamiwaza-restart.log

echo -e "\n=== Daemon log ==="
tail -20 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log 2>/dev/null || echo "No daemon log yet"
```

### Step 5: Wait and Verify

After running Step 4, wait an additional 2-3 minutes, then check:

```bash
# Should see 5+ containers running
docker ps

# Should see something listening on port 443
sudo ss -tlnp | grep :443

# Test local connection
curl -k https://localhost/
# Should get HTML response, not connection refused

# Check for specific services
echo "Backend: $(docker ps | grep -c backend)"
echo "Keycloak: $(docker ps | grep -c keycloak)"
echo "Traefik: $(docker ps | grep -c traefik)"
```

### Step 6: Test from Outside

From your local machine:
```bash
# Should now work
curl -k https://100.53.110.232/

# Or open in browser:
# https://100.53.110.232/
# Accept the self-signed cert warning
# Login: admin / kamiwaza
```

## If It Still Doesn't Work

### Check for Errors
```bash
# Look for errors in logs
grep -i error /opt/kamiwaza/kamiwaza/logs/kamiwazad.log | tail -20

# Check Docker logs for each service
docker ps -a --format '{{.Names}}' | while read container; do
    echo "=== Logs for $container ==="
    docker logs "$container" 2>&1 | tail -20
    echo ""
done
```

### Try Lite Mode Instead
If full mode continues to fail, try lite mode (no authentication):

```bash
# Stop everything
kamiwaza stop
docker stop $(docker ps -aq)

# Configure for lite mode
export KAMIWAZA_MODE="lite"
export KAMIWAZA_LITE=true

# Update configs
sudo sed -i 's/export KAMIWAZA_LITE=.*/export KAMIWAZA_LITE=true/' /opt/kamiwaza/kamiwaza/env.sh
sudo sed -i 's/export KAMIWAZA_MODE=.*/export KAMIWAZA_MODE="lite"/' /opt/kamiwaza/kamiwaza/env.sh

# Start
KAMIWAZA_MODE=lite kamiwaza start
```

### Complete Reinstall
If nothing works, reinstall from scratch:

```bash
# Clean up
kamiwaza stop || true
sudo systemctl stop kamiwaza || true
docker stop $(docker ps -aq)
docker rm $(docker ps -aq)
sudo apt remove --purge kamiwaza -y
sudo rm -rf /opt/kamiwaza

# Download and run deployment script
cd /tmp
wget https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/kamiwaza_v0.9.2_noble_x86_64_build3.deb
sudo KAMIWAZA_DEPLOYMENT_MODE=full apt install -f -y ./kamiwaza_v0.9.2_noble_x86_64_build3.deb

# Start
sudo -u ubuntu bash -c "export KAMIWAZA_MODE=full && kamiwaza start"
```

## Expected Results

### Successful Full Mode
- **Containers**: backend, keycloak, traefik, celery-beat, celery-worker, flower
- **Port 443**: Traefik listening
- **Access**: https://100.53.110.232/ → Login page
- **Credentials**: admin / kamiwaza

### Successful Lite Mode
- **Containers**: backend, traefik, celery-beat, celery-worker
- **Port 443**: Traefik listening
- **Access**: https://100.53.110.232/ → Direct UI (no login)

## Need Help?

If you run these commands and share the output, I can provide more specific guidance.
