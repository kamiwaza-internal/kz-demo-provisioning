#!/bin/bash
#
# Fix Keycloak Hostname Configuration for Kamiwaza
#
# This script fixes the common issue where Keycloak is configured with
# 'localhost' as the hostname instead of the actual server IP/domain.
#
# Usage: 
#   1. SSH into the EC2 instance
#   2. Run: sudo bash fix_keycloak_hostname.sh
#
# Or run remotely:
#   ssh -i your-key.pem ubuntu@3.218.164.211 'bash -s' < fix_keycloak_hostname.sh
#

set -euo pipefail

# Get the public IP from EC2 metadata
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")

if [ -z "$PUBLIC_IP" ]; then
    echo "ERROR: Could not detect public IP. Please provide it as argument:"
    echo "  sudo bash $0 YOUR_PUBLIC_IP"
    exit 1
fi

echo "=========================================="
echo "  Keycloak Hostname Fix Script"
echo "=========================================="
echo ""
echo "Detected Public IP: $PUBLIC_IP"
echo ""

# Find Keycloak container
KEYCLOAK_CONTAINER=$(docker ps --format '{{.Names}}' | grep -i keycloak | head -1 || echo "")

if [ -z "$KEYCLOAK_CONTAINER" ]; then
    echo "ERROR: Could not find Keycloak container"
    echo "Running containers:"
    docker ps --format 'table {{.Names}}\t{{.Status}}'
    exit 1
fi

echo "Found Keycloak container: $KEYCLOAK_CONTAINER"
echo ""

# Check current configuration
echo "Checking current Keycloak configuration..."
echo ""

# Get the current realm configuration
CURRENT_ISSUER=$(curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration 2>/dev/null | grep -o '"issuer":"[^"]*"' | head -1 || echo "Could not retrieve")
echo "Current issuer: $CURRENT_ISSUER"

if echo "$CURRENT_ISSUER" | grep -q "localhost"; then
    echo ""
    echo "⚠️  ISSUE DETECTED: Keycloak is configured with 'localhost'"
    echo "   This causes login failures when accessing from external clients."
    echo ""
fi

# Method 1: Update Keycloak environment variable (if using KC_HOSTNAME)
echo "Attempting to fix Keycloak hostname configuration..."
echo ""

# Check if we can update via docker-compose
COMPOSE_FILE=""
for f in /opt/kamiwaza/docker-compose.yml /opt/kamiwaza/kamiwaza/docker-compose.yml /home/ubuntu/kamiwaza/docker-compose.yml; do
    if [ -f "$f" ]; then
        COMPOSE_FILE="$f"
        break
    fi
done

if [ -n "$COMPOSE_FILE" ]; then
    echo "Found docker-compose file: $COMPOSE_FILE"
    
    # Backup the file
    cp "$COMPOSE_FILE" "${COMPOSE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Created backup: ${COMPOSE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Check if KC_HOSTNAME is already set
    if grep -q "KC_HOSTNAME" "$COMPOSE_FILE"; then
        echo "Updating KC_HOSTNAME in docker-compose.yml..."
        sed -i "s|KC_HOSTNAME=.*|KC_HOSTNAME=$PUBLIC_IP|g" "$COMPOSE_FILE"
        sed -i "s|KC_HOSTNAME_URL=.*|KC_HOSTNAME_URL=https://$PUBLIC_IP|g" "$COMPOSE_FILE"
    else
        echo "KC_HOSTNAME not found in docker-compose - may need manual configuration"
    fi
fi

# Method 2: Check for Keycloak standalone config
KEYCLOAK_CONFIG=""
for f in /opt/kamiwaza/keycloak/conf/keycloak.conf /opt/keycloak/conf/keycloak.conf; do
    if [ -f "$f" ]; then
        KEYCLOAK_CONFIG="$f"
        break
    fi
done

if [ -n "$KEYCLOAK_CONFIG" ]; then
    echo "Found Keycloak config: $KEYCLOAK_CONFIG"
    cp "$KEYCLOAK_CONFIG" "${KEYCLOAK_CONFIG}.backup.$(date +%Y%m%d_%H%M%S)"
    
    if grep -q "hostname=" "$KEYCLOAK_CONFIG"; then
        sed -i "s|hostname=.*|hostname=$PUBLIC_IP|g" "$KEYCLOAK_CONFIG"
        echo "Updated hostname in keycloak.conf"
    else
        echo "hostname=$PUBLIC_IP" >> "$KEYCLOAK_CONFIG"
        echo "Added hostname to keycloak.conf"
    fi
