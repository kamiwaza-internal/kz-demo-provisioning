import os
import json
import base64
from datetime import datetime
from pathlib import Path
from typing import Dict

import boto3
from botocore.exceptions import ClientError

from worker.celery_app import celery_app
from app.database import SessionLocal
from app.models import Job, JobLog
from app.aws_handler import AWSHandler, AWSAuthError
from app.terraform_runner import TerraformRunner, TerraformError
from app.aws_cdk_provisioner import AWSCDKProvisioner
from app.email_service import EmailService
from app.csv_handler import CSVHandler
from app.config import settings

import logging

logger = logging.getLogger(__name__)


def vpc_exists(vpc_id: str, region: str, credentials: Dict) -> bool:
    """
    Check if a VPC exists in AWS.

    Args:
        vpc_id: The VPC ID to check
        region: AWS region
        credentials: Dict with 'access_key', 'secret_key', and optional 'session_token'

    Returns:
        True if VPC exists, False otherwise
    """
    try:
        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
        return len(response.get('Vpcs', [])) > 0
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidVpcID.NotFound':
            return False
        # For other errors, log but assume VPC doesn't exist
        logger.warning(f"Error checking VPC {vpc_id}: {str(e)}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error checking VPC {vpc_id}: {str(e)}")
        return False


@celery_app.task(bind=True, name='worker.tasks.execute_provisioning_job')
def execute_provisioning_job(self, job_id: int):
    """
    Execute a provisioning job: authenticate AWS, run Terraform or CDK, send email.
    """
    db = SessionLocal()

    try:
        # Get job from database
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # Update job status
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        def log_message(level: str, message: str, source: str = "worker"):
            """Helper to log messages to database"""
            log = JobLog(
                job_id=job.id,
                level=level,
                message=message,
                source=source
            )
            db.add(log)
            db.commit()
            logger.log(getattr(logging, level.upper()), f"Job {job_id}: {message}")

        log_message("info", "Job execution started")

        # Check provisioning method
        provisioning_method = os.environ.get("AWS_PROVISIONING_METHOD", "terraform")
        log_message("info", f"Provisioning method: {provisioning_method}")

        if provisioning_method == "cdk":
            # Use AWS CDK provisioning
            execute_cdk_provisioning(job, db, log_message)
        else:
            # Use Terraform provisioning (legacy)
            execute_terraform_provisioning(job, db, log_message)

    except Exception as e:
        # Mark job as failed
        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()

        log_message("error", f"Job failed: {str(e)}")

        # Send failure email
        send_completion_email(job, db)

    finally:
        db.close()


def execute_cdk_provisioning(job: Job, db, log_message):
    """Execute provisioning using AWS CDK"""
    log_message("info", "Using AWS CDK for provisioning")

    # Initialize CDK provisioner
    provisioner = AWSCDKProvisioner()

    # Step 1: Get AWS credentials
    log_message("info", "Getting AWS credentials...")

    auth_method = os.environ.get("AWS_AUTH_METHOD", "access_keys")
    credentials = None

    try:
        if auth_method == "assume_role":
            role_arn = os.environ.get("AWS_ASSUME_ROLE_ARN")
            external_id = os.environ.get("AWS_EXTERNAL_ID")
            session_name = os.environ.get("AWS_SESSION_NAME", "kamiwaza-provisioner")

            if not role_arn:
                raise Exception("AWS_ASSUME_ROLE_ARN not configured")

            log_message("info", f"Assuming role: {role_arn}")
            credentials = provisioner.assume_role(
                role_arn=role_arn,
                session_name=session_name,
                external_id=external_id,
                region=job.aws_region
            )
            log_message("info", f"✓ Assumed role successfully (expires: {credentials['expiration']})")

        elif auth_method == "access_keys":
            access_key = os.environ.get("AWS_ACCESS_KEY_ID")
            secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

            if not access_key or not secret_key:
                raise Exception("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY not configured")

            credentials = {
                'access_key': access_key,
                'secret_key': secret_key,
                'region': job.aws_region
            }
            log_message("info", "✓ Using access key credentials")

        else:
            raise Exception(f"Unsupported auth method: {auth_method}")

        # Get caller identity
        identity = provisioner.get_caller_identity(credentials)
        job.aws_account_id = identity['account_id']
        db.commit()
        log_message("info", f"✓ Authenticated as: {identity['arn']}")

    except Exception as e:
        log_message("error", f"AWS authentication failed: {str(e)}")
        raise

    # Step 2: Prepare instance configuration
    log_message("info", "Preparing instance configuration...")

    # Auto-reuse VPC from most recent successful deployment if not specified
    if not job.vpc_id:
        recent_job = db.query(Job).filter(
            Job.status == 'success',
            Job.aws_region == job.aws_region,
            Job.terraform_outputs.isnot(None)
        ).order_by(Job.completed_at.desc()).first()

        if recent_job and recent_job.terraform_outputs:
            reused_vpc_id = recent_job.terraform_outputs.get('VpcId')
            if reused_vpc_id:
                # Verify VPC still exists before reusing
                if vpc_exists(reused_vpc_id, job.aws_region, credentials):
                    job.vpc_id = reused_vpc_id
                    db.commit()
                    log_message("info", f"♻️  Reusing VPC from job #{recent_job.id}: {reused_vpc_id}")
                else:
                    log_message("warning", f"⚠️  VPC {reused_vpc_id} from job #{recent_job.id} no longer exists, will create new VPC")

    # Auto-select cached AMI if requested
    ami_id_to_use = job.ami_id
    if job.use_cached_ami and not job.ami_id and job.deployment_type == "kamiwaza":
        log_message("info", "Searching for cached Kamiwaza AMI...")
        version = job.kamiwaza_branch or "release/0.9.2"
        cached_ami_id = check_ami_exists_for_version(version, job.aws_region, credentials)
        if cached_ami_id:
            ami_id_to_use = cached_ami_id
            log_message("info", f"✓ Found cached AMI: {cached_ami_id} for version {version}")
            # Update job with the selected AMI
            job.ami_id = cached_ami_id
            db.commit()
        else:
            log_message("warning", f"⚠️  No cached AMI found for version {version}, will use default AMI and full installation")

    # Generate user data script
    user_data_script = generate_user_data_script(job, db)
    user_data_b64 = base64.b64encode(user_data_script.encode()).decode()

    instance_config = {
        'instance_type': job.instance_type,
        'ami_id': ami_id_to_use,
        'vpc_id': job.vpc_id,
        'subnet_id': job.subnet_id,
        'security_group_ids': job.security_group_ids,
        'key_pair_name': job.key_pair_name,
        'user_data': user_data_b64,
        'tags': job.tags or {}
    }

    # Add job-specific tags
    instance_config['tags'].update({
        'Name': job.job_name,
        'JobId': str(job.id),
        'ManagedBy': 'KamiwazaDeploymentManager'
    })

    # Step 3: Deploy EC2 instance with CDK
    log_message("info", "Deploying EC2 instance with AWS CDK...")

    success, outputs, log_lines = provisioner.deploy_ec2_instance(
        job_id=job.id,
        credentials=credentials,
        instance_config=instance_config,
        callback=lambda line: log_message("info", line)
    )

    if success:
        # Extract outputs
        job.instance_id = outputs.get('InstanceId')
        job.public_ip = outputs.get('PublicIP')
        job.private_ip = outputs.get('PrivateIP')
        job.terraform_outputs = outputs  # Store all outputs
        job.status = "success"
        job.completed_at = datetime.utcnow()
        db.commit()

        log_message("info", "✓ CDK deployment completed successfully")
        if job.instance_id:
            log_message("info", f"Instance ID: {job.instance_id}")
        if job.public_ip:
            log_message("info", f"Public IP: {job.public_ip}")
        if job.private_ip:
            log_message("info", f"Private IP: {job.private_ip}")

        # Send success email
        send_completion_email(job, db)

        # For Kamiwaza deployments, start log streaming and readiness check
        if job.deployment_type == "kamiwaza":
            log_message("info", "Starting Kamiwaza log streaming...")
            # Start streaming logs immediately (iteration 0)
            stream_kamiwaza_logs.apply_async(args=[job.id, job.instance_id, job.aws_region, 0], countdown=30)

            log_message("info", "Starting Kamiwaza readiness checks (will begin in 3 minutes)...")
            # Schedule first check in 3 minutes to give Kamiwaza time to start
            # The deployment script already waits ~5 minutes for services to initialize
            # But HTTPS endpoint may take additional time to become accessible
            check_kamiwaza_readiness.apply_async(args=[job.id], countdown=180)

    else:
        raise Exception("CDK deployment failed - see logs for details")


