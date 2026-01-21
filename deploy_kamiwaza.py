#!/usr/bin/env python3
"""
Kamiwaza EC2 Deployment CLI

This script provides a simple command-line interface to deploy Kamiwaza
to AWS EC2 using the kz-demo-provisioning system with AWS CDK.

Usage:
    python3 deploy_kamiwaza.py [options]

Example:
    python3 deploy_kamiwaza.py \
        --name kamiwaza-demo \
        --region us-east-1 \
        --instance-type t3.xlarge \
        --package-url https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/kamiwaza_v0.9.2_noble_x86_64_build3.deb
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import ssl
from pathlib import Path


def print_banner():
    """Print deployment banner"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║     Kamiwaza EC2 Deployment Tool                           ║
║                                                              ║
║     Deploy full Kamiwaza platform to AWS EC2               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)


def check_prerequisites():
    """Check that required tools are installed"""
    print("Checking prerequisites...")

    # Check Python
    if sys.version_info < (3, 9):
        print("❌ Python 3.9+ required")
        return False
    print("✓ Python 3.9+ found")

    # Check AWS CLI
    try:
        subprocess.run(["aws", "--version"], capture_output=True, check=True)
        print("✓ AWS CLI found")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ AWS CLI not found - install from https://aws.amazon.com/cli/")
        return False

    # Check CDK
    try:
        subprocess.run(["npx", "cdk", "--version"], capture_output=True, check=True)
        print("✓ AWS CDK found")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ AWS CDK not found - install with: npm install -g aws-cdk")
        return False

    return True


def generate_user_data(package_url: str, use_cached_ami: bool = False) -> str:
    """Generate user data script"""

    if use_cached_ami:
        print("Using pre-configured AMI - minimal user data (Kamiwaza already installed)")
        # Minimal user data for AMI-based deployments (Kamiwaza already installed)
        user_data = """#!/bin/bash
# Kamiwaza is pre-installed in this AMI
# Just ensure it starts on boot

set -euo pipefail

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/kamiwaza-firstboot.log
}

log "=========================================="
log "Kamiwaza First Boot (from cached AMI)"
log "=========================================="

# Start Kamiwaza (it's already installed)
log "Starting Kamiwaza..."
su - ubuntu -c "kamiwaza start" 2>&1 | tee -a /var/log/kamiwaza-startup.log &

log "✓ Kamiwaza start initiated"
log "This deployment used a pre-configured AMI (fast deployment)"
log "Monitor startup: sudo tail -f /var/log/kamiwaza-startup.log"
"""
        user_data_b64 = base64.b64encode(user_data.encode()).decode()
        print(f"✓ User data generated for AMI deployment ({len(user_data)} bytes)")
        return user_data_b64

    # Standard deployment with .deb package installation
    print(f"Generating user data for package: {package_url}")

    script_path = Path(__file__).parent / "scripts" / "deploy_kamiwaza_full.sh"
    if not script_path.exists():
        print(f"❌ Deployment script not found at {script_path}")
        sys.exit(1)

    deployment_script = script_path.read_text()

    # Build user data
    user_data = "#!/bin/bash\n\n"
    user_data += "# Kamiwaza Deployment Configuration\n"
    user_data += f"export KAMIWAZA_PACKAGE_URL='{package_url}'\n"
    user_data += "export KAMIWAZA_ROOT='/opt/kamiwaza'\n"
    user_data += "export KAMIWAZA_USER='ubuntu'\n"
    user_data += "\n"
    user_data += deployment_script

    # Encode to base64
    user_data_b64 = base64.b64encode(user_data.encode()).decode()

    print(f"✓ User data generated ({len(user_data)} bytes)")
    return user_data_b64


