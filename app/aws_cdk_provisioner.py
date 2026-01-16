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

        logger.info(f"Assuming role: {role_arn}")

        try:
            sts_client = boto3.client('sts', region_name=region)

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

        log(f"Starting CDK deployment for job {job_id}")

        # Generate CDK context
        context = {
            'jobId': job_id,
            'instanceType': instance_config.get('instance_type', 't3.medium'),
            'region': credentials.get('region', 'us-west-2')
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

        try:
            # CDK synth
            log("Running CDK synth...")
            synth_cmd = ["npx", "cdk", "synth", "--context", f"@{context_file}"]
            synth_result = subprocess.run(
                synth_cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=self.cdk_app_dir,
                timeout=120
            )

            if synth_result.returncode != 0:
                log(f"CDK synth failed: {synth_result.stderr}")
                return (False, {}, log_lines)

            log("✓ CDK synth successful")

            # CDK deploy
            log("Running CDK deploy...")
            deploy_cmd = [
                "npx", "cdk", "deploy",
                "--context", f"@{context_file}",
                "--require-approval", "never",
                "--outputs-file", f"outputs-{job_id}.json"
            ]

            deploy_result = subprocess.run(
                deploy_cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=self.cdk_app_dir,
                timeout=600
            )

            # Stream output
            for line in deploy_result.stdout.split('\n'):
                if line.strip():
                    log(line)

            if deploy_result.returncode != 0:
                log(f"CDK deploy failed: {deploy_result.stderr}")
                return (False, {}, log_lines)

            log("✓ CDK deploy successful")

            # Read outputs
            outputs_file = self.cdk_app_dir / f"outputs-{job_id}.json"
            if outputs_file.exists():
                with open(outputs_file) as f:
                    outputs = json.load(f)

                # Extract instance details
                stack_outputs = outputs.get(f"kamiwaza-job-{job_id}", {})

                return (True, stack_outputs, log_lines)
            else:
                log("Warning: Outputs file not found")
                return (True, {}, log_lines)

        except Exception as e:
            log(f"Deployment error: {str(e)}")
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

        log(f"Destroying CDK stack for job {job_id}")

        env = {
            **os.environ,
            'AWS_ACCESS_KEY_ID': credentials['access_key'],
            'AWS_SECRET_ACCESS_KEY': credentials['secret_key'],
            'AWS_DEFAULT_REGION': credentials.get('region', 'us-west-2'),
            'CDK_STACK_NAME': f"kamiwaza-job-{job_id}"
        }

        if credentials.get('session_token'):
            env['AWS_SESSION_TOKEN'] = credentials['session_token']

        try:
            destroy_cmd = [
                "npx", "cdk", "destroy",
                f"kamiwaza-job-{job_id}",
                "--force"
            ]

            destroy_result = subprocess.run(
                destroy_cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=self.cdk_app_dir,
                timeout=300
            )

            for line in destroy_result.stdout.split('\n'):
                if line.strip():
                    log(line)

            if destroy_result.returncode == 0:
                log("✓ Stack destroyed successfully")
                return (True, log_lines)
            else:
                log(f"Destroy failed: {destroy_result.stderr}")
                return (False, log_lines)

        except Exception as e:
            log(f"Destroy error: {str(e)}")
            return (False, log_lines)