def execute_terraform_provisioning(job: Job, db, log_message):
    """Execute provisioning using Terraform (legacy)"""
    log_message("info", "Using Terraform for provisioning (legacy mode)")

    # Step 1: Authenticate with AWS
    log_message("info", "Authenticating with AWS...")

    try:
        if job.aws_auth_method == "assume_role":
            credentials = AWSHandler.assume_role(
                role_arn=job.assume_role_arn,
                session_name=job.session_name or "terraform-provisioning",
                external_id=job.external_id,
                region=job.aws_region
            )
            log_message("info", f"Successfully assumed role: {job.assume_role_arn}")
        else:
            # Note: access_key/secret_key should be passed securely and not stored in DB
            log_message("error", "Access key authentication not fully implemented in worker")
            raise AWSAuthError("Access key auth requires credentials to be passed securely")

        # Get caller identity
        account_id, arn, user_id = AWSHandler.get_caller_identity(credentials)
        job.aws_account_id = account_id
        db.commit()
        log_message("info", f"Authenticated as: {arn} (Account: {account_id})")

    except AWSAuthError as e:
        log_message("error", f"AWS authentication failed: {str(e)}")
        raise

    # Step 2: Prepare Terraform workspace
    log_message("info", "Preparing Terraform workspace...")

    tf_runner = TerraformRunner(
        job_id=job.id,
        log_callback=lambda level, msg: log_message(level, msg, source="terraform")
    )

    try:
        terraform_source = Path(__file__).parent.parent / "terraform"
        tf_runner.prepare_workspace(str(terraform_source))
    except TerraformError as e:
        log_message("error", f"Failed to prepare workspace: {str(e)}")
        raise

    # Step 3: Prepare Terraform variables
    log_message("info", "Preparing Terraform variables...")

    # Generate user_data script
    user_data_script = generate_user_data_script(job, db)

    tf_vars = {
        "aws_region": job.aws_region,
        "instance_type": job.instance_type,
        "volume_size": job.volume_size_gb,
        "job_name": job.job_name,
        "user_data": user_data_script,
    }

    if job.ami_id:
        tf_vars["ami_id"] = job.ami_id

    if job.vpc_id:
        tf_vars["vpc_id"] = job.vpc_id

    if job.subnet_id:
        tf_vars["subnet_id"] = job.subnet_id

    if job.security_group_ids:
        tf_vars["security_group_ids"] = job.security_group_ids

    if job.key_pair_name:
        tf_vars["key_pair_name"] = job.key_pair_name

    if job.tags:
        tf_vars["tags"] = job.tags

    # Write tfvars
    tf_runner.write_tfvars(tf_vars)

    # Step 4: Set up AWS environment variables for Terraform
    tf_env = {
        "AWS_ACCESS_KEY_ID": credentials["access_key"],
        "AWS_SECRET_ACCESS_KEY": credentials["secret_key"],
        "AWS_DEFAULT_REGION": credentials["region"],
    }

    if credentials.get("session_token"):
        tf_env["AWS_SESSION_TOKEN"] = credentials["session_token"]

    # Step 5: Run Terraform
    try:
        log_message("info", "Running Terraform init...")
        tf_runner.init(tf_env)

        log_message("info", "Running Terraform validate...")
        tf_runner.validate(tf_env)

        log_message("info", "Running Terraform apply...")
        tf_runner.apply(tf_env)

        log_message("info", "Retrieving Terraform outputs...")
        outputs = tf_runner.get_outputs(tf_env)

        # Save outputs
        job.instance_id = outputs.get("instance_id")
        job.public_ip = outputs.get("public_ip")
        job.private_ip = outputs.get("private_ip")
        job.terraform_outputs = outputs
        db.commit()

        log_message("info", f"Instance provisioned: {job.instance_id}")
        if job.public_ip:
            log_message("info", f"Public IP: {job.public_ip}")
        if job.private_ip:
            log_message("info", f"Private IP: {job.private_ip}")

    except TerraformError as e:
        log_message("error", f"Terraform execution failed: {str(e)}")
        raise

    # Step 6: Mark job as success
    job.status = "success"
    job.completed_at = datetime.utcnow()
    db.commit()

    log_message("info", "Job completed successfully")

    # Step 7: Send email notification
    send_completion_email(job, db)


def generate_user_data_script(job: Job, db) -> str:
    """Generate user_data script for EC2 instance"""

    # Check deployment type
    if job.deployment_type == "kamiwaza":
        return generate_kamiwaza_user_data(job, db)
    else:
        return generate_docker_user_data(job, db)