def test_kamiwaza_login_page(public_ip: str, timeout_minutes: int = 30) -> bool:
    """
    Test that the Kamiwaza login page is accessible.

    Args:
        public_ip: The public IP address of the Kamiwaza instance
        timeout_minutes: Maximum time to wait for the page to become accessible

    Returns:
        True if login page is accessible, False otherwise
    """
    print("\n" + "="*60)
    print("TESTING KAMIWAZA LOGIN PAGE ACCESSIBILITY")
    print("="*60)
    print(f"Testing URL: https://{public_ip}")
    print(f"Timeout: {timeout_minutes} minutes")
    print("This may take 10-30 minutes as Kamiwaza completes installation...")

    url = f"https://{public_ip}"
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    retry_interval = 30  # Check every 30 seconds

    # Create SSL context that doesn't verify certificates (self-signed cert)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    attempt = 0
    while True:
        attempt += 1
        elapsed = time.time() - start_time

        if elapsed > timeout_seconds:
            print(f"\n❌ Timeout reached after {timeout_minutes} minutes")
            print(f"   The login page is not yet accessible at {url}")
            print(f"   Kamiwaza may still be installing. Check deployment logs on the instance.")
            return False

        try:
            print(f"\nAttempt {attempt} (elapsed: {int(elapsed/60)}m {int(elapsed%60)}s)...", end=" ")

            request = urllib.request.Request(url, headers={'User-Agent': 'Kamiwaza-Deployment-Test'})
            with urllib.request.urlopen(request, context=ssl_context, timeout=10) as response:
                status_code = response.getcode()
                content = response.read().decode('utf-8', errors='ignore')

                # Check if we got a successful response
                if status_code == 200:
                    # Verify it's actually the Kamiwaza login page
                    if 'kamiwaza' in content.lower() or 'login' in content.lower():
                        print(f"✓ SUCCESS!")
                        print(f"\n✅ Kamiwaza login page is accessible!")
                        print(f"   URL: {url}")
                        print(f"   Status: {status_code}")
                        print(f"   Time to ready: {int(elapsed/60)} minutes {int(elapsed%60)} seconds")
                        return True
                    else:
                        print(f"⚠ Got 200 but content doesn't look like Kamiwaza login page")
                else:
                    print(f"⚠ Got status {status_code}")

        except urllib.error.HTTPError as e:
            print(f"⚠ HTTP {e.code}")
        except urllib.error.URLError as e:
            print(f"⚠ Connection failed: {e.reason}")
        except Exception as e:
            print(f"⚠ Error: {type(e).__name__}")

        # Wait before retrying
        remaining = timeout_seconds - elapsed
        if remaining > 0:
            wait_time = min(retry_interval, remaining)
            time.sleep(wait_time)
        else:
            break

    return False


def deploy_with_cdk(
    stack_name: str,
    region: str,
    instance_type: str,
    volume_size: int,
    user_data_b64: str,
    key_pair_name: str = None,
    vpc_id: str = None,
    subnet_id: str = None,
    role_arn: str = None,
    external_id: str = None,
    skip_login_test: bool = False,
    ami_id: str = None
):
    """Deploy using AWS CDK"""
    print("\nDeploying with AWS CDK...")

    # Set environment variables for CDK
    env = os.environ.copy()
    env["CDK_STACK_NAME"] = stack_name
    env["AWS_DEFAULT_REGION"] = region

    # Create CDK context
    context = {
        "instanceType": instance_type,
        "userData": user_data_b64,
        "jobId": stack_name.replace("-", "_")
    }

    if key_pair_name:
        context["keyPairName"] = key_pair_name
    if vpc_id:
        context["vpcId"] = vpc_id
    if subnet_id:
        context["subnetId"] = subnet_id
    if ami_id:
        context["amiId"] = ami_id
        print(f"Using custom AMI: {ami_id}")

    # Save context to file
    context_file = Path("cdk.context.json")
    if context_file.exists():
        existing_context = json.loads(context_file.read_text())
        existing_context.update(context)
        context = existing_context

    context_file.write_text(json.dumps(context, indent=2))

    # Run CDK bootstrap (if needed)
    print("Ensuring CDK is bootstrapped...")
    try:
        subprocess.run(
            ["npx", "cdk", "bootstrap", f"aws://unknown-account/{region}"],
            cwd=Path(__file__).parent / "cdk",
            env=env,
            check=False
        )
    except Exception as e:
        print(f"⚠ Bootstrap warning: {e}")

    # Run CDK deploy
    print(f"\nDeploying stack: {stack_name}")
    print("This may take 20-30 minutes...")

    try:
        result = subprocess.run(
            [
                "npx", "cdk", "deploy",
                "--require-approval", "never",
                "--outputs-file", f"outputs-{stack_name}.json"
            ],
            cwd=Path(__file__).parent / "cdk",
            env=env,
            check=True
        )

        print("\n✓ Deployment successful!")

        # Read outputs
        outputs_file = Path(__file__).parent / "cdk" / f"outputs-{stack_name}.json"
        if outputs_file.exists():
            outputs = json.loads(outputs_file.read_text())
            print("\n" + "="*60)
            print("DEPLOYMENT OUTPUTS")
            print("="*60)
            for key, value in outputs.get(stack_name, {}).items():
                print(f"{key}: {value}")

            # Extract public IP
            public_ip = outputs.get(stack_name, {}).get("PublicIP")
            if public_ip:
                print("\n" + "="*60)
                print("ACCESS INFORMATION")
                print("="*60)
                print(f"Kamiwaza URL: https://{public_ip}")
                print(f"Username: admin")
                print(f"Password: kamiwaza")
                print("\n⏳ Note: Deployment is still in progress on the EC2 instance.")
                print("   It may take 10-20 more minutes for Kamiwaza to be fully ready.")
                print(f"   Monitor progress: ssh ubuntu@{public_ip} -i your-key.pem")
                print(f"   Then run: sudo tail -f /var/log/kamiwaza-deployment.log")

                # Test login page accessibility
                if not skip_login_test:
                    login_page_accessible = test_kamiwaza_login_page(public_ip, timeout_minutes=30)

                    if not login_page_accessible:
                        print("\n⚠ WARNING: Login page test did not complete successfully")
                        print("   The deployment may still be in progress.")
                        print("   You can manually check the login page later.")
                else:
                    print("\n⏭ Skipping login page accessibility test (--skip-login-test specified)")

        return True

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Deployment failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Kamiwaza to AWS EC2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic deployment (fresh install - 30+ minutes)
  python3 deploy_kamiwaza.py --name kamiwaza-demo

  # Fast deployment with cached AMI (~5 minutes)
  python3 deploy_kamiwaza.py --name kamiwaza-demo --ami-id ami-0123456789abcdef0

  # Full options
  python3 deploy_kamiwaza.py \\
      --name kamiwaza-prod \\
      --region us-west-2 \\
      --instance-type t3.2xlarge \\
      --volume-size 200 \\
      --key-pair my-ssh-key \\
      --ami-id ami-0123456789abcdef0

