#!/bin/bash
#
# Complete Keycloak Configuration Fix for Kamiwaza
#
# This script fixes the Keycloak hostname and issuer configuration
# to allow proper authentication from external clients.
#
# Run this script ON THE EC2 INSTANCE:
#   sudo bash fix_keycloak_full.sh
#
# Or remotely:
#   ssh -i your-key.pem ubuntu@3.218.164.211 'sudo bash -s' < scripts/fix_keycloak_full.sh
#

set -euo pipefail

echo "=========================================="
echo "  Keycloak Full Configuration Fix"
echo "=========================================="
echo ""

# Get the public IP from EC2 metadata
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")

if [ -z "$PUBLIC_IP" ]; then
    echo "ERROR: Could not detect public IP."
    echo "If running this script manually, set PUBLIC_IP environment variable:"
    echo "  export PUBLIC_IP=3.218.164.211"
    echo "  sudo bash fix_keycloak_full.sh"
    exit 1
fi

echo "Public IP: $PUBLIC_IP"
echo ""

# Find docker-compose file
COMPOSE_FILE=""
COMPOSE_DIR=""
for dir in /opt/kamiwaza /opt/kamiwaza/kamiwaza /home/ubuntu/kamiwaza; do
    if [ -f "$dir/docker-compose.yml" ]; then
        COMPOSE_FILE="$dir/docker-compose.yml"
        COMPOSE_DIR="$dir"
        break
    fi
done

if [ -z "$COMPOSE_FILE" ]; then
    echo "ERROR: Could not find docker-compose.yml"
    echo "Searching for docker-compose files..."
    find /opt /home -name "docker-compose.yml" 2>/dev/null || true
    exit 1
fi

echo "Found docker-compose: $COMPOSE_FILE"
echo ""

# Backup the file
BACKUP_FILE="${COMPOSE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$COMPOSE_FILE" "$BACKUP_FILE"
echo "Created backup: $BACKUP_FILE"

# Check current Keycloak configuration
echo ""
echo "Current Keycloak environment variables:"
grep -A 50 "keycloak:" "$COMPOSE_FILE" | grep -E "KC_|KEYCLOAK_" | head -20 || echo "  (none found)"
echo ""

# Update Keycloak configuration
echo "Updating Keycloak configuration..."

# Create a Python script to update the docker-compose.yml
python3 << EOF
import yaml
import sys

compose_file = "$COMPOSE_FILE"
public_ip = "$PUBLIC_IP"

# Read the file
with open(compose_file, 'r') as f:
    compose = yaml.safe_load(f)

# Find keycloak service
keycloak_service = None
for service_name in compose.get('services', {}):
    if 'keycloak' in service_name.lower():
        keycloak_service = service_name
        break

if not keycloak_service:
    print("ERROR: Could not find keycloak service in docker-compose.yml")
    sys.exit(1)

print(f"Found keycloak service: {keycloak_service}")

# Get or create environment section
service = compose['services'][keycloak_service]
if 'environment' not in service:
    service['environment'] = {}

env = service['environment']

# Handle both list and dict format
if isinstance(env, list):
    # Convert list to dict
    env_dict = {}
    for item in env:
        if '=' in item:
            key, value = item.split('=', 1)
            env_dict[key] = value
        else:
            env_dict[item] = ""
    env = env_dict
    service['environment'] = env

# Set the correct Keycloak hostname configuration
# KC_HOSTNAME: The hostname for Keycloak (without protocol)
# KC_HOSTNAME_URL: The full URL (optional, overrides KC_HOSTNAME)
# KC_HOSTNAME_STRICT: Whether to validate hostname strictly
# KC_HOSTNAME_STRICT_HTTPS: Whether to require HTTPS
# KC_PROXY: Proxy mode (edge for reverse proxy terminating TLS)