fi

# Method 3: Update via Keycloak Admin API
echo ""
echo "Attempting to update realm configuration via Admin API..."

# First, get admin token
ADMIN_TOKEN=$(curl -sk -X POST "https://localhost/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=admin" \
    -d "password=admin" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" 2>/dev/null | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4 || echo "")

if [ -n "$ADMIN_TOKEN" ]; then
    echo "Got admin token, updating realm..."
    
    # Get current realm config
    REALM_CONFIG=$(curl -sk -X GET "https://localhost/admin/realms/kamiwaza" \
        -H "Authorization: Bearer $ADMIN_TOKEN" 2>/dev/null || echo "")
    
    if [ -n "$REALM_CONFIG" ]; then
        # Update the frontendUrl
        echo "$REALM_CONFIG" | python3 -c "
import json, sys
config = json.load(sys.stdin)
# Frontend URL should be the external URL
# This doesn't exist in standard Keycloak, the hostname is set via env vars
print('Current realm:', config.get('realm'))
print('Display name:', config.get('displayName'))
" 2>/dev/null || echo "Could not parse realm config"
    fi
else
    echo "Could not get admin token (admin/admin credentials may not work)"
fi

echo ""
echo "=========================================="
echo "  MANUAL FIX INSTRUCTIONS"
echo "=========================================="
echo ""
echo "If the automatic fix didn't work, follow these steps:"
echo ""
echo "1. SSH into the instance:"
echo "   ssh -i YOUR_KEY.pem ubuntu@$PUBLIC_IP"
echo ""
echo "2. Find and edit the Keycloak configuration:"
echo ""
echo "   Option A: If using docker-compose:"
echo "   sudo nano /opt/kamiwaza/docker-compose.yml"
echo "   # Add/update these environment variables for the keycloak service:"
echo "   #   KC_HOSTNAME=$PUBLIC_IP"
echo "   #   KC_HOSTNAME_STRICT=false"
echo "   #   KC_HOSTNAME_STRICT_HTTPS=false"
echo ""
echo "   Option B: If using keycloak.conf:"
echo "   sudo nano /opt/kamiwaza/keycloak/conf/keycloak.conf"
echo "   # Add/update:"
echo "   #   hostname=$PUBLIC_IP"
echo ""
echo "3. Restart Keycloak:"
echo "   cd /opt/kamiwaza && docker-compose restart keycloak"
echo "   # OR"
echo "   kamiwaza restart"
echo ""
echo "4. Wait 30-60 seconds for Keycloak to restart"
echo ""
echo "5. Verify the fix:"
echo "   curl -sk https://$PUBLIC_IP/realms/kamiwaza/.well-known/openid-configuration | grep issuer"
echo "   # Should now show: https://$PUBLIC_IP/realms/kamiwaza"
echo ""
echo "=========================================="
echo ""

# Try to restart Keycloak if we made changes
if [ -n "$COMPOSE_FILE" ] || [ -n "$KEYCLOAK_CONFIG" ]; then
    echo "Restarting Keycloak to apply changes..."
    
    if [ -n "$COMPOSE_FILE" ]; then
        cd "$(dirname "$COMPOSE_FILE")"
        docker-compose restart keycloak 2>/dev/null || docker restart "$KEYCLOAK_CONTAINER" 2>/dev/null || true
    else
        docker restart "$KEYCLOAK_CONTAINER" 2>/dev/null || true
    fi
    
    echo "Waiting for Keycloak to restart (60 seconds)..."
    sleep 60
    
    # Verify
    NEW_ISSUER=$(curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration 2>/dev/null | grep -o '"issuer":"[^"]*"' | head -1 || echo "Could not retrieve")
    echo ""
    echo "New issuer: $NEW_ISSUER"
    
    if echo "$NEW_ISSUER" | grep -q "$PUBLIC_IP"; then
        echo ""
        echo "✅ SUCCESS! Keycloak hostname has been updated."
        echo "   You should now be able to login at https://$PUBLIC_IP/login"
    else
        echo ""
        echo "⚠️  The issuer still shows localhost. Please follow the manual instructions above."
    fi
fi

echo ""
echo "Done."
