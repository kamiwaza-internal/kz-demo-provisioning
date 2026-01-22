#!/usr/bin/env python3
"""
Fix Kamiwaza installation via AWS Systems Manager (SSM)
This script connects to the EC2 instance via SSM and runs repair commands
"""

import boto3
import json
import time
import sys

INSTANCE_ID = "i-0c2b296db180519f7"
REGION = "us-east-1"
MODE = "full"  # or "lite"

def send_command(ssm, commands, description):
    """Send command via SSM and wait for results"""
    print(f"\n{'='*70}")
    print(f"{description}")
    print('='*70)

    response = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={'commands': commands}
    )

    command_id = response['Command']['CommandId']
    print(f"Command ID: {command_id}")

    # Wait for command to complete
    max_attempts = 30
    for attempt in range(max_attempts):
        time.sleep(2)
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=INSTANCE_ID
            )

            status = result['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                if result['StandardOutputContent']:
                    print(result['StandardOutputContent'])
                if result['StandardErrorContent']:
                    print("STDERR:", result['StandardErrorContent'], file=sys.stderr)
                return status == 'Success'

            if attempt % 5 == 0:
                print(f"Waiting... (attempt {attempt}/{max_attempts})")

        except ssm.exceptions.InvocationDoesNotExist:
            continue

    print("Timeout waiting for command")
    return False

def main():
    print(f"Kamiwaza SSM Repair Tool")
    print(f"Instance: {INSTANCE_ID}")
    print(f"Region: {REGION}")
    print(f"Mode: {MODE}")

    try:
        ssm = boto3.client('ssm', region_name=REGION)

        # Step 1: Diagnose current state
        print("\n" + "="*70)
        print("STEP 1: DIAGNOSIS")
        print("="*70)

        send_command(ssm, [
            'echo "=== Docker Status ==="',
            'systemctl status docker --no-pager | head -10',
            'echo ""',
            'echo "=== Running Containers ==="',
            'docker ps --format "table {{.Names}}\t{{.Status}}"',
            'echo ""',
            'echo "=== Port 443 ==="',
            'sudo ss -tlnp | grep :443 || echo "Nothing on 443"',
            'echo ""',
            'echo "=== Kamiwaza Config ==="',
            'cat /opt/kamiwaza/kamiwaza/env.sh 2>/dev/null | grep -E "KAMIWAZA" || echo "No config found"'
        ], "Current State Check")

        # Step 2: Stop services
        print("\n" + "="*70)
        print("STEP 2: STOPPING SERVICES")
        print("="*70)

        send_command(ssm, [
            'sudo -u ubuntu kamiwaza stop 2>/dev/null || true',
            'sudo systemctl stop kamiwaza 2>/dev/null || true',
            'docker ps -a --format "{{.Names}}" | grep -E "kamiwaza|keycloak|traefik|backend|celery" | xargs -r docker stop',
            'sleep 5',
            'echo "Services stopped"'
        ], "Stop Existing Services")

        # Step 3: Configure mode
        print("\n" + "="*70)
        print(f"STEP 3: CONFIGURING {MODE.upper()} MODE")
        print("="*70)

        if MODE == "full":
            kamiwaza_lite = "false"
            kamiwaza_mode = "full"
            use_auth = "true"
        else:
            kamiwaza_lite = "true"
            kamiwaza_mode = "lite"
            use_auth = "false"

        send_command(ssm, [
            f'sudo sed -i "s/export KAMIWAZA_LITE=.*/export KAMIWAZA_LITE={kamiwaza_lite}/" /opt/kamiwaza/kamiwaza/env.sh',
            f'sudo sed -i "s/export KAMIWAZA_MODE=.*/export KAMIWAZA_MODE=\\"{kamiwaza_mode}\\"/" /opt/kamiwaza/kamiwaza/env.sh',
            f'sudo sed -i "s/export KAMIWAZA_USE_AUTH=.*/export KAMIWAZA_USE_AUTH={use_auth}/" /opt/kamiwaza/kamiwaza/env.sh',
            'echo "Configuration updated"',
            'cat /opt/kamiwaza/kamiwaza/env.sh | grep -E "KAMIWAZA"'
        ], "Update Configuration")

        # Update systemd service
        send_command(ssm, [
            'if [ -f /etc/systemd/system/kamiwaza.service ]; then',
            f'  sudo sed -i "s/Environment=\\"KAMIWAZA_LITE=.*\\"/Environment=\\"KAMIWAZA_LITE={kamiwaza_lite}\\"/" /etc/systemd/system/kamiwaza.service',
            f'  sudo sed -i "s/Environment=\\"KAMIWAZA_MODE=.*\\"/Environment=\\"KAMIWAZA_MODE={kamiwaza_mode}\\"/" /etc/systemd/system/kamiwaza.service',
            '  sudo systemctl daemon-reload',
            '  echo "Systemd service updated"',
            'else',
            '  echo "No systemd service found"',
            'fi'
        ], "Update Systemd Service")

        # Step 4: Start Kamiwaza
        print("\n" + "="*70)
        print("STEP 4: STARTING KAMIWAZA")
        print("="*70)
        print("This will take 2-3 minutes...")

        send_command(ssm, [
            'cd /home/ubuntu',
            'sudo -u ubuntu bash -c "export KAMIWAZA_MODE=' + kamiwaza_mode + ' && kamiwaza start" > /var/log/kamiwaza-restart.log 2>&1 &',
            'echo "Start command issued, waiting..."',
            'sleep 20',
            'echo "Initial wait complete"'
        ], "Start Kamiwaza")

        # Step 5: Wait for startup
        print("\nWaiting 120 seconds for full startup...")
        time.sleep(120)

        # Step 6: Check status
        print("\n" + "="*70)
        print("STEP 5: FINAL STATUS CHECK")
        print("="*70)

        send_command(ssm, [
            'echo "=== Docker Containers ==="',
            'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"',
            'echo ""',
            'echo "=== Port 443 Status ==="',
            'sudo ss -tlnp | grep :443 || echo "Nothing listening on 443"',
            'echo ""',
            'echo "=== Service Counts ==="',
            'echo "Backend: $(docker ps | grep -c backend || echo 0)"',
            'echo "Keycloak: $(docker ps | grep -c keycloak || echo 0)"',
            'echo "Traefik: $(docker ps | grep -c traefik || echo 0)"',
            'echo ""',
            'echo "=== Recent Logs ==="',
            'tail -30 /var/log/kamiwaza-restart.log',
            'echo ""',
            'tail -20 /opt/kamiwaza/kamiwaza/logs/kamiwazad.log 2>/dev/null || echo "No daemon log"'
        ], "Final Status")

        # Step 7: Test connectivity
        print("\n" + "="*70)
        print("STEP 6: CONNECTIVITY TEST")
        print("="*70)

        success = send_command(ssm, [
            'curl -sk https://localhost/ > /dev/null 2>&1 && echo "✓ Local HTTPS working" || echo "✗ Local HTTPS failed"',
            'curl -sk -o /dev/null -w "%{http_code}" https://localhost/ 2>/dev/null || echo "Connection failed"'
        ], "Test Local Connection")

        print("\n" + "="*70)
        print("REPAIR COMPLETE")
        print("="*70)

        if success:
            print("\n✓ Kamiwaza should now be accessible at:")
            print("  https://100.53.110.232/")
            if MODE == "full":
                print("\nDefault credentials:")
                print("  Username: admin")
                print("  Password: kamiwaza")
            else:
                print("\n(Lite mode - no login required)")
        else:
            print("\n⚠ Some commands failed. Check the output above for errors.")
            print("\nTry running manually:")
            print("  ssh ubuntu@100.53.110.232")
            print("  export KAMIWAZA_MODE=" + kamiwaza_mode)
            print("  kamiwaza start")

    except boto3.exceptions.NoCredentialsError:
        print("\n❌ ERROR: No AWS credentials found")
        print("\nPlease configure AWS credentials:")
        print("  aws configure")
        print("\nOr set environment variables:")
        print("  export AWS_ACCESS_KEY_ID=...")
        print("  export AWS_SECRET_ACCESS_KEY=...")
        print("  export AWS_SESSION_TOKEN=...")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
