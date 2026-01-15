import os
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Callable, Optional
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class TerraformError(Exception):
    """Custom exception for Terraform execution errors"""
    pass


class TerraformRunner:
    """Handles Terraform execution in isolated job directories"""

    def __init__(self, job_id: int, log_callback: Optional[Callable[[str, str], None]] = None):
        """
        Initialize Terraform runner for a job.

        Args:
            job_id: Unique job identifier
            log_callback: Optional callback function(level, message) for logging
        """
        self.job_id = job_id
        self.log_callback = log_callback or self._default_log
        self.work_dir = Path(settings.jobs_workdir) / str(job_id)
        self.terraform_binary = settings.terraform_binary

    def _default_log(self, level: str, message: str):
        """Default logging if no callback provided"""
        logger.log(getattr(logging, level.upper(), logging.INFO), message)

    def _log(self, level: str, message: str):
        """Internal logging wrapper"""
        self.log_callback(level, message)

    def prepare_workspace(self, terraform_source_dir: str):
        """
        Prepare isolated Terraform workspace for the job.

        Args:
            terraform_source_dir: Path to source terraform files

        Raises:
            TerraformError: If workspace preparation fails
        """
        try:
            # Create job work directory
            self.work_dir.mkdir(parents=True, exist_ok=True)
            self._log("info", f"Created workspace: {self.work_dir}")

            # Copy terraform files from source
            source_path = Path(terraform_source_dir)
            if not source_path.exists():
                raise TerraformError(f"Terraform source directory not found: {terraform_source_dir}")

            for tf_file in source_path.glob("*.tf"):
                shutil.copy(tf_file, self.work_dir)
                self._log("debug", f"Copied {tf_file.name}")

            # Copy template files
            for tpl_file in source_path.glob("*.tpl"):
                shutil.copy(tpl_file, self.work_dir)
                self._log("debug", f"Copied {tpl_file.name}")

        except Exception as e:
            self._log("error", f"Failed to prepare workspace: {str(e)}")
            raise TerraformError(f"Workspace preparation failed: {str(e)}")

    def write_tfvars(self, variables: Dict):
        """
        Write variables to tfvars.json file.

        Args:
            variables: Dictionary of Terraform variables

        Raises:
            TerraformError: If writing fails
        """
        try:
            tfvars_path = self.work_dir / "terraform.tfvars.json"
            with open(tfvars_path, 'w') as f:
                json.dump(variables, f, indent=2)

            self._log("info", f"Written tfvars with {len(variables)} variables")
            self._log("debug", f"Variables: {list(variables.keys())}")

        except Exception as e:
            self._log("error", f"Failed to write tfvars: {str(e)}")
            raise TerraformError(f"Failed to write tfvars: {str(e)}")

    def run_terraform_command(
        self,
        command: list,
        env: Dict[str, str],
        capture_output: bool = True
    ) -> subprocess.CompletedProcess:
        """
        Execute a terraform command with environment variables.

        Args:
            command: Command list (e.g., ['init'], ['apply', '-auto-approve'])
            env: Environment variables including AWS credentials
            capture_output: Whether to capture and log output line by line

        Returns:
            CompletedProcess instance

        Raises:
            TerraformError: If command fails
        """
        full_command = [self.terraform_binary] + command
        full_env = {**os.environ.copy(), **env}

        # Remove sensitive vars from logs
        safe_env_keys = [k for k in env.keys() if 'SECRET' not in k.upper() and 'TOKEN' not in k.upper()]
        self._log("info", f"Running: {' '.join(full_command)}")
        self._log("debug", f"Environment vars set: {safe_env_keys}")

        try:
            if capture_output:
                # Stream output line by line
                process = subprocess.Popen(
                    full_command,
                    cwd=str(self.work_dir),
                    env=full_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                output_lines = []
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        output_lines.append(line)
                        # Determine log level based on content
                        level = "error" if "Error:" in line else "info"
                        self._log(level, f"[terraform] {line}")

                process.wait()

                if process.returncode != 0:
                    raise TerraformError(
                        f"Terraform command failed with exit code {process.returncode}"
                    )

                # Create a CompletedProcess-like object
                return subprocess.CompletedProcess(
                    args=full_command,
                    returncode=process.returncode,
                    stdout="\n".join(output_lines),
                    stderr=""
                )
            else:
                # Simple execution
                result = subprocess.run(
                    full_command,
                    cwd=str(self.work_dir),
                    env=full_env,
                    capture_output=True,
                    text=True,
                    check=True
                )
                return result

        except subprocess.CalledProcessError as e:
            self._log("error", f"Terraform command failed: {e.stderr}")
            raise TerraformError(f"Command failed: {e.stderr}")
        except Exception as e:
            self._log("error", f"Unexpected error running terraform: {str(e)}")
            raise TerraformError(f"Unexpected error: {str(e)}")

    def init(self, env: Dict[str, str]):
        """Run terraform init"""
        self._log("info", "Initializing Terraform...")
        self.run_terraform_command(['init', '-no-color'], env)
        self._log("info", "Terraform initialized successfully")

    def validate(self, env: Dict[str, str]):
        """Run terraform validate"""
        self._log("info", "Validating Terraform configuration...")
        self.run_terraform_command(['validate', '-no-color'], env)
        self._log("info", "Terraform validation successful")

    def plan(self, env: Dict[str, str]):
        """Run terraform plan"""
        self._log("info", "Planning Terraform changes...")
        self.run_terraform_command(['plan', '-no-color'], env)
        self._log("info", "Terraform plan completed")

    def apply(self, env: Dict[str, str]):
        """Run terraform apply"""
        self._log("info", "Applying Terraform configuration...")
        self.run_terraform_command(['apply', '-auto-approve', '-no-color'], env)
        self._log("info", "Terraform apply completed successfully")

    def get_outputs(self, env: Dict[str, str]) -> Dict:
        """
        Get terraform outputs as JSON.

        Returns:
            Dictionary of output values

        Raises:
            TerraformError: If unable to retrieve outputs
        """
        try:
            self._log("info", "Retrieving Terraform outputs...")
            result = self.run_terraform_command(
                ['output', '-json', '-no-color'],
                env,
                capture_output=False
            )

            outputs = json.loads(result.stdout)
            self._log("info", f"Retrieved {len(outputs)} outputs")

            # Extract values from output format
            output_values = {
                key: val.get('value')
                for key, val in outputs.items()
            }

            return output_values

        except json.JSONDecodeError as e:
            self._log("error", f"Failed to parse terraform outputs: {str(e)}")
            raise TerraformError(f"Invalid JSON output: {str(e)}")
        except Exception as e:
            self._log("error", f"Failed to get outputs: {str(e)}")
            raise TerraformError(f"Failed to get outputs: {str(e)}")

    def destroy(self, env: Dict[str, str]):
        """Run terraform destroy (for cleanup)"""
        self._log("info", "Destroying Terraform resources...")
        self.run_terraform_command(['destroy', '-auto-approve', '-no-color'], env)
        self._log("info", "Terraform destroy completed")

    def cleanup_workspace(self):
        """Remove job workspace directory"""
        try:
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)
                self._log("info", f"Cleaned up workspace: {self.work_dir}")
        except Exception as e:
            self._log("warning", f"Failed to cleanup workspace: {str(e)}")