def generate_kamiwaza_user_data(job: Job, db) -> str:
    """Generate user_data script for Kamiwaza full stack deployment (RHEL 9 RPM)"""

    # Read the deployment script - using RPM-based installation for RHEL 9
    script_path = Path(__file__).parent.parent / "scripts" / "deploy_kamiwaza_full.sh"
    if not script_path.exists():
        raise Exception(f"Kamiwaza deployment script not found at {script_path}")

    deployment_script = script_path.read_text()

    # Get RPM package URL - check job tags first, then fall back to environment
    package_url = None
    if job.tags and isinstance(job.tags, dict):
        package_url = job.tags.get("PackageURL")

    if not package_url:
        package_url = os.environ.get("KAMIWAZA_PACKAGE_URL", "https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/rpm/rhel9/x86_64/kamiwaza_v0.9.2_rhel9_x86_64-online_rc18.rpm")

    # Get deployment mode from job (defaults to 'full' for backward compatibility)
    deployment_mode = getattr(job, 'kamiwaza_deployment_mode', 'full') or 'full'

    # Build user data with environment variables for RHEL 9
    user_data_lines = [
        "#!/bin/bash",
        "",
        "# Kamiwaza Deployment Configuration (RPM-based Installation for RHEL 9)",
        f"export KAMIWAZA_PACKAGE_URL='{package_url}'",
        f"export KAMIWAZA_DEPLOYMENT_MODE='{deployment_mode}'",
    ]

    # Add API keys from settings (if configured)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    n2yo_key = os.environ.get("N2YO_API_KEY", "")
    datalastic_key = os.environ.get("DATALASTIC_API_KEY", "")
    flightradar24_key = os.environ.get("FLIGHTRADAR24_API_KEY", "")

    if anthropic_key:
        user_data_lines.append(f"export ANTHROPIC_API_KEY='{anthropic_key}'")
    if n2yo_key:
        user_data_lines.append(f"export N2YO_API_KEY='{n2yo_key}'")
    if datalastic_key:
        user_data_lines.append(f"export DATALASTIC_API_KEY='{datalastic_key}'")
    if flightradar24_key:
        user_data_lines.append(f"export FLIGHTRADAR24_API_KEY='{flightradar24_key}'")

    user_data_lines.extend([
        "export KAMIWAZA_ROOT='/opt/kamiwaza'",
        "export KAMIWAZA_USER='ec2-user'",  # RHEL 9 uses ec2-user
        "",
        deployment_script
    ])

    return "\n".join(user_data_lines)


def generate_docker_user_data(job: Job, db) -> str:
    """Generate user_data script for custom Docker deployments"""

    # Prepare users CSV content
    users_csv_content = ""
    if job.users_data:
        users_csv_content = CSVHandler.to_csv_string(job.users_data)

    # Base64 encode for environment variable
    users_csv_b64 = base64.b64encode(users_csv_content.encode()).decode() if users_csv_content else ""

    # Generate docker-compose.yml content
    compose_services = {}
    for container in job.dockerhub_images:
        service = {
            "image": container["image"],
            "container_name": container["name"],
            "restart": container.get("restart", "unless-stopped"),
        }

        if container.get("ports"):
            service["ports"] = container["ports"]

        if container.get("environment"):
            service["environment"] = container["environment"]

        # Add users data to environment if needed
        if users_csv_b64:
            if "environment" not in service:
                service["environment"] = {}
            service["environment"]["APP_USERS_B64"] = users_csv_b64

        if container.get("volumes"):
            service["volumes"] = container["volumes"]

        if container.get("command"):
            service["command"] = container["command"]

        compose_services[container["name"]] = service

    compose_content = {
        "version": "3.8",
        "services": compose_services
    }

    # Build user_data script
    user_data_lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# Update and install Docker",
        "yum update -y",
        "yum install -y docker",
        "systemctl start docker",
        "systemctl enable docker",
        "",
        "# Install docker-compose",
        "curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose",
        "chmod +x /usr/local/bin/docker-compose",
        "",
        "# Create app directory",
        "mkdir -p /opt/app",
        "",
    ]

    # Write users CSV if present
    if users_csv_content:
        # Escape single quotes in CSV content
        csv_escaped = users_csv_content.replace("'", "'\\''")
        user_data_lines.extend([
            "# Write users CSV",
            f"cat > /opt/app/users.csv << 'EOF'",
            users_csv_content,
            "EOF",
            "",
        ])

    # Write docker-compose.yml
    compose_json = json.dumps(compose_content, indent=2)
    user_data_lines.extend([
        "# Write docker-compose.yml",
        f"cat > /opt/app/docker-compose.yml << 'EOF'",
        compose_json,
        "EOF",
        "",
        "# Start containers",
        "cd /opt/app",
        "docker-compose up -d",
        "",
        "# Log completion",
        "echo 'Provisioning complete' > /opt/app/provisioning.log",
    ])

    return "\n".join(user_data_lines)


def send_completion_email(job: Job, db):
    """Send completion email for job"""

    # Get recent logs
    logs = db.query(JobLog).filter(JobLog.job_id == job.id).order_by(JobLog.timestamp.desc()).limit(20).all()
    log_excerpt = "\n".join([
        f"[{log.timestamp.strftime('%H:%M:%S')}] [{log.level}] {log.message}"
        for log in reversed(logs)
    ])

    # Extract exposed ports
    exposed_ports = []
    for container in job.dockerhub_images:
        if container.get("ports"):
            exposed_ports.extend(container["ports"])

    # Send email
    success = EmailService.send_job_notification(
        recipient_email=job.requester_email,
        job_name=job.job_name,
        job_id=job.id,
        status=job.status,
        deployment_type=job.deployment_type or "docker",
        instance_id=job.instance_id,
        public_ip=job.public_ip,
        private_ip=job.private_ip,
        aws_region=job.aws_region,
        aws_account_id=job.aws_account_id,
        role_arn=job.assume_role_arn,
        exposed_ports=exposed_ports,
        error_message=job.error_message,
        log_excerpt=log_excerpt[:500],  # First 500 chars
        web_ui_url="http://localhost:8000"  # TODO: Make this configurable
    )

    job.email_sent = success
    if success:
        job.email_sent_at = datetime.utcnow()

    db.commit()


# ============================================================================
# KAMIWAZA PROVISIONING TASK (for Deployment Manager)
# ============================================================================