For more information, see AMI_CACHING_GUIDE.md
        """
    )

    # Required arguments
    parser.add_argument(
        "--name",
        required=True,
        help="Deployment name (will be used as CloudFormation stack name)"
    )

    # AWS configuration
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)"
    )
    parser.add_argument(
        "--instance-type",
        default="t3.xlarge",
        help="EC2 instance type (default: t3.xlarge)"
    )
    parser.add_argument(
        "--volume-size",
        type=int,
        default=100,
        help="EBS volume size in GB (default: 100)"
    )
    parser.add_argument(
        "--key-pair",
        help="SSH key pair name for instance access"
    )
    parser.add_argument(
        "--vpc-id",
        help="VPC ID (optional, will create new VPC if not specified)"
    )
    parser.add_argument(
        "--subnet-id",
        help="Subnet ID (optional)"
    )

    # Kamiwaza configuration
    parser.add_argument(
        "--package-url",
        default="https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/kamiwaza_v0.9.2_noble_x86_64_build3.deb",
        help="URL to Kamiwaza .deb package (default: v0.9.2 noble x86_64 build3)"
    )
    parser.add_argument(
        "--ami-id",
        help="Pre-configured Kamiwaza AMI ID for faster deployment (skips .deb installation)"
    )

    # AWS authentication
    parser.add_argument(
        "--role-arn",
        help="IAM role ARN to assume for deployment"
    )
    parser.add_argument(
        "--external-id",
        help="External ID for role assumption"
    )

    # Options
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip prerequisite checks"
    )
    parser.add_argument(
        "--skip-login-test",
        action="store_true",
        help="Skip the login page accessibility test after deployment"
    )

    args = parser.parse_args()

    # Print banner
    print_banner()

    # Check prerequisites
    if not args.skip_checks:
        if not check_prerequisites():
            print("\n❌ Prerequisites not met. Install required tools and try again.")
            sys.exit(1)
        print()

    # Generate user data
    use_cached_ami = bool(args.ami_id)
    user_data_b64 = generate_user_data(args.package_url, use_cached_ami=use_cached_ami)

    # Deploy with CDK
    print(f"\nDeployment Configuration:")
    print(f"  Name: {args.name}")
    print(f"  Region: {args.region}")
    print(f"  Instance Type: {args.instance_type}")
    print(f"  Volume Size: {args.volume_size} GB")
    if args.ami_id:
        print(f"  AMI ID: {args.ami_id} (pre-configured - fast deployment)")
        print(f"  Expected deployment time: ~5 minutes")
    else:
        print(f"  Package URL: {args.package_url}")
        print(f"  Expected deployment time: ~30 minutes (fresh installation)")
    if args.key_pair:
        print(f"  Key Pair: {args.key_pair}")
    if args.vpc_id:
        print(f"  VPC ID: {args.vpc_id}")

    print("\n⚠ This will create AWS resources that incur costs.")
    response = input("Continue? (yes/no): ")
    if response.lower() not in ["yes", "y"]:
        print("Deployment cancelled.")
        sys.exit(0)

    success = deploy_with_cdk(
        stack_name=args.name,
        region=args.region,
        instance_type=args.instance_type,
        volume_size=args.volume_size,
        user_data_b64=user_data_b64,
        key_pair_name=args.key_pair,
        vpc_id=args.vpc_id,
        subnet_id=args.subnet_id,
        role_arn=args.role_arn,
        external_id=args.external_id,
        skip_login_test=args.skip_login_test,
        ami_id=args.ami_id
    )

    if success:
        print("\n✅ Deployment initiated successfully!")
        print("\nNext steps:")
        print("1. Monitor CloudFormation stack in AWS Console")
        print("2. Wait for EC2 instance to complete Kamiwaza installation (20-30 min)")
        print("3. Access Kamiwaza at the URL shown above")
        print(f"\nTo destroy this deployment later:")
        print(f"  cd cdk && npx cdk destroy {args.name}")
    else:
        print("\n❌ Deployment failed. Check the error messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
