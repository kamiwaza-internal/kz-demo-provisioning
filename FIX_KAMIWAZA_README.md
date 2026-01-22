# How to Fix Kamiwaza on 100.53.110.232

## Problem
The Kamiwaza instance at https://100.53.110.232/ is not responding (connection refused on port 443).

## Instance Details
- **IP**: 100.53.110.232 (Tailscale/private network IP)
- **Instance ID**: i-0c2b296db180519f7
- **Region**: us-east-1
- **OS**: Ubuntu 24.04
- **User**: ubuntu

## Root Cause
Based on the official [Kamiwaza installation documentation](https://docs.kamiwaza.ai/installation/installation_process), the issue is likely:
1. Kamiwaza services haven't started
2. Docker containers are not running
3. Traefik (reverse proxy) isn't listening on port 443

## Solutions (Pick One)

### ⭐ Option 1: Manual Fix (RECOMMENDED - No special tools needed)

1. **Connect to the instance**:
   ```bash
   ssh ubuntu@100.53.110.232
   ```

2. **Copy and paste this entire script**:
   ```bash
   #!/bin/bash
   # Quick Kamiwaza Fix Script

   echo "=== Stopping existing services ==="
   kamiwaza stop 2>/dev/null || true
   sudo systemctl stop kamiwaza 2>/dev/null || true
   docker stop $(docker ps -aq) 2>/dev/null || true
   sleep 5

   echo "=== Configuring for FULL mode ==="
   export KAMIWAZA_MODE="full"
   export KAMIWAZA_LITE=false

   # Update configuration files
   if [ -f /opt/kamiwaza/kamiwaza/env.sh ]; then
       sudo sed -i 's/export KAMIWAZA_LITE=.*/export KAMIWAZA_LITE=false/' /opt/kamiwaza/kamiwaza/env.sh
       sudo sed -i 's/export KAMIWAZA_MODE=.*/export KAMIWAZA_MODE="full"/' /opt/kamiwaza/kamiwaza/env.sh
       sudo sed -i 's/export KAMIWAZA_USE_AUTH=.*/export KAMIWAZA_USE_AUTH=true/' /opt/kamiwaza/kamiwaza/env.sh
       source /opt/kamiwaza/kamiwaza/env.sh
   fi

   echo "=== Starting Kamiwaza (this takes 2-3 minutes) ==="
   KAMIWAZA_MODE=full kamiwaza start > /tmp/kamiwaza-restart.log 2>&1 &

   echo "Waiting 120 seconds..."
   sleep 120

   echo "=== Status Check ==="
   docker ps
   sudo ss -tlnp | grep :443

   echo "=== Done! ==="
   echo "Check logs: tail -f /opt/kamiwaza/kamiwaza/logs/kamiwazad.log"
   echo "Wait another 2-3 minutes, then access: https://100.53.110.232/"
   ```

3. **Wait 2-3 more minutes**, then test:
   ```bash
   curl -k https://localhost/
   ```

4. **Access from your browser**: https://100.53.110.232/
   - Accept the self-signed certificate warning
   - Login: `admin` / `kamiwaza`

**See detailed step-by-step instructions**: [MANUAL_FIX_STEPS.md](MANUAL_FIX_STEPS.md)

---

### Option 2: Using AWS Systems Manager (SSM)

If AWS SSM is enabled on the instance and you have AWS credentials configured:

```bash
# Make sure AWS credentials are configured
aws configure

# Run the automated fix
python3 scripts/ssm_fix_kamiwaza.py
```

This script will:
- Connect via SSM (no SSH needed)
- Diagnose the current state
- Stop and reconfigure services
- Start Kamiwaza in full mode
- Verify the fix

---

### Option 3: Using SSH Scripts

If you can set up SSH access, you can use the automated scripts:

```bash
# First, configure SSH (if needed)
# Add your key or configure SSH config for this host

# Run diagnostic
./scripts/diagnose_and_fix_kamiwaza.sh 100.53.110.232

# Run repair
./scripts/fix_kamiwaza_remote.sh 100.53.110.232 full
```

---

### Option 4: AWS Console (EC2 Instance Connect)

1. Go to [AWS EC2 Console](https://console.aws.amazon.com/ec2)
2. Find instance `i-0c2b296db180519f7`
3. Click **Connect** → **Session Manager** or **EC2 Instance Connect**
4. Once connected, follow the manual fix steps from Option 1

---

## Verification Steps

After running any fix, verify it's working:

```bash
# On the instance
docker ps | grep -E "backend|keycloak|traefik"
# Should show 5+ containers running

sudo ss -tlnp | grep :443
# Should show traefik or nginx listening

curl -k https://localhost/
# Should return HTML, not connection error
```

From your local machine:
```bash
curl -k https://100.53.110.232/
# Should return HTML
```

Browser: https://100.53.110.232/ should show Kamiwaza login page

---

## Expected Services (Full Mode)

When working correctly, you should see these Docker containers:

1. **backend** (1-3 instances) - Main API server
2. **keycloak** - Authentication service
3. **traefik** - Reverse proxy (handles HTTPS on port 443)
4. **celery-beat** - Task scheduler
5. **celery-worker** - Background task worker
6. **flower** (optional) - Celery monitoring

---

## Common Issues

### Still getting "connection refused"?
- Check if Docker is running: `systemctl status docker`
- Check logs: `tail -100 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log`
- Try restarting: `kamiwaza restart`

### Containers keep restarting?
- Check individual logs: `docker logs <container-name>`
- Might be a resource issue - check: `free -h` and `df -h`

### Keycloak login fails?
- Check Keycloak is running: `docker ps | grep keycloak`
- Check hostname: `curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration`
- See [scripts/fix_keycloak_hostname.sh](scripts/fix_keycloak_hostname.sh)

### Want to try Lite mode instead? (No authentication)
Replace `KAMIWAZA_MODE=full` with `KAMIWAZA_MODE=lite` in the commands

---

## Files Created

- **MANUAL_FIX_STEPS.md** - Detailed manual repair steps
- **scripts/diagnose_and_fix_kamiwaza.sh** - SSH-based diagnostic tool
- **scripts/fix_kamiwaza_remote.sh** - SSH-based automated repair
- **scripts/ssm_fix_kamiwaza.py** - AWS SSM-based automated repair
- **docs/KAMIWAZA_TROUBLESHOOTING.md** - Complete troubleshooting guide

---

## Support

- **Kamiwaza Docs**: https://docs.kamiwaza.ai
- **Installation Guide**: https://docs.kamiwaza.ai/installation/installation_process
- **System Requirements**: https://docs.kamiwaza.ai/installation/system_requirements

---

## Quick Reference

```bash
# Start Kamiwaza
kamiwaza start

# Stop Kamiwaza
kamiwaza stop

# Check status
docker ps
systemctl status kamiwaza

# View logs
tail -f /opt/kamiwaza/kamiwaza/logs/kamiwazad.log
journalctl -u kamiwaza -f

# Test locally
curl -k https://localhost/

# Default credentials (full mode)
# Username: admin
# Password: kamiwaza
```