@celery_app.task(bind=True, name='worker.tasks.execute_kamiwaza_provisioning')
def execute_kamiwaza_provisioning(self, job_id: int):
    """
    Execute Kamiwaza user provisioning: create users and deploy Kaizen instances.
    """
    db = SessionLocal()

    try:
        from app.kamiwaza_provisioner import KamiwazaProvisioner
        from app.models import JobFile

        # Get job from database
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Provisioning job {job_id} not found")
            return

        # Update job status
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        def log_message(level: str, message: str):
            """Helper to log messages to database"""
            log = JobLog(
                job_id=job.id,
                level=level,
                message=message,
                source="kamiwaza-provisioner"
            )
            db.add(log)
            db.commit()
            logger.log(getattr(logging, level.upper()), f"Provisioning job {job_id}: {message}")

        log_message("info", "Kamiwaza provisioning started")

        # Get CSV file
        if not job.csv_file_id:
            log_message("error", "No CSV file attached to job")
            raise Exception("No CSV file attached to job")

        job_file = db.query(JobFile).filter(JobFile.id == job.csv_file_id).first()
        if not job_file:
            log_message("error", "CSV file not found in database")
            raise Exception("CSV file not found")

        # Read CSV content
        csv_path = Path(job_file.file_path)
        if not csv_path.exists():
            log_message("error", f"CSV file not found at: {csv_path}")
            raise Exception(f"CSV file not found at: {csv_path}")

        with open(csv_path, 'rb') as f:
            csv_content = f.read()

        log_message("info", f"Loaded CSV file: {job_file.filename}")

        # Override Kamiwaza URL if specified in job
        original_kamiwaza_url = os.environ.get("KAMIWAZA_URL")
        if job.kamiwaza_repo:  # URL is stored in kamiwaza_repo field
            os.environ["KAMIWAZA_URL"] = job.kamiwaza_repo
            log_message("info", f"Target Kamiwaza instance: {job.kamiwaza_repo}")

        try:
            # Initialize provisioner (will read KAMIWAZA_URL from environment)
            provisioner = KamiwazaProvisioner()

            # Run provisioning with live callback
            success, summary, log_lines = provisioner.run_provisioning(
                csv_content=csv_content,
                callback=lambda line: log_message("info", line)
            )
        finally:
            # Restore original URL after provisioning
            if original_kamiwaza_url:
                os.environ["KAMIWAZA_URL"] = original_kamiwaza_url
            elif job.kamiwaza_repo:
                # Only delete if we set it and there was no original
                if "KAMIWAZA_URL" in os.environ:
                    del os.environ["KAMIWAZA_URL"]

        # Update job status
        if success:
            # User provisioning succeeded, now hydrate apps and tools
            log_message("info", "✓ User provisioning completed successfully")
            log_message("info", "")
            log_message("info", "Starting app and tool hydration...")

            try:
                from app.kamiwaza_app_hydrator import KamiwazaAppHydrator

                # Override Kamiwaza URL for hydrator as well
                if job.kamiwaza_repo:
                    os.environ["KAMIWAZA_URL"] = job.kamiwaza_repo

                hydrator = KamiwazaAppHydrator()

                # Restore original URL
                if original_kamiwaza_url:
                    os.environ["KAMIWAZA_URL"] = original_kamiwaza_url
                elif job.kamiwaza_repo:
                    del os.environ["KAMIWAZA_URL"]

                # Get selected apps from job configuration
                selected_apps = job.selected_apps if hasattr(job, 'selected_apps') and job.selected_apps else None

                hydration_success, hydration_summary, hydration_logs = hydrator.hydrate_apps_and_tools(
                    callback=lambda line: log_message("info", line),
                    selected_apps=selected_apps
                )

                if hydration_success:
                    log_message("info", "✓ App hydration completed successfully")
                else:
                    log_message("warning", f"⚠ App hydration failed: {hydration_summary}")
                    log_message("warning", "User provisioning succeeded but app hydration failed")

                # Deploy tools from toolshed if selected
                selected_tools = job.selected_tools if hasattr(job, 'selected_tools') and job.selected_tools else None
                if selected_tools and len(selected_tools) > 0:
                    log_message("info", "")
                    log_message("info", "Starting tool deployment from toolshed...")

                    try:
                        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner
                        from app.config import settings

                        # Override Kamiwaza URL for tools provisioner
                        provisioner_url = job.kamiwaza_repo if job.kamiwaza_repo else f"https://{job.public_ip}"

                        tools_provisioner = KamiwazaToolsProvisioner(
                            kamiwaza_url=provisioner_url,
                            username=os.environ.get("KAMIWAZA_USERNAME", "admin"),
                            password=os.environ.get("KAMIWAZA_PASSWORD", "kamiwaza"),
                            toolshed_stage=settings.toolshed_stage
                        )

                        tools_success, tools_summary, tools_logs = tools_provisioner.provision_tools(
                            callback=lambda line: log_message("info", line),
                            selected_tools=selected_tools,
                            sync_first=True
                        )

                        if tools_success:
                            log_message("info", "✓ Tool deployment completed successfully")
                            # Update tool deployment status
                            if not job.tool_deployment_status:
                                job.tool_deployment_status = {}
                            for tool_name in selected_tools:
                                job.tool_deployment_status[tool_name] = "success"
                        else:
                            log_message("warning", f"⚠ Tool deployment failed: {tools_summary}")
                            # Mark failed tools
                            if not job.tool_deployment_status:
                                job.tool_deployment_status = {}
                            for tool_name in selected_tools:
                                if tool_name not in job.tool_deployment_status:
                                    job.tool_deployment_status[tool_name] = "failed"

                    except Exception as tool_error:
                        log_message("error", f"✗ Tool deployment error: {str(tool_error)}")
                        log_message("warning", "User provisioning succeeded but tool deployment encountered an error")
                        # Mark all tools as failed
                        if not job.tool_deployment_status:
                            job.tool_deployment_status = {}
                        for tool_name in selected_tools:
                            job.tool_deployment_status[tool_name] = "failed"

                # Import custom MCP tools from GitHub if provided
                custom_mcp_urls = job.custom_mcp_github_urls if hasattr(job, 'custom_mcp_github_urls') and job.custom_mcp_github_urls else None
                if custom_mcp_urls and len(custom_mcp_urls) > 0:
                    log_message("info", "")
                    log_message("info", f"Starting custom MCP import from GitHub ({len(custom_mcp_urls)} tools)...")

                    try:
                        from app.mcp_github_importer import MCPGitHubImporter
                        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner
                        from app.config import settings

                        provisioner_url = job.kamiwaza_repo if job.kamiwaza_repo else f"https://{job.public_ip}"

                        # Authenticate with Kamiwaza
                        tools_provisioner = KamiwazaToolsProvisioner(
                            kamiwaza_url=provisioner_url,
                            username=os.environ.get("KAMIWAZA_USERNAME", "admin"),
                            password=os.environ.get("KAMIWAZA_PASSWORD", "kamiwaza"),
                            toolshed_stage=settings.toolshed_stage
                        )

                        auth_success, token, auth_error = tools_provisioner.authenticate()
                        if not auth_success:
                            log_message("error", f"✗ Authentication failed for MCP import: {auth_error}")
                        else:
                            # Create importer
                            importer = MCPGitHubImporter()

                            for github_url in custom_mcp_urls:
                                log_message("info", f"  • Importing MCP from: {github_url}")

                                # Validate
                                validate_success, tool_config, validation_logs = importer.validate_mcp_repo(github_url)

                                if not validate_success:
                                    log_message("warning", f"    ✗ Validation failed for {github_url}")
                                    for log_line in validation_logs[-5:]:  # Show last 5 lines
                                        log_message("warning", f"      {log_line}")
                                    continue

                                # Import to Kamiwaza
                                import_success, import_msg = importer.import_to_kamiwaza(
                                    provisioner_url,
                                    token,
                                    tool_config,
                                    github_url
                                )

                                if import_success:
                                    log_message("info", f"    ✓ {import_msg}")
                                else:
                                    log_message("warning", f"    ✗ {import_msg}")

                    except Exception as mcp_error:
                        log_message("error", f"✗ Custom MCP import error: {str(mcp_error)}")
                        log_message("warning", "User provisioning succeeded but custom MCP import encountered an error")

                # Mark job as complete
                job.status = "success"
                job.completed_at = datetime.utcnow()

            except Exception as hydration_error:
                log_message("error", f"✗ App/tool deployment error: {str(hydration_error)}")
                log_message("warning", "User provisioning succeeded but app/tool deployment encountered an error")
                job.status = "success"  # Still mark as success since users were created
                job.completed_at = datetime.utcnow()
        else:
            job.status = "failed"
            job.error_message = summary
            job.completed_at = datetime.utcnow()
            log_message("error", f"✗ Provisioning failed: {summary}")

        db.commit()

    except Exception as e:
        # Mark job as failed
        logger.error(f"Provisioning job {job_id} failed: {str(e)}", exc_info=True)

        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()

        log_message("error", f"✗ Provisioning error: {str(e)}")

    finally:
        db.close()


# ============================================================================
# KAMIWAZA LOG STREAMING TASK
# ============================================================================

