"""
AWS CDK-based provisioning with IAM role assumption

This module uses AWS CDK to provision EC2 instances with proper IAM role-based authentication
instead of long-lived access keys.
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class AWSCDKProvisioner:
    """
    AWS CDK-based EC2 provisioning with role assumption.

    Supports multiple authentication methods:
    1. IAM Role ARN (recommended) - AssumeRole from current credentials
    2. AWS SSO Profile - Use SSO session
    3. Access Keys (fallback) - Traditional access key/secret
    """

    def __init__(self):
        self.cdk_app_dir = Path(__file__).parent.parent / "cdk"

    def get_auth_method(self) -> str:
        """Determine which authentication method to use based on environment"""
        if os.environ.get("AWS_ASSUME_ROLE_ARN"):
            return "assume_role"
        elif os.environ.get("AWS_SSO_PROFILE"):
            return "sso"
        elif os.environ.get("AWS_ACCESS_KEY_ID"):
            return "access_keys"
        else:
            return "none"

    def check_base_credentials(self) -> Tuple[bool, Optional[str]]:
        """
        Check if base AWS credentials are available for AssumeRole operations.

        Returns:
            Tuple of (credentials_available, message)
        """
        import boto3
        from botocore.exceptions import NoCredentialsError, ClientError
        from app.config import settings

        # Check what auth method is configured
        auth_method = settings.aws_auth_method

        try:
            sts_client = None

            if auth_method == "assume_role":
                # For assume role, we need base credentials to assume the role
                # Check environment variables first (worker tasks use these)
                access_key = os.environ.get("AWS_ACCESS_KEY_ID") or settings.aws_access_key_id
                secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or settings.aws_secret_access_key

                if not access_key or not secret_key:
                    return (False, "AWS assume role configured but no base credentials found. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in Settings.")

                # Try with configured credentials
                sts_client = boto3.client(
                    'sts',
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key
                )

            elif auth_method == "access_keys":
                # Check environment variables first (worker tasks use these), then settings
                access_key = os.environ.get("AWS_ACCESS_KEY_ID") or settings.aws_access_key_id
                secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or settings.aws_secret_access_key

                if not access_key or not secret_key:
                    return (False, "AWS access keys not configured. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in Settings.")

                # Create STS client with configured credentials
                sts_client = boto3.client(
                    'sts',
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key
                )

            else:
                return (False, f"Unknown auth method: {auth_method}. Please configure in Settings.")

            # Try to get caller identity to verify credentials work
            response = sts_client.get_caller_identity()

            return (True, f"✓ Authenticated as: {response.get('Arn', 'Unknown')}")

        except NoCredentialsError:
            return (False, "No AWS credentials found. Please configure credentials in Settings.")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            return (False, f"AWS credentials invalid ({error_code}): {error_msg}")
        except Exception as e:
            return (False, f"Error checking credentials: {str(e)}")

    def validate_cdk_installed(self) -> Tuple[bool, Optional[str]]:
        """Check if AWS CDK is installed"""
        try:
            result = subprocess.run(
                ["npx", "cdk", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return (True, result.stdout.strip())
            else:
                return (False, "CDK not found")
        except Exception as e:
            return (False, str(e))

    def assume_role(
        self,
        role_arn: str,
        session_name: str = "kamiwaza-provisioner",
        external_id: Optional[str] = None,
        region: str = "us-west-2"
    ) -> Dict[str, str]:
        """
        Assume an IAM role and return temporary credentials.

        This is the recommended authentication method as it doesn't require
        storing long-lived access keys.

        Args:
            role_arn: ARN of the role to assume (e.g., arn:aws:iam::123456789012:role/KamiwazaProvisionerRole)
            session_name: Session name for tracking
            external_id: Optional external ID for additional security
            region: AWS region

        Returns:
            Dict with temporary credentials
        """
        import boto3
        from app.config import settings

        logger.info(f"Assuming role: {role_arn}")

        try:
            # Create STS client with base credentials from settings
            # This is needed because boto3's default credential chain might not find them
            sts_client = boto3.client(
                'sts',
                region_name=region,
                aws_access_key_id=settings.aws_access_key_id or None,
                aws_secret_access_key=settings.aws_secret_access_key or None
            )

            assume_role_params = {
                'RoleArn': role_arn,
                'RoleSessionName': session_name
            }

            if external_id:
                assume_role_params['ExternalId'] = external_id

            response = sts_client.assume_role(**assume_role_params)

            credentials = response['Credentials']

            return {
                'access_key': credentials['AccessKeyId'],
                'secret_key': credentials['SecretAccessKey'],
                'session_token': credentials['SessionToken'],
                'expiration': credentials['Expiration'].isoformat(),
                'region': region
            }
        except Exception as e:
            logger.error(f"Failed to assume role: {e}")
            raise Exception(f"Role assumption failed: {str(e)}")

    def get_caller_identity(self, credentials: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Get AWS caller identity (account ID, user ARN, etc.)"""
        import boto3

        if credentials:
            sts_client = boto3.client(
                'sts',
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key'],
                aws_session_token=credentials.get('session_token'),
                region_name=credentials.get('region', 'us-west-2')
            )
        else:
            sts_client = boto3.client('sts')

        response = sts_client.get_caller_identity()

        return {
            'account_id': response['Account'],
            'arn': response['Arn'],
            'user_id': response['UserId']
        }

    def bootstrap_cdk(
        self,
        credentials: Dict[str, str],
        region: str = "us-west-2"
    ) -> Tuple[bool, str]:
        """
        Bootstrap CDK in the AWS account (one-time setup).

        This creates the necessary S3 bucket and IAM roles for CDK deployments.
        """
        logger.info(f"Bootstrapping CDK in region: {region}")

        env = {
            **os.environ,
            'AWS_ACCESS_KEY_ID': credentials['access_key'],
            'AWS_SECRET_ACCESS_KEY': credentials['secret_key'],
            'AWS_DEFAULT_REGION': region
        }

        if credentials.get('session_token'):
            env['AWS_SESSION_TOKEN'] = credentials['session_token']

        try:
            result = subprocess.run(
                ["npx", "cdk", "bootstrap", f"aws://unknown-account/{region}"],
                capture_output=True,
                text=True,
                env=env,
                cwd=self.cdk_app_dir,
                timeout=300
            )

            if result.returncode == 0:
                return (True, result.stdout)
            else:
                return (False, result.stderr)
        except Exception as e:
            return (False, str(e))

    def deploy_ec2_instance(
        self,
        job_id: int,
        credentials: Dict[str, str],
        instance_config: Dict,
        callback=None
    ) -> Tuple[bool, Dict, List[str]]:
        """
        Deploy EC2 instance using AWS CDK.

        Args:
            job_id: Job ID for tracking
            credentials: AWS credentials (from assume_role or access keys)
            instance_config: Configuration dict with:
                - instance_type
                - ami_id (optional)
                - vpc_id (optional)
                - subnet_id (optional)
                - security_group_ids (optional)
                - key_pair_name (optional)
                - user_data (optional)
                - tags (optional)
            callback: Optional callback for log output

        Returns:
            Tuple of (success, outputs dict, log lines)
        """
        log_lines = []

        def log(msg: str):
            log_lines.append(msg)
            if callback:
                callback(msg)
            logger.info(msg)

        # Get volume size with sensible default
        volume_size = instance_config.get('volume_size', 100)
        
        log("=" * 60)
        log(f"STARTING CDK DEPLOYMENT FOR JOB {job_id}")
        log("=" * 60)
        log(f"Region: {credentials.get('region', 'us-west-2')}")
        log(f"Instance Type: {instance_config.get('instance_type', 't3.medium')}")
        log(f"Volume Size: {volume_size} GB")
        log("")

        # Generate CDK context
        context = {
            'jobId': job_id,
            'instanceType': instance_config.get('instance_type', 't3.medium'),
            'region': credentials.get('region', 'us-west-2'),
            'volumeSize': volume_size
        }

        if instance_config.get('ami_id'):
            context['amiId'] = instance_config['ami_id']
        if instance_config.get('vpc_id'):
            context['vpcId'] = instance_config['vpc_id']
        if instance_config.get('subnet_id'):
            context['subnetId'] = instance_config['subnet_id']
        if instance_config.get('key_pair_name'):
            context['keyPairName'] = instance_config['key_pair_name']
        if instance_config.get('user_data'):
            context['userData'] = instance_config['user_data']
        if instance_config.get('tags'):
            context['tags'] = instance_config['tags']
        ssh_cidrs = instance_config.get('ssh_allowed_cidrs')
        if ssh_cidrs and isinstance(ssh_cidrs, list) and len(ssh_cidrs) > 0:
            context['sshAllowedCidrs'] = [c for c in ssh_cidrs if c and c.strip() and c.strip() != "0.0.0.0/0"]

        # Set up environment
        env = {
            **os.environ,
            'AWS_ACCESS_KEY_ID': credentials['access_key'],
            'AWS_SECRET_ACCESS_KEY': credentials['secret_key'],
            'AWS_DEFAULT_REGION': credentials.get('region', 'us-west-2'),
            'CDK_STACK_NAME': f"kamiwaza-job-{job_id}"
        }

        if credentials.get('session_token'):
            env['AWS_SESSION_TOKEN'] = credentials['session_token']

        # Write context to file
        context_file = self.cdk_app_dir / f"cdk.context.{job_id}.json"
        with open(context_file, 'w') as f:
            json.dump(context, f, indent=2)

        # Clear CDK context cache to avoid stale VPC/subnet lookups
        # This prevents errors from deleted subnets that are still in cache
        cdk_context_cache = self.cdk_app_dir / "cdk.context.json"
        if cdk_context_cache.exists():
            log("Preparing CDK environment...")
            log("  • Clearing CDK context cache to ensure fresh VPC/subnet lookups")
            cdk_context_cache.unlink()
            log("  • Cache cleared successfully")
        log("")

        try:
            # CDK synth
            log("=" * 60)
            log("STAGE 1: CDK Synth (Generating CloudFormation template)")
            log("=" * 60)
            
            # Log context without userData (too long) for readability
            context_for_log = {k: v for k, v in context.items() if k != 'userData'}
            log(f"Context: {json.dumps(context_for_log, indent=2)}")
            
            # Log user data size separately
            if 'userData' in context:
                user_data_size = len(context['userData'])
                log(f"User Data: {user_data_size} bytes (base64 encoded)")
                if user_data_size > 14000:
                    log(f"⚠️  User data is close to 16KB limit - consider using cached AMI")

            # Pass context as individual key=value pairs
            context_args = []
            for key, value in context.items():
                # Only use json.dumps for complex types (dict, list)
                # For simple types, convert directly to string to avoid extra quotes
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)
                context_args.extend(["--context", f"{key}={value_str}"])

            synth_cmd = ["npx", "cdk", "synth"] + context_args
            log(f"Running: {' '.join(synth_cmd[:4])}... (with context)")

            synth_result = subprocess.run(
                synth_cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=self.cdk_app_dir,
                timeout=120
            )

            if synth_result.returncode != 0:
                log("✗ CDK synth failed")
                log(f"Error: {synth_result.stderr}")
                return (False, {}, log_lines)

            log("✓ CDK synth successful - CloudFormation template generated")

            # CDK deploy
            log("")
            log("=" * 60)
            log("STAGE 2: CDK Deploy (Creating AWS Resources)")
            log("=" * 60)
            log("This may take 5-10 minutes. CDK will:")
            log("  1. Upload assets to S3 (if needed)")
            log("  2. Create/update CloudFormation stack")
            log("  3. Provision EC2 instance and related resources")
            log("  4. Execute user data scripts")
            log("")

            deploy_cmd = [
                "npx", "cdk", "deploy",
                "--require-approval", "never",
                "--outputs-file", f"outputs-{job_id}.json",
                "--progress", "events",  # Show CloudFormation events
                "--verbose"  # Enable verbose output for more feedback
            ] + context_args  # Reuse same context args from synth

            log(f"Running: {' '.join(deploy_cmd[:4])}...")
            log("Initializing CDK deployment...")
            log("")

            import threading
            import time

            # Create process with unbuffered output
            # Use stdbuf to disable buffering if available (Linux/Mac)
            try:
                # Try with stdbuf for better real-time output
                deploy_cmd_unbuffered = ["stdbuf", "-oL", "-eL"] + deploy_cmd
                process = subprocess.Popen(
                    deploy_cmd_unbuffered,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    cwd=self.cdk_app_dir,
                    bufsize=0  # Unbuffered
                )
            except FileNotFoundError:
                # stdbuf not available, use regular command
                process = subprocess.Popen(
                    deploy_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    cwd=self.cdk_app_dir,
                    bufsize=0  # Unbuffered
                )

            # Track if we've seen any output
            last_output_time = [time.time()]  # Use list to allow modification in thread

            # Progress indicator thread
            def progress_indicator():
                dots = 0
                messages = [
                    "CDK is analyzing your infrastructure...",
                    "CDK is preparing CloudFormation template...",
                    "CDK is uploading assets to S3...",
                    "CDK is creating CloudFormation stack...",
                    "Waiting for CloudFormation to provision resources...",
                    "CloudFormation is creating VPC and networking...",
                    "CloudFormation is creating EC2 instance...",
                    "Still waiting for CloudFormation (this can take 5-10 minutes)...",
                ]
                message_idx = 0

                while process.poll() is None:
                    current_time = time.time()
                    # If no output for 20 seconds, show progress indicator
                    if current_time - last_output_time[0] > 20:
                        if message_idx < len(messages):
                            log(f"⏳ {messages[message_idx]}")
                            message_idx += 1
                        else:
                            log(f"⏳ Still working... (elapsed: {int(current_time - last_output_time[0])}s)")
                        last_output_time[0] = current_time  # Reset timer after showing message
                    time.sleep(10)

            # Start progress indicator in background
            progress_thread = threading.Thread(target=progress_indicator, daemon=True)
            progress_thread.start()

            # Stream output line by line
            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.rstrip()
                    if line:
                        last_output_time[0] = time.time()  # Update shared time
                        log(line)
            finally:
                process.stdout.close()

            return_code = process.wait(timeout=600)

            if return_code != 0:
                log("")
                log("✗ CDK deploy failed")
                return (False, {}, log_lines)

            log("")
            log("✓ CDK deploy successful - All AWS resources created")

            # Read outputs
            log("")
            log("=" * 60)
            log("STAGE 3: Reading Deployment Outputs")
            log("=" * 60)

            outputs_file = self.cdk_app_dir / f"outputs-{job_id}.json"
            if outputs_file.exists():
                with open(outputs_file) as f:
                    outputs = json.load(f)

                # Extract instance details
                stack_outputs = outputs.get(f"kamiwaza-job-{job_id}", {})

                log("✓ Successfully retrieved deployment outputs:")
                for key, value in stack_outputs.items():
                    log(f"  • {key}: {value}")

                log("")
                log("=" * 60)
                log("DEPLOYMENT COMPLETE")
                log("=" * 60)

                return (True, stack_outputs, log_lines)
            else:
                log("⚠ Warning: Outputs file not found")
                log("Deployment may have succeeded, but outputs couldn't be retrieved")
                return (True, {}, log_lines)

        except subprocess.TimeoutExpired:
            log("")
            log("✗ CDK deployment timed out after 10 minutes")
            log("The deployment may still be running in AWS CloudFormation")
            log("Check the AWS Console for stack status")
            return (False, {}, log_lines)
        except Exception as e:
            log("")
            log(f"✗ Deployment error: {str(e)}")
            log(f"Error type: {type(e).__name__}")
            import traceback
            log("Traceback:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    log(f"  {line}")
            return (False, {}, log_lines)
        finally:
            # Cleanup context file
            if context_file.exists():
                context_file.unlink()

    def destroy_ec2_instance(
        self,
        job_id: int,
        credentials: Dict[str, str],
        callback=None
    ) -> Tuple[bool, List[str]]:
        """Destroy EC2 instance using CDK destroy"""
        log_lines = []

        def log(msg: str):
            log_lines.append(msg)
            if callback:
                callback(msg)
            logger.info(msg)

        log("=" * 60)
        log(f"DESTROYING CDK STACK FOR JOB {job_id}")
        log("=" * 60)
        log(f"Stack name: kamiwaza-job-{job_id}")
        log(f"Region: {credentials.get('region', 'us-west-2')}")
        log("")

        env = {
            **os.environ,
            'AWS_ACCESS_KEY_ID': credentials['access_key'],
            'AWS_SECRET_ACCESS_KEY': credentials['secret_key'],
            'AWS_DEFAULT_REGION': credentials.get('region', 'us-west-2'),
            'CDK_STACK_NAME': f"kamiwaza-job-{job_id}",
            # Disable CDK version checks and notices to avoid interference
            'CDK_DISABLE_VERSION_CHECK': '1'
        }

        if credentials.get('session_token'):
            env['AWS_SESSION_TOKEN'] = credentials['session_token']

        try:
            destroy_cmd = [
                "npx", "cdk", "destroy",
                f"kamiwaza-job-{job_id}",
                "--force",
                "--no-version-reporting"  # Disable version reporting
            ]

            log(f"Running: {' '.join(destroy_cmd)}")
            log("")

            # Use Popen to stream output in real-time
            process = subprocess.Popen(
                destroy_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                env=env,
                cwd=self.cdk_app_dir,
                bufsize=1  # Line buffered
            )

            # Stream output line by line
            for line in iter(process.stdout.readline, ''):
                if line:
                    line = line.rstrip()
                    if line:
                        log(line)

            process.stdout.close()
            return_code = process.wait(timeout=300)

            log("")
            if return_code == 0:
                log("=" * 60)
                log("✓ STACK DESTROYED SUCCESSFULLY")
                log("=" * 60)
                return (True, log_lines)
            else:
                log("=" * 60)
                log(f"✗ DESTROY FAILED (exit code: {return_code})")
                log("=" * 60)
                return (False, log_lines)

        except subprocess.TimeoutExpired:
            log("")
            log("=" * 60)
            log("✗ DESTROY TIMED OUT AFTER 5 MINUTES")
            log("=" * 60)
            log("The stack deletion may still be in progress in AWS CloudFormation.")
            log("Check the AWS Console for the actual stack status.")
            return (False, log_lines)
        except Exception as e:
            log("")
            log("=" * 60)
            log(f"✗ DESTROY ERROR: {str(e)}")
            log("=" * 60)
            import traceback
            log("Traceback:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    log(f"  {line}")
            return (False, log_lines)
