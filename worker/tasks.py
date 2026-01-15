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
from app.email_service import EmailService
from app.csv_handler import CSVHandler
from app.config import settings

import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='worker.tasks.execute_provisioning_job')
def execute_provisioning_job(self, job_id: int):
    """
    Execute a provisioning job: authenticate AWS, run Terraform, send email.
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