@celery_app.task(bind=True, name='worker.tasks.stream_kamiwaza_logs')
def stream_kamiwaza_logs(self, job_id: int, instance_id: str, region: str, iteration: int = 0):
    """
    Stream Kamiwaza deployment and startup logs from EC2 instance using SSM.
    This task streams logs in real-time and reschedules itself until deployment is complete.
    """
    import time
    import hashlib

    db = SessionLocal()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found for log streaming")
            return

        # Stop streaming if Kamiwaza is ready
        if job.kamiwaza_ready:
            logger.info(f"Job {job_id} Kamiwaza is ready, stopping log stream")
            return

        def log_message(level: str, message: str):
            """Helper to log messages"""
            log = JobLog(
                job_id=job.id,
                level=level,
                message=message,
                source="kamiwaza-logs"
            )
            db.add(log)
            db.commit()

        # Get AWS credentials
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        provisioner = AWSCDKProvisioner()

        auth_method = os.environ.get("AWS_AUTH_METHOD", "access_keys")
        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = os.environ.get("AWS_ASSUME_ROLE_ARN")
                external_id = os.environ.get("AWS_EXTERNAL_ID")
                session_name = os.environ.get("AWS_SESSION_NAME", "kamiwaza-provisioner")

                if not role_arn:
                    raise Exception("AWS_ASSUME_ROLE_ARN not configured")

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=region
                )
            elif auth_method == "access_keys":
                access_key = os.environ.get("AWS_ACCESS_KEY_ID")
                secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

                if not access_key or not secret_key:
                    raise Exception("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY not configured")

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': region
                }
        except Exception as e:
            logger.error(f"Failed to get AWS credentials for log streaming: {str(e)}")
            return

        # Create SSM client
        ssm_client = boto3.client(
            'ssm',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Check if this is the first run
        if iteration == 0:
            log_message("info", "")
            log_message("info", "=" * 60)
            log_message("info", "KAMIWAZA INSTALLATION LOGS (Real-time Stream)")
            log_message("info", "=" * 60)
            log_message("info", "Waiting for instance to become available...")
            time.sleep(5)  # Give instance time to start

        # Create marker file to track what we've already logged
        marker_file = f"/tmp/kamiwaza-log-marker-{job_id}"

        # Send command to get new logs since last check
        command = f"""
# Initialize line counter file if it doesn't exist
if [ ! -f {marker_file} ]; then
    echo "0" > {marker_file}
fi

LAST_LINE=$(cat {marker_file})

# Get deployment log (only new lines)
if [ -f /var/log/kamiwaza-deployment.log ]; then
    LINE_COUNT=$(wc -l < /var/log/kamiwaza-deployment.log 2>/dev/null || echo "0")
    if [ "$LINE_COUNT" -gt "$LAST_LINE" ]; then
        tail -n +$((LAST_LINE + 1)) /var/log/kamiwaza-deployment.log 2>/dev/null || true
        echo "$LINE_COUNT" > {marker_file}
    fi
fi

# Also show last 5 lines of startup log for status updates
if [ -f /var/log/kamiwaza-startup.log ]; then
    echo ""
    echo "--- Latest from startup log ---"
    tail -n 5 /var/log/kamiwaza-startup.log 2>/dev/null || true
fi

# Show kamiwaza status every 10 iterations (5 minutes)
if [ $((iteration % 10)) -eq 0 ] && command -v kamiwaza &> /dev/null; then
    echo ""
    echo "--- Kamiwaza Status ---"
    sudo -u ubuntu kamiwaza status 2>/dev/null || echo "Status not available yet"
fi
"""

        try:
            response = ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={'commands': [command.replace('iteration', str(iteration))]},
                TimeoutSeconds=30
            )

            command_id = response['Command']['CommandId']

            # Wait for command to complete
            max_wait = 20
            waited = 0
            output = None

            while waited < max_wait:
                time.sleep(2)
                waited += 2

                try:
                    output = ssm_client.get_command_invocation(
                        CommandId=command_id,
                        InstanceId=instance_id
                    )

                    if output['Status'] in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                        break
                except ssm_client.exceptions.InvocationDoesNotExist:
                    continue

            # Get the output
            if output and output['Status'] == 'Success':
                log_content = output.get('StandardOutputContent', '')

                if log_content.strip():
                    # Split into lines and log each
                    lines = log_content.strip().split('\n')

                    for line in lines:
                        if line.strip():
                            log_message("info", line.strip())

            # Check for errors
            if output and output.get('StandardErrorContent'):
                error_content = output['StandardErrorContent'].strip()
                if error_content and 'No such file' not in error_content:
                    if iteration == 0:
                        log_message("info", "Waiting for Kamiwaza installation to begin...")

        except ssm_client.exceptions.InvalidInstanceId:
            if iteration == 0:
                log_message("info", "Waiting for SSM agent to become available...")
        except ClientError as e:
            if 'TargetNotConnected' in str(e):
                if iteration == 0:
                    log_message("info", "Instance is starting up, SSM agent not yet available...")
            else:
                logger.warning(f"SSM error for job {job_id}: {str(e)}")
        except Exception as e:
            # Only log if it's not a common "not ready yet" error
            if 'TargetNotConnected' not in str(e) and 'InvalidInstanceId' not in str(e):
                logger.warning(f"Error streaming logs for job {job_id}: {str(e)}")

        # Schedule next log fetch (every 30 seconds) if not ready yet
        if not job.kamiwaza_ready:
            # Continue streaming for up to 40 minutes (80 iterations * 30 seconds)
            MAX_ITERATIONS = 80
            if iteration < MAX_ITERATIONS:
                stream_kamiwaza_logs.apply_async(
                    args=[job_id, instance_id, region, iteration + 1],
                    countdown=30
                )
            else:
                log_message("info", "")
                log_message("info", "Log streaming stopped (timeout reached after 40 minutes)")
                log_message("info", "Kamiwaza may still be installing. Check the readiness status or connect to the instance directly.")

    except Exception as e:
        logger.error(f"Critical error in log streaming for job {job_id}: {str(e)}", exc_info=True)

    finally:
        db.close()


# ============================================================================
# KAMIWAZA DEBUGGING HELPER
# ============================================================================

