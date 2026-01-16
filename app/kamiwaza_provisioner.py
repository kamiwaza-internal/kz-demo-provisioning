"""
Kamiwaza User Provisioning Handler

Integrates with the provision_users.py script from the Kamiwaza repository
to provision users and deploy Kaizen instances.
"""

import os
import subprocess
import csv as csv_module
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class KamiwazaProvisioningError(Exception):
    """Exception raised during Kamiwaza provisioning"""
    pass


class KamiwazaProvisioner:
    """
    Handler for provisioning Kamiwaza users and Kaizen instances.

    This class wraps the provision_users.py script and provides
    integration with the web app's job system.
    """

    def __init__(self):
        # Default paths - can be overridden via environment variables
        self.provision_script = os.environ.get(
            "KAMIWAZA_PROVISION_SCRIPT",
            "/Users/steffenmerten/Code/kamiwaza/scripts/provision_users.py"
        )
        self.kaizen_source = os.environ.get(
            "KAIZEN_SOURCE",
            "/Users/steffenmerten/Code/kaizen-v3/apps/kaizenv3"
        )
        self.kamiwaza_url = os.environ.get("KAMIWAZA_URL", "https://localhost")
        self.kamiwaza_username = os.environ.get("KAMIWAZA_USERNAME", "admin")
        self.kamiwaza_password = os.environ.get("KAMIWAZA_PASSWORD", "kamiwaza")
        self.user_password = os.environ.get("DEFAULT_USER_PASSWORD", "kamiwaza")
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def validate_prerequisites(self) -> Tuple[bool, List[str]]:
        """
        Validate that all prerequisites are met for provisioning.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check provision script exists
        if not Path(self.provision_script).exists():
            errors.append(f"Provision script not found: {self.provision_script}")

        # Check kaizen source exists
        if not Path(self.kaizen_source).exists():
            errors.append(f"Kaizen source not found: {self.kaizen_source}")

        # Check Kamiwaza is accessible
        try:
            import httpx
            with httpx.Client(verify=False, timeout=5.0) as client:
                response = client.get(f"{self.kamiwaza_url}/health")
                if response.status_code != 200:
                    errors.append(f"Kamiwaza health check failed: HTTP {response.status_code}")
        except Exception as e:
            errors.append(f"Cannot reach Kamiwaza at {self.kamiwaza_url}: {str(e)}")

        # Check Keycloak container is running
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=keycloak", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if "keycloak" not in result.stdout:
                errors.append("Keycloak container not running")
        except Exception as e:
            errors.append(f"Cannot check Keycloak container: {str(e)}")

        return (len(errors) == 0, errors)

    def validate_csv(self, csv_content: bytes) -> Tuple[bool, List[Dict[str, str]], List[str]]:
        """
        Validate CSV file format and content.

        Args:
            csv_content: Raw CSV file content as bytes

        Returns:
            Tuple of (is_valid, list of user dicts, list of errors)
        """
        errors = []
        users = []

        try:
            # Decode content
            content_str = csv_content.decode('utf-8')
            lines = content_str.strip().split('\n')

            if len(lines) < 2:
                errors.append("CSV must have at least a header row and one data row")
                return (False, users, errors)

            # Parse CSV
            reader = csv_module.DictReader(lines)

            # Check required columns
            if 'email' not in reader.fieldnames:
                errors.append("CSV must have an 'email' column")
            if 'role' not in reader.fieldnames:
                errors.append("CSV must have a 'role' column")

            if errors:
                return (False, users, errors)

            # Validate rows
            for i, row in enumerate(reader, start=2):
                email = row.get('email', '').strip().lower()
                role = row.get('role', '').strip().lower()

                if not email:
                    errors.append(f"Row {i}: Missing email")
                    continue

                if '@' not in email:
                    errors.append(f"Row {i}: Invalid email format: {email}")
                    continue

                if not role:
                    errors.append(f"Row {i}: Missing role for {email}")
                    continue

                if role not in ('operator', 'analyst'):
                    errors.append(f"Row {i}: Invalid role '{role}' for {email}. Must be 'operator' or 'analyst'")
                    continue

                users.append({'email': email, 'role': role})

            if not users:
                errors.append("No valid users found in CSV")

            return (len(errors) == 0, users, errors)

        except Exception as e:
            errors.append(f"Error parsing CSV: {str(e)}")
            return (False, users, errors)

    def check_kaizen_template_exists(self) -> bool:
        """
        Check if Kaizen template exists in the App Garden.

        Returns:
            True if template exists, False otherwise
        """
        try:
            import httpx

            # Authenticate first
            with httpx.Client(verify=False, timeout=30.0) as client:
                auth_response = client.post(
                    f"{self.kamiwaza_url}/api/auth/token",
                    data={
                        "username": self.kamiwaza_username,
                        "password": self.kamiwaza_password
                    }
                )

                if auth_response.status_code != 200:
                    logger.error(f"Authentication failed: HTTP {auth_response.status_code}")
                    return False

                token = auth_response.json().get("access_token")

                # Check for Kaizen template
                templates_response = client.get(
                    f"{self.kamiwaza_url}/api/apps/app_templates",
                    headers={"Authorization": f"Bearer {token}"}
                )

                if templates_response.status_code != 200:
                    logger.error(f"Failed to list templates: HTTP {templates_response.status_code}")
                    return False

                templates = templates_response.json()
                for template in templates:
                    if template.get("name") == "Kaizen":
                        return True

                return False

        except Exception as e:
            logger.error(f"Error checking Kaizen template: {e}")
            return False

    def run_provisioning(
        self,
        csv_content: bytes,
        callback=None
    ) -> Tuple[bool, str, List[str]]:
        """
        Run the provisioning script with the given CSV.

        Args:
            csv_content: Raw CSV file content as bytes
            callback: Optional callback function(line: str) to receive log output

        Returns:
            Tuple of (success, summary_message, list of log lines)
        """
        log_lines = []

        try:
            # Validate prerequisites
            valid, errors = self.validate_prerequisites()
            if not valid:
                error_msg = "Prerequisites not met:\n" + "\n".join(errors)
                log_lines.append(error_msg)
                if callback:
                    callback(error_msg)
                return (False, error_msg, log_lines)

            # Create temporary CSV file
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as tmp_csv:
                tmp_csv.write(csv_content)
                csv_path = tmp_csv.name

            try:
                # Build command
                cmd = [
                    "python3",
                    self.provision_script,
                    "--csv", csv_path,
                    "--kaizen-source", self.kaizen_source,
                    "--kamiwaza-url", self.kamiwaza_url,
                    "--kamiwaza-username", self.kamiwaza_username,
                    "--kamiwaza-password", self.kamiwaza_password,
                    "--user-password", self.user_password,
                ]

                if self.anthropic_api_key:
                    cmd.extend(["--anthropic-api-key", self.anthropic_api_key])

                # Log command (hide passwords)
                safe_cmd = cmd.copy()
                if "--kamiwaza-password" in safe_cmd:
                    idx = safe_cmd.index("--kamiwaza-password")
                    safe_cmd[idx + 1] = "***"
                if "--user-password" in safe_cmd:
                    idx = safe_cmd.index("--user-password")
                    safe_cmd[idx + 1] = "***"
                if "--anthropic-api-key" in safe_cmd:
                    idx = safe_cmd.index("--anthropic-api-key")
                    safe_cmd[idx + 1] = "***"

                start_msg = f"Starting provisioning: {' '.join(safe_cmd)}"
                log_lines.append(start_msg)
                if callback:
                    callback(start_msg)

                # Run command with live output
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                # Stream output
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        log_lines.append(line)
                        if callback:
                            callback(line)

                # Wait for completion
                return_code = process.wait()

                if return_code == 0:
                    success_msg = "✓ Provisioning completed successfully"
                    log_lines.append(success_msg)
                    if callback:
                        callback(success_msg)
                    return (True, success_msg, log_lines)
                else:
                    error_msg = f"✗ Provisioning failed with exit code {return_code}"
                    log_lines.append(error_msg)
                    if callback:
                        callback(error_msg)
                    return (False, error_msg, log_lines)

            finally:
                # Clean up temporary file
                try:
                    os.unlink(csv_path)
                except:
                    pass

        except Exception as e:
            error_msg = f"✗ Provisioning error: {str(e)}"
            log_lines.append(error_msg)
            if callback:
                callback(error_msg)
            return (False, error_msg, log_lines)