env['KC_HOSTNAME'] = public_ip
env['KC_HOSTNAME_URL'] = f'https://{public_ip}'
env['KC_HOSTNAME_STRICT'] = 'false'
env['KC_HOSTNAME_STRICT_HTTPS'] = 'false'
env['KC_PROXY'] = 'edge'
env['KC_HTTP_ENABLED'] = 'true'

# Also set the frontend URL for the realm
env['KC_HOSTNAME_ADMIN_URL'] = f'https://{public_ip}'

print("Updated environment variables:")
for key in ['KC_HOSTNAME', 'KC_HOSTNAME_URL', 'KC_HOSTNAME_STRICT', 'KC_HOSTNAME_STRICT_HTTPS', 'KC_PROXY', 'KC_HTTP_ENABLED', 'KC_HOSTNAME_ADMIN_URL']:
    if key in env:
        print(f"  {key}={env[key]}")

# Write back
with open(compose_file, 'w') as f:
    yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

print(f"\nUpdated {compose_file}")
EOF

if [ $? -ne 0 ]; then
    echo ""
    echo "Python YAML update failed. Trying sed-based approach..."
    
    # Restore backup
    cp "$BACKUP_FILE" "$COMPOSE_FILE"
    
    # Simple sed-based approach - add environment variables
    # This is a fallback if PyYAML isn't available
    
    # Check if KC_HOSTNAME already exists
    if grep -q "KC_HOSTNAME" "$COMPOSE_FILE"; then
        echo "Updating existing KC_HOSTNAME settings..."
        sed -i "s|KC_HOSTNAME=.*|KC_HOSTNAME=$PUBLIC_IP|g" "$COMPOSE_FILE"
        sed -i "s|KC_HOSTNAME_URL=.*|KC_HOSTNAME_URL=https://$PUBLIC_IP|g" "$COMPOSE_FILE"
    else
        echo "WARNING: Could not automatically add KC_HOSTNAME settings."
        echo "Please manually edit $COMPOSE_FILE and add these to the keycloak service:"
        echo ""
        echo "    environment:"
        echo "      KC_HOSTNAME: $PUBLIC_IP"
        echo "      KC_HOSTNAME_URL: https://$PUBLIC_IP"
        echo "      KC_HOSTNAME_STRICT: 'false'"
        echo "      KC_HOSTNAME_STRICT_HTTPS: 'false'"
        echo "      KC_PROXY: edge"
        echo "      KC_HTTP_ENABLED: 'true'"
    fi
fi

echo ""
echo "=========================================="
echo "  Restarting Keycloak"
echo "=========================================="
echo ""

cd "$COMPOSE_DIR"

# Stop and remove the old keycloak container to ensure new config is used
echo "Stopping Keycloak..."
docker-compose stop keycloak 2>/dev/null || docker stop $(docker ps -q --filter name=keycloak) 2>/dev/null || true

echo "Removing old Keycloak container..."
docker-compose rm -f keycloak 2>/dev/null || docker rm -f $(docker ps -aq --filter name=keycloak) 2>/dev/null || true

echo "Starting Keycloak with new configuration..."
docker-compose up -d keycloak 2>/dev/null || true

echo ""
echo "Waiting for Keycloak to start (this may take 60-90 seconds)..."
echo ""

# Wait for Keycloak to be ready
MAX_WAIT=120
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    sleep 10
    ELAPSED=$((ELAPSED + 10))
    
    # Check if Keycloak is responding
    HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "https://localhost/realms/kamiwaza/.well-known/openid-configuration" 2>/dev/null || echo "000")
    
    if [ "$HTTP_CODE" = "200" ]; then
        echo "✓ Keycloak is responding"
        break
    else
        echo "  Waiting... ($ELAPSED seconds, HTTP: $HTTP_CODE)"
    fi
done

echo ""
echo "=========================================="
echo "  Verifying Configuration"
echo "=========================================="
echo ""