def log_kamiwaza_debug_info(job_id: int, instance_id: str, region: str, db):
    """
    Collect debugging information from Kamiwaza instance when readiness checks fail.
    """
    def log_message(level: str, message: str):
        log = JobLog(
            job_id=job_id,
            level=level,
            message=message,
            source="debug"
        )
        db.add(log)
        db.commit()

    log_message("info", "=" * 60)
    log_message("info", "COLLECTING DEBUG INFORMATION")
    log_message("info", "=" * 60)

    try:
        # Get AWS credentials
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        provisioner = AWSCDKProvisioner()

        auth_method = os.environ.get("AWS_AUTH_METHOD", "access_keys")
        credentials = None

        if auth_method == "assume_role":
            role_arn = os.environ.get("AWS_ASSUME_ROLE_ARN")
            external_id = os.environ.get("AWS_EXTERNAL_ID")
            session_name = os.environ.get("AWS_SESSION_NAME", "kamiwaza-provisioner")

            if not role_arn:
                raise Exception("AWS_ASSUME_ROLE_ARN not configured")

            credentials = provisioner.assume_role(
                role_arn=role_arn,
                session_name=session_name,
                external_id=external_id,
                region=region
            )
        elif auth_method == "access_keys":
            access_key = os.environ.get("AWS_ACCESS_KEY_ID")
            secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

            if not access_key or not secret_key:
                raise Exception("AWS credentials not configured")

            credentials = {
                'access_key': access_key,
                'secret_key': secret_key,
                'region': region
            }

        # Create SSM client
        ssm_client = boto3.client(
            'ssm',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Collect debugging information
        debug_command = """
echo "=== Kamiwaza Status ==="
sudo -u ubuntu kamiwaza status 2>&1 || echo "kamiwaza status failed"

echo ""
echo "=== Docker Containers ==="
docker ps -a 2>&1 || echo "docker ps failed"

echo ""
echo "=== Last 20 lines of deployment log ==="
tail -n 20 /var/log/kamiwaza-deployment.log 2>&1 || echo "No deployment log"

echo ""
echo "=== Last 20 lines of startup log ==="
tail -n 20 /var/log/kamiwaza-startup.log 2>&1 || echo "No startup log"

echo ""
echo "=== Port 443 Status ==="
ss -tlnp | grep :443 2>&1 || echo "Port 443 not listening"

echo ""
echo "=== Disk Space ==="
df -h / 2>&1

echo ""
echo "=== Memory Usage ==="
free -h 2>&1
"""

        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': [debug_command]},
            TimeoutSeconds=60
        )

        command_id = response['Command']['CommandId']

        # Wait for command to complete
        import time
        max_wait = 30
        waited = 0

        while waited < max_wait:
            time.sleep(2)
            waited += 2

            try:
                output = ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id
                )

                if output['Status'] in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                    break
            except ssm_client.exceptions.InvocationDoesNotExist:
                continue

        if output['Status'] == 'Success':
            log_content = output.get('StandardOutputContent', '')
            if log_content.strip():
                for line in log_content.strip().split('\n'):
                    if line.strip():
                        log_message("info", line.strip())
        else:
            log_message("warning", f"Debug command status: {output['Status']}")

        log_message("info", "=" * 60)

    except Exception as e:
        log_message("error", f"Failed to collect debug info: {str(e)}")


# ============================================================================
# KAMIWAZA READINESS CHECK TASK
# ============================================================================

