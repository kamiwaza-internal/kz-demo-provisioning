import os
import json
import base64
from datetime import datetime
from pathlib import Path
from typing import Dict

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

    # Generate user data script
    user_data_script = generate_user_data_script(job, db)
    user_data_b64 = base64.b64encode(user_data_script.encode()).decode()

    instance_config = {
        'instance_type': job.instance_type,
        'ami_id': job.ami_id,
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


def generate_user_data_script(job: Job, db) -> str:
    """Generate user_data script for EC2 instance"""

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

        # Initialize provisioner
        provisioner = KamiwazaProvisioner()

        # Run provisioning with live callback
        success, summary, log_lines = provisioner.run_provisioning(
            csv_content=csv_content,
            callback=lambda line: log_message("info", line)
        )

        # Update job status
        if success:
            job.status = "success"
            job.completed_at = datetime.utcnow()
            log_message("info", "✓ Provisioning completed successfully")
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
