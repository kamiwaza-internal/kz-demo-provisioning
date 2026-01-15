import boto3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Handle email notifications via SES or SMTP"""

    @staticmethod
    def send_job_notification(
        recipient_email: str,
        job_name: str,
        job_id: int,
        status: str,
        instance_id: Optional[str] = None,
        public_ip: Optional[str] = None,
        private_ip: Optional[str] = None,
        aws_region: str = None,
        aws_account_id: Optional[str] = None,
        role_arn: Optional[str] = None,
        exposed_ports: Optional[list] = None,
        error_message: Optional[str] = None,
        log_excerpt: Optional[str] = None,
        web_ui_url: Optional[str] = None
    ) -> bool:
        """
        Send job completion notification email.

        Returns:
            True if email sent successfully, False otherwise
        """
        subject = f"[{status.upper()}] Provisioning Job: {job_name}"

        # Build email body
        body_lines = [
            f"Provisioning Job Status: {status.upper()}",
            f"Job Name: {job_name}",
            f"Job ID: {job_id}",
            ""
        ]

        if status == "success":
            body_lines.extend([
                "EC2 Instance Details:",
                f"  Instance ID: {instance_id}",
                f"  Region: {aws_region}",
            ])

            if public_ip:
                body_lines.append(f"  Public IP: {public_ip}")
            if private_ip:
                body_lines.append(f"  Private IP: {private_ip}")
            if aws_account_id:
                body_lines.append(f"  Account ID: {aws_account_id}")
            if role_arn:
                body_lines.append(f"  Role: {role_arn}")

            body_lines.append("")

            if exposed_ports:
                body_lines.extend([
                    "Exposed Services:",
                    *[f"  - Port {port}" for port in exposed_ports],
                    ""
                ])

        elif status == "failed":
            body_lines.extend([
                f"Error: {error_message or 'Unknown error'}",
                ""
            ])

        if log_excerpt:
            body_lines.extend([
                "Recent Log Excerpt:",
                "---",
                log_excerpt,
                "---",
                ""
            ])

        if web_ui_url:
            body_lines.append(f"View full details: {web_ui_url}/jobs/{job_id}")

        body = "\n".join(body_lines)

        # Send via configured provider
        if settings.email_provider == "ses":
            return EmailService._send_via_ses(recipient_email, subject, body)
        else:
            return EmailService._send_via_smtp(recipient_email, subject, body)

    @staticmethod
    def _send_via_ses(recipient: str, subject: str, body: str) -> bool:
        """Send email via AWS SES"""
        try:
            ses_client = boto3.client('ses', region_name=settings.ses_region)

            response = ses_client.send_email(
                Source=settings.ses_from_email,
                Destination={'ToAddresses': [recipient]},
                Message={
                    'Subject': {'Data': subject},
                    'Body': {'Text': {'Data': body}}
                }
            )

            logger.info(f"Email sent via SES to {recipient}, MessageId: {response['MessageId']}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email via SES: {str(e)}")
            return False

    @staticmethod
    def _send_via_smtp(recipient: str, subject: str, body: str) -> bool:
        """Send email via SMTP"""
        try:
            msg = MIMEMultipart()
            msg['From'] = settings.smtp_from
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                if settings.smtp_user and settings.smtp_pass:
                    server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)

            logger.info(f"Email sent via SMTP to {recipient}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {str(e)}")
            return False