@celery_app.task(bind=True, name='worker.tasks.check_kamiwaza_readiness')
def check_kamiwaza_readiness(self, job_id: int):
    """
    Check if Kamiwaza login page is accessible on the deployed EC2 instance.
    This task is called periodically after a successful deployment.
    """
    import ssl
    import urllib.request
    import urllib.error
    import socket

    db = SessionLocal()

    try:
        # Get job from database
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found for readiness check")
            return

        # Only check Kamiwaza deployments
        if job.deployment_type != "kamiwaza":
            logger.info(f"Job {job_id} is not a Kamiwaza deployment, skipping check")
            return

        # Only check if not already ready
        if job.kamiwaza_ready:
            logger.info(f"Job {job_id} Kamiwaza already marked as ready")
            return

        # Check if we have a public IP
        if not job.public_ip:
            logger.warning(f"Job {job_id} has no public IP, cannot check readiness")
            return

        # Update check attempt
        job.kamiwaza_check_attempts = (job.kamiwaza_check_attempts or 0) + 1
        job.kamiwaza_checked_at = datetime.utcnow()
        db.commit()

        logger.info(f"Checking Kamiwaza readiness for job {job_id} (attempt {job.kamiwaza_check_attempts})")

        # Try to access the login page
        url = f"https://{job.public_ip}"
        error_details = None

        # Create SSL context that doesn't verify certificates (self-signed cert)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Kamiwaza-Deployment-Manager'})
            with urllib.request.urlopen(request, context=ssl_context, timeout=10) as response:
                status_code = response.getcode()
                content = response.read().decode('utf-8', errors='ignore')

                # Check if we got a successful response
                if status_code == 200:
                    # Verify it's actually the Kamiwaza login page
                    if 'kamiwaza' in content.lower() or 'login' in content.lower():
                        logger.info(f"✓ Kamiwaza login page is accessible for job {job_id}")
                        job.kamiwaza_ready = True
                        db.commit()

                        # Log success message
                        log = JobLog(
                            job_id=job.id,
                            level="info",
                            message=f"✓ Kamiwaza login page is now accessible at https://{job.public_ip}",
                            source="readiness-check"
                        )
                        db.add(log)
                        db.commit()

                        # Deploy apps and tools if selected (for Kamiwaza-only deployments without user provisioning)
                        if not job.users_data or len(job.users_data) == 0:
                            # This is a Kamiwaza-only deployment, deploy apps and tools now
                            selected_apps = job.selected_apps if hasattr(job, 'selected_apps') and job.selected_apps else None
                            selected_tools = job.selected_tools if hasattr(job, 'selected_tools') and job.selected_tools else None

                            if (selected_apps and len(selected_apps) > 0) or (selected_tools and len(selected_tools) > 0):
                                try:
                                    # Deploy apps
                                    if selected_apps and len(selected_apps) > 0:
                                        logger.info(f"Deploying {len(selected_apps)} apps to Kamiwaza for job {job_id}")
                                        log = JobLog(
                                            job_id=job.id,
                                            level="info",
                                            message=f"Starting automatic app deployment: {', '.join(selected_apps)}",
                                            source="readiness-check"
                                        )
                                        db.add(log)
                                        db.commit()

                                        from app.kamiwaza_app_hydrator import KamiwazaAppHydrator
                                        hydrator = KamiwazaAppHydrator()
                                        hydrator.kamiwaza_url = f"https://{job.public_ip}"

                                        app_success, app_summary, app_logs = hydrator.hydrate_apps_and_tools(
                                            callback=None,
                                            selected_apps=selected_apps
                                        )

                                        if app_success:
                                            log = JobLog(
                                                job_id=job.id,
                                                level="info",
                                                message=f"✓ Apps deployed successfully",
                                                source="readiness-check"
                                            )
                                            db.add(log)
                                        else:
                                            log = JobLog(
                                                job_id=job.id,
                                                level="warning",
                                                message=f"⚠ App deployment failed: {app_summary}",
                                                source="readiness-check"
                                            )
                                            db.add(log)
                                        db.commit()

                                    # Deploy tools
                                    if selected_tools and len(selected_tools) > 0:
                                        logger.info(f"Deploying {len(selected_tools)} tools to Kamiwaza for job {job_id}")
                                        log = JobLog(
                                            job_id=job.id,
                                            level="info",
                                            message=f"Starting automatic tool deployment: {', '.join(selected_tools)}",
                                            source="readiness-check"
                                        )
                                        db.add(log)
                                        db.commit()

                                        from app.kamiwaza_tools_provisioner import KamiwazaToolsProvisioner
                                        from app.config import settings

                                        tools_provisioner = KamiwazaToolsProvisioner(
                                            kamiwaza_url=f"https://{job.public_ip}",
                                            username=settings.kamiwaza_username,
                                            password=settings.kamiwaza_password,
                                            toolshed_stage=settings.toolshed_stage
                                        )

                                        tools_success, tools_summary, tools_logs = tools_provisioner.provision_tools(
                                            callback=None,
                                            selected_tools=selected_tools,
                                            sync_first=True
                                        )

                                        if tools_success:
                                            log = JobLog(
                                                job_id=job.id,
                                                level="info",
                                                message=f"✓ Tools deployed successfully",
                                                source="readiness-check"
                                            )
                                            db.add(log)
                                            # Update tool deployment status
                                            if not job.tool_deployment_status:
                                                job.tool_deployment_status = {}
                                            for tool_name in selected_tools:
                                                job.tool_deployment_status[tool_name] = "success"
                                        else:
                                            log = JobLog(
                                                job_id=job.id,
                                                level="warning",
                                                message=f"⚠ Tool deployment failed: {tools_summary}",
                                                source="readiness-check"
                                            )
                                            db.add(log)
                                            # Mark failed tools
                                            if not job.tool_deployment_status:
                                                job.tool_deployment_status = {}
                                            for tool_name in selected_tools:
                                                job.tool_deployment_status[tool_name] = "failed"

                                        db.commit()

                                except Exception as deploy_error:
                                    logger.error(f"Error deploying apps/tools for job {job_id}: {str(deploy_error)}")
                                    log = JobLog(
                                        job_id=job.id,
                                        level="error",
                                        message=f"✗ App/tool deployment error: {str(deploy_error)}",
                                        source="readiness-check"
                                    )
                                    db.add(log)
                                    db.commit()

                        # Trigger automatic AMI creation (if not already in progress)
                        if not job.ami_creation_status or job.ami_creation_status == "pending":
                            logger.info(f"Triggering automatic AMI creation for job {job_id}")
                            job.ami_creation_status = "pending"
                            db.commit()
                            # Schedule AMI creation in 2 minutes to allow final setup
                            create_ami_after_deployment.apply_async(args=[job_id], countdown=120)

                        return
                    else:
                        error_details = f"Got HTTP 200 but content doesn't look like Kamiwaza (content length: {len(content)} bytes)"
                        logger.info(f"{error_details} for job {job_id}")
                else:
                    error_details = f"Got HTTP {status_code}"
                    logger.info(f"{error_details} for job {job_id}")

        except urllib.error.HTTPError as e:
            error_details = f"HTTP {e.code} error"
            logger.info(f"{error_details} when checking job {job_id}")
        except urllib.error.URLError as e:
            # More detailed error based on reason type
            if isinstance(e.reason, socket.timeout):
                error_details = "Connection timeout (10s) - service may still be starting"
            elif isinstance(e.reason, socket.gaierror):
                error_details = f"DNS resolution failed: {e.reason}"
            elif isinstance(e.reason, ConnectionRefusedError):
                error_details = "Connection refused - port 443 not accepting connections yet"
            elif isinstance(e.reason, ssl.SSLError):
                error_details = f"SSL error: {e.reason}"
            else:
                error_details = f"Connection failed: {e.reason}"
            logger.info(f"{error_details} for job {job_id}")
        except socket.timeout:
            error_details = "Socket timeout - service not responding"
            logger.info(f"{error_details} for job {job_id}")
        except Exception as e:
            error_details = f"{type(e).__name__}: {str(e)}"
            logger.warning(f"Unexpected error checking job {job_id}: {error_details}")

        # Log check attempt with error details
        if error_details:
            message = f"Kamiwaza readiness check #{job.kamiwaza_check_attempts}: {error_details}"
        else:
            message = f"Kamiwaza readiness check #{job.kamiwaza_check_attempts}: Not yet accessible"

        log = JobLog(
            job_id=job.id,
            level="info",
            message=message,
            source="readiness-check"
        )
        db.add(log)
        db.commit()

        # Schedule another check if we haven't exceeded max attempts (180 attempts = 1.5 hours)
        MAX_ATTEMPTS = 180
        if job.kamiwaza_check_attempts < MAX_ATTEMPTS:
            # Schedule another check in 30 seconds
            check_kamiwaza_readiness.apply_async(args=[job_id], countdown=30)
        else:
            logger.warning(f"Max readiness check attempts reached for job {job_id}")
            log = JobLog(
                job_id=job.id,
                level="warning",
                message=f"⚠ Kamiwaza readiness checks timed out after {MAX_ATTEMPTS} attempts (~1.5 hours). Last error: {error_details or 'Unknown'}. The deployment may still be in progress. Check https://{job.public_ip} manually.",
                source="readiness-check"
            )
            db.add(log)
            db.commit()

            # Log debugging information via SSM if possible
            try:
                log_kamiwaza_debug_info(job_id, job.instance_id, region, db)
            except Exception as e:
                logger.error(f"Failed to collect debug info for job {job_id}: {e}")

    except Exception as e:
        logger.error(f"Error in readiness check for job {job_id}: {str(e)}", exc_info=True)
        # Log the critical error to the database
        try:
            log = JobLog(
                job_id=job_id,
                level="error",
                message=f"Critical error in readiness check: {str(e)}",
                source="readiness-check"
            )
            db.add(log)
            db.commit()
        except:
            pass

    finally:
        db.close()


# ============================================================================
# AUTOMATIC AMI CREATION TASK
# ============================================================================