# Check the new issuer
NEW_ISSUER=$(curl -sk https://localhost/realms/kamiwaza/.well-known/openid-configuration 2>/dev/null | grep -o '"issuer":"[^"]*"' | head -1 || echo "Could not retrieve")
echo "New issuer: $NEW_ISSUER"

if echo "$NEW_ISSUER" | grep -q "$PUBLIC_IP"; then
    echo ""
    echo "✅ SUCCESS! Keycloak issuer has been updated to include $PUBLIC_IP"
elif echo "$NEW_ISSUER" | grep -q "localhost"; then
    echo ""
    echo "⚠️  WARNING: Issuer still shows localhost"
    echo ""
    echo "The configuration change may not have taken effect."
    echo "Try these additional steps:"
    echo ""
    echo "1. Check Keycloak logs for errors:"
    echo "   docker logs \$(docker ps -q --filter name=keycloak) --tail 100"
    echo ""
    echo "2. Try a full restart of all services:"
    echo "   cd $COMPOSE_DIR"
    echo "   docker-compose down"
    echo "   docker-compose up -d"
    echo ""
    echo "3. If using Kamiwaza CLI:"
    echo "   kamiwaza stop"
    echo "   kamiwaza start"
else
    echo ""
    echo "⚠️  Could not verify new configuration"
fi

# Test authentication
echo ""
echo "=========================================="
echo "  Testing Authentication"
echo "=========================================="
echo ""

# Get a new token
echo "Getting new token..."
TOKEN_RESPONSE=$(curl -sk -X POST "https://localhost/api/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=admin&password=kamiwaza" 2>/dev/null)

if echo "$TOKEN_RESPONSE" | grep -q "access_token"; then
    echo "✓ Got access token"
    
    # Extract and decode token
    ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
    
    # Decode JWT payload
    PAYLOAD=$(echo "$ACCESS_TOKEN" | cut -d'.' -f2 | python3 -c "
import sys, base64, json
payload = sys.stdin.read().strip()
payload += '=' * (4 - len(payload) % 4)
decoded = base64.urlsafe_b64decode(payload)
data = json.loads(decoded)
print('Token issuer:', data.get('iss', 'N/A'))
print('Token user:', data.get('preferred_username', 'N/A'))
" 2>/dev/null)
    echo "$PAYLOAD"
    
    # Test API call with token
    echo ""
    echo "Testing API call with new token..."
    API_RESPONSE=$(curl -sk -X GET "https://localhost/api/auth/validate" \
        -H "Authorization: Bearer $ACCESS_TOKEN" -w "\nHTTP: %{http_code}" 2>/dev/null)
    
    HTTP_CODE=$(echo "$API_RESPONSE" | tail -1)
    BODY=$(echo "$API_RESPONSE" | head -n -1)
    
    if echo "$HTTP_CODE" | grep -q "200"; then
        echo "✅ API authentication working!"
    elif echo "$HTTP_CODE" | grep -q "401"; then
        echo "❌ API still returning 401 Unauthorized"
        echo "Response: $BODY"
        echo ""
        echo "The backend may need to be restarted to pick up the new Keycloak config."
        echo "Try:"
        echo "  docker-compose restart backend"
        echo "  # OR"
        echo "  kamiwaza restart"
    else
        echo "API response: $HTTP_CODE"
        echo "$BODY"
    fi
else
    echo "❌ Could not get access token"
    echo "Response: $TOKEN_RESPONSE"
fi

echo ""
echo "=========================================="
echo "  Next Steps"
echo "=========================================="
echo ""
echo "1. Clear your browser cache and cookies for https://$PUBLIC_IP"
echo ""
echo "2. Try logging in again at: https://$PUBLIC_IP/login"
echo "   Username: admin"
echo "   Password: kamiwaza"
echo ""
echo "3. If still not working, restart all services:"
echo "   cd $COMPOSE_DIR"
echo "   docker-compose restart"
echo ""
echo "4. Check logs for errors:"
echo "   docker-compose logs -f keycloak"
echo "   docker-compose logs -f backend"
echo ""
echo "=========================================="
echo "  Done"
echo "=========================================="