def check_ami_exists_for_version(version: str, region: str, credentials: Dict) -> Optional[str]:
    """
    Check if an AMI already exists for a given Kamiwaza version.

    Args:
        version: Kamiwaza version (e.g., "v0.9.2" or "release/0.9.2")
        region: AWS region
        credentials: AWS credentials dict

    Returns:
        AMI ID if found, None otherwise
    """
    try:
        # Normalize version to format like "v0.9.2"
        if version.startswith("release/"):
            version = "v" + version.replace("release/", "")
        elif not version.startswith("v"):
            version = "v" + version

        ec2_client = boto3.client(
            'ec2',
            region_name=region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Search for AMIs with the KamiwazaVersion tag
        response = ec2_client.describe_images(
            Filters=[
                {
                    'Name': 'tag:KamiwazaVersion',
                    'Values': [version]
                },
                {
                    'Name': 'tag:ManagedBy',
                    'Values': ['KamiwazaDeploymentManager']
                },
                {
                    'Name': 'state',
                    'Values': ['available']
                }
            ],
            Owners=['self']
        )

        images = response.get('Images', [])
        if images:
            # Return the most recent AMI
            images.sort(key=lambda x: x['CreationDate'], reverse=True)
            ami_id = images[0]['ImageId']
            logger.info(f"Found existing AMI {ami_id} for version {version}")
            return ami_id

        return None

    except Exception as e:
        logger.warning(f"Error checking for existing AMI: {str(e)}")
        return None


@celery_app.task(bind=True, name='worker.tasks.create_ami_after_deployment')
def create_ami_after_deployment(self, job_id: int):
    """
    Create an AMI from a successfully deployed Kamiwaza instance.
    This is called after readiness check passes.
    """
    db = SessionLocal()

    try:
        # Get job from database
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found for AMI creation")
            return

        # Only create AMI for Kamiwaza deployments
        if job.deployment_type != "kamiwaza":
            logger.info(f"Job {job_id} is not a Kamiwaza deployment, skipping AMI creation")
            job.ami_creation_status = "skipped"
            db.commit()
            return

        # Skip if AMI creation already attempted
        if job.ami_creation_status in ["creating", "completed"]:
            logger.info(f"Job {job_id} AMI creation already {job.ami_creation_status}")
            return

        # Check if we have instance ID
        if not job.instance_id:
            logger.warning(f"Job {job_id} has no instance ID, cannot create AMI")
            job.ami_creation_status = "failed"
            job.ami_creation_error = "No instance ID available"
            db.commit()
            return

        def log_message(level: str, message: str):
            """Helper to log messages"""
            log = JobLog(
                job_id=job.id,
                level=level,
                message=message,
                source="ami-creation"
            )
            db.add(log)
            db.commit()
            logger.log(getattr(logging, level.upper()), f"AMI creation for job {job_id}: {message}")

        log_message("info", "Starting automatic AMI creation...")

        # Get AWS credentials
        from app.aws_cdk_provisioner import AWSCDKProvisioner
        provisioner = AWSCDKProvisioner()

        auth_method = os.environ.get("AWS_AUTH_METHOD", "access_keys")
        credentials = None

        try:
            if auth_method == "assume_role":
                role_arn = os.environ.get("AWS_ASSUME_ROLE_ARN")
                external_id = os.environ.get("AWS_EXTERNAL_ID")
                session_name = os.environ.get("AWS_SESSION_NAME", "kamiwaza-provisioner")

                if not role_arn:
                    raise Exception("AWS_ASSUME_ROLE_ARN not configured")

                credentials = provisioner.assume_role(
                    role_arn=role_arn,
                    session_name=session_name,
                    external_id=external_id,
                    region=job.aws_region
                )
            elif auth_method == "access_keys":
                access_key = os.environ.get("AWS_ACCESS_KEY_ID")
                secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

                if not access_key or not secret_key:
                    raise Exception("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY not configured")

                credentials = {
                    'access_key': access_key,
                    'secret_key': secret_key,
                    'region': job.aws_region
                }
        except Exception as e:
            log_message("error", f"Failed to get AWS credentials: {str(e)}")
            job.ami_creation_status = "failed"
            job.ami_creation_error = str(e)
            db.commit()
            return

        # Extract Kamiwaza version from branch
        kamiwaza_version = job.kamiwaza_branch or "v0.9.2"
        if kamiwaza_version.startswith("release/"):
            kamiwaza_version = "v" + kamiwaza_version.replace("release/", "")
        elif not kamiwaza_version.startswith("v"):
            kamiwaza_version = "v" + kamiwaza_version

        log_message("info", f"Checking for existing AMI for Kamiwaza {kamiwaza_version}...")

        # Check if AMI already exists for this version
        existing_ami = check_ami_exists_for_version(
            kamiwaza_version,
            job.aws_region,
            credentials
        )

        if existing_ami:
            log_message("info", f"✓ AMI already exists for {kamiwaza_version}: {existing_ami}")
            log_message("info", "Skipping AMI creation (version already cached)")
            job.ami_creation_status = "skipped"
            job.created_ami_id = existing_ami
            db.commit()
            return

        log_message("info", f"No existing AMI found for {kamiwaza_version}, creating new AMI...")

        # Update status
        job.ami_creation_status = "creating"
        db.commit()

        # Create EC2 client
        ec2_client = boto3.client(
            'ec2',
            region_name=job.aws_region,
            aws_access_key_id=credentials.get('access_key'),
            aws_secret_access_key=credentials.get('secret_key'),
            aws_session_token=credentials.get('session_token')
        )

        # Generate AMI name
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        ami_name = f"kamiwaza-golden-{kamiwaza_version}-{timestamp}"
        ami_description = f"Kamiwaza {kamiwaza_version} pre-installed on Ubuntu 24.04 LTS (auto-created from job {job.id})"

        log_message("info", f"Creating AMI: {ami_name}")

        # Create the AMI (with reboot for consistency)
        response = ec2_client.create_image(
            InstanceId=job.instance_id,
            Name=ami_name,
            Description=ami_description,
            NoReboot=False,  # Reboot for filesystem consistency
            TagSpecifications=[
                {
                    'ResourceType': 'image',
                    'Tags': [
                        {'Key': 'Name', 'Value': ami_name},
                        {'Key': 'KamiwazaVersion', 'Value': kamiwaza_version},
                        {'Key': 'KamiwazaDeploymentMode', 'Value': job.kamiwaza_deployment_mode or 'full'},
                        {'Key': 'CreatedFrom', 'Value': job.instance_id},
                        {'Key': 'CreatedFromJob', 'Value': str(job.id)},
                        {'Key': 'ManagedBy', 'Value': 'KamiwazaDeploymentManager'},
                        {'Key': 'CreatedAt', 'Value': timestamp},
                        {'Key': 'AutoCreated', 'Value': 'true'}
                    ]
                }
            ]
        )

        ami_id = response['ImageId']
        job.created_ami_id = ami_id
        db.commit()

        log_message("info", f"✓ AMI creation initiated: {ami_id}")
        log_message("info", "Waiting for AMI to become available (this may take 20-30 minutes)...")

        # Wait for AMI to be available
        waiter = ec2_client.get_waiter('image_available')
        waiter.wait(
            ImageIds=[ami_id],
            WaiterConfig={
                'Delay': 30,  # Check every 30 seconds
                'MaxAttempts': 80  # Wait up to 40 minutes (30s * 80 = 2400s)
            }
        )

        # Get AMI details
        ami_info = ec2_client.describe_images(ImageIds=[ami_id])
        if ami_info['Images']:
            ami_size = ami_info['Images'][0]['BlockDeviceMappings'][0]['Ebs']['VolumeSize']
            log_message("info", f"✓ AMI is now available! Size: {ami_size} GB")

        # Mark as completed
        job.ami_creation_status = "completed"
        job.ami_created_at = datetime.utcnow()
        db.commit()

        log_message("info", "=" * 60)
        log_message("info", f"✓ AMI Created Successfully: {ami_id}")
        log_message("info", f"Version: {kamiwaza_version}")
        log_message("info", f"Region: {job.aws_region}")
        log_message("info", "This AMI can now be used for faster future deployments!")
        log_message("info", "=" * 60)

    except ClientError as e:
        error_msg = f"AWS error creating AMI: {e.response['Error']['Message']}"
        logger.error(f"Job {job_id}: {error_msg}")
        job.ami_creation_status = "failed"
        job.ami_creation_error = error_msg
        db.commit()

        log = JobLog(
            job_id=job.id,
            level="error",
            message=error_msg,
            source="ami-creation"
        )
        db.add(log)
        db.commit()

    except Exception as e:
        error_msg = f"Unexpected error creating AMI: {str(e)}"
        logger.error(f"Job {job_id}: {error_msg}", exc_info=True)
        job.ami_creation_status = "failed"
        job.ami_creation_error = error_msg
        db.commit()

        log = JobLog(
            job_id=job.id,
            level="error",
            message=error_msg,
            source="ami-creation"
        )
        db.add(log)
        db.commit()

    finally:
        db.close()
