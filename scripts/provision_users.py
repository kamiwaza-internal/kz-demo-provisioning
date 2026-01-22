#!/usr/bin/env python3
"""
Unified User Provisioning Script for Kamiwaza and Kaizen.

This script:
1. Reads a CSV with email,role columns (role = 'operator' or 'analyst')
2. Creates ONE shared Kaizen template in the App Garden (idempotent)
3. Creates operator users in Kamiwaza with admin role
4. Creates analyst users in Keycloak with viewer/user roles for Kaizen SSO access
5. Deploys individual Kaizen instances for ALL users from the shared template
6. Deploys default MCP tools to the Toolshed and attaches them to Demo Agents

Naming convention for deployments: "{username} kaizen" (e.g., "admin kaizen", "steffen kaizen")

Usage:
    python scripts/provision_users.py --csv scripts/new_users.csv \\
        --anthropic-api-key YOUR_KEY \\
        --tools-source /path/to/kamiwaza-extensions-geo-tools

Prerequisites:
    - Kamiwaza running at https://localhost with auth enabled
    - Keycloak container running (default_kamiwaza-keycloak-web)
    - kaizen-v3 source at /Users/steffenmerten/Code/kaizen-v3
    - kamiwaza-extensions-geo-tools repo for MCP tools (optional)
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
import yaml
import sqlite3
import uuid as uuid_module
from dotenv import load_dotenv

# Load environment variables from .env file
# Look for provision_users.env in the same directory as this script
_script_dir = Path(__file__).parent
_env_file = _script_dir / "provision_users.env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Try loading from current directory
    load_dotenv()


# ============================================================================
# DEFAULT TOOLSHED TOOLS CONFIGURATION
# ============================================================================
# These tools will be deployed to the Kamiwaza Toolshed if not already present,
# and attached as MCP servers to Demo Agents.

def get_default_toolshed_tools() -> list:
    """
    Get default toolshed tools configuration with API keys from environment.
    
    This function is called at runtime to pick up environment variables.
    """
    return [
        {
            "template": "tool-indopac-tracking",
            "name": "indopac-tracking",
            "description": "Indo-Pacific region tracking for satellites, vessels, and aircraft",
            "image": "kamiwazaai/tool-indopac-tracking:v1.0.3",  # Fallback image for direct deploy
            "port": 8000,
            "env_vars": {
                "PORT": "8000",
                "HOST": "0.0.0.0",
                "MCP_TRANSPORT": "http",
                "N2YO_API_KEY": os.environ.get("N2YO_API_KEY", ""),
                "DATALASTIC_API_KEY": os.environ.get("DATALASTIC_API_KEY", ""),
                "FLIGHTRADAR24_API_KEY": os.environ.get("FLIGHTRADAR24_API_KEY", ""),
            },
        },
    ]


# For backward compatibility - will be populated at runtime
DEFAULT_TOOLSHED_TOOLS = []


@dataclass
class UserEntry:
    """Represents a user from the CSV file."""
    email: str
    role: str  # 'operator' or 'analyst'

    @property
    def username(self) -> str:
        """Extract username from email."""
        return self.email.split("@")[0]

    def is_operator(self) -> bool:
        return self.role.lower() == "operator"

    def is_analyst(self) -> bool:
        return self.role.lower() == "analyst"


@dataclass
class ProvisioningResult:
    """Result of provisioning a single user."""
    email: str
    role: str
    status: str  # 'success', 'failed', 'skipped'
    message: str
    deployment_url: Optional[str] = None


@dataclass
class ToolDeployment:
    """Result of deploying a tool to the Toolshed."""
    name: str
    deployment_id: str
    url: str
    status: str


class ToolshedManager:
    """
    Manages MCP tool deployment to Kamiwaza Toolshed.
    
    Based on deploy-to-toolshed.py from kamiwaza-extensions-geo-tools.
    """

    def __init__(
        self,
        api_url: str = "https://localhost/api",
        db_path: Optional[str] = None,
        verify_ssl: bool = False,
    ):
        self.api_url = api_url.rstrip("/")
        self.db_path = db_path
        self.verify_ssl = verify_ssl
        self.token: Optional[str] = None

    def set_token(self, token: str):
        """Set authentication token."""
        self.token = token

    def _headers(self) -> dict:
        """Get authorization headers."""
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def list_templates(self) -> List[dict]:
        """List all available MCP templates in the Toolshed."""
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.get(
                    f"{self.api_url}/tool/templates",
                    headers=self._headers(),
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"  ⚠ Error listing templates: {e}")
        return []

    def get_template_by_name(self, name: str) -> Optional[dict]:
        """Get template by name if it exists."""
        templates = self.list_templates()
        for template in templates:
            if template.get("name") == name:
                return template
        return None

    def list_deployments(self) -> List[dict]:
        """List all active MCP deployments."""
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.get(
                    f"{self.api_url}/tool/deployments",
                    headers=self._headers(),
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"  ⚠ Error listing deployments: {e}")
        return []

    def get_deployment_by_name(self, name: str) -> Optional[dict]:
        """Get deployment by name if it exists."""
        deployments = self.list_deployments()
        for dep in deployments:
            if dep.get("name") == name:
                return dep
        return None

    def register_template(self, tool_path: Path) -> Optional[str]:
        """
        Register an MCP template from a tool directory into Toolshed.

        Args:
            tool_path: Path to the MCP tool directory containing kamiwaza.json

        Returns:
            Template ID if successful, None otherwise.
        """
        if not self.db_path:
            print("  ⚠ Cannot register template: KAMIWAZA_DB_PATH not set")
            return None

        kj_path = tool_path / "kamiwaza.json"
        if not kj_path.exists():
            print(f"  ⚠ kamiwaza.json not found in {tool_path}")
            return None

        with open(kj_path) as f:
            config = json.load(f)

        dc_path = tool_path / "docker-compose.yml"
        compose_yml = ""
        if dc_path.exists():
            compose_yml = dc_path.read_text()

        name = config.get("name")
        version = config.get("version", "1.0.0")
        image = config.get("image", f"kamiwazaai/{name}:v{version}")
        description = config.get("description", "")
        category = config.get("category", "tools")
        tags = json.dumps(config.get("tags", ["tool", "mcp"]))
        env_defaults = json.dumps(config.get("env_defaults", {}))
        required_env_vars = json.dumps(config.get("required_env_vars", []))
        risk_tier = config.get("risk_tier", 1)

        if not name:
            print("  ⚠ kamiwaza.json must have 'name' field")
            return None

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM app_templates WHERE name = ?", (name,))
            existing = cursor.fetchone()

            if existing:
                template_id = existing[0]
                cursor.execute(
                    """
                    UPDATE app_templates SET
                        version = ?, image = ?, description = ?, category = ?,
                        tags = ?, env_defaults = ?, required_env_vars = ?,
                        compose_yml = ?, risk_tier = ?
                    WHERE id = ?
                """,
                    (
                        version, image, description, category, tags,
                        env_defaults, required_env_vars, compose_yml, risk_tier,
                        template_id,
                    ),
                )
                print(f"    ✓ Updated template: {name}")
            else:
                template_id = str(uuid_module.uuid4())
                cursor.execute(
                    """
                    INSERT INTO app_templates (
                        id, name, version, source_type, visibility, risk_tier, verified,
                        image, description, category, tags, env_defaults, required_env_vars, compose_yml
                    ) VALUES (?, ?, ?, 'kamiwaza', 'public', ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        template_id, name, version, risk_tier, image, description,
                        category, tags, env_defaults, required_env_vars, compose_yml,
                    ),
                )
                print(f"    ✓ Registered new template: {name}")

            conn.commit()
            conn.close()
            return template_id

        except Exception as e:
            print(f"  ⚠ Failed to register template: {e}")
            return None

    def deploy_tool(
        self,
        template_name: str,
        name: str,
        env_vars: Optional[dict] = None,
    ) -> Optional[ToolDeployment]:
        """
        Deploy an MCP tool from a template.

        Args:
            template_name: Name of the template to deploy
            name: Name for this deployment instance
            env_vars: Optional environment variables

        Returns:
            ToolDeployment if successful, None otherwise.
        """
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=60.0) as client:
                response = client.post(
                    f"{self.api_url}/tool/deploy-template/{template_name}",
                    json={"name": name, "env_vars": env_vars or {}},
                    headers=self._headers(),
                )
                if response.status_code in [200, 201]:
                    deployment = response.json()
                    return ToolDeployment(
                        name=name,
                        deployment_id=deployment.get("id"),
                        url=deployment.get("url", ""),
                        status=deployment.get("status", "DEPLOYING"),
                    )
                else:
                    print(f"    ⚠ Deployment failed: HTTP {response.status_code}")
                    return None

        except Exception as e:
            print(f"    ⚠ Error deploying tool: {e}")
            return None

    def deploy_tool_direct(
        self,
        name: str,
        image: str,
        env_vars: Optional[dict] = None,
        port: int = 8000,
    ) -> Optional[ToolDeployment]:
        """
        Deploy an MCP tool directly via Docker (bypasses template system).
        
        This is a fallback when templates aren't available in the API.
        
        Args:
            name: Name for this deployment instance
            image: Docker image to deploy
            env_vars: Environment variables
            port: Container port to expose
            
        Returns:
            ToolDeployment if successful, None otherwise.
        """
        deployment_id = str(uuid_module.uuid4())
        container_name = f"kamiwaza-tool-{name}"
        
        # Build environment variables string
        env_args = []
        for k, v in (env_vars or {}).items():
            env_args.extend(["-e", f"{k}={v}"])
        
        # Run Docker container
        try:
            # First, try to remove any existing container with this name
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
            )
            
            # Run the container
            result = subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", container_name,
                    "-p", f"{port}",
                    *env_args,
                    "--network", "default_kamiwaza-traefik",
                    "--restart", "unless-stopped",
                    image,
                ],
                capture_output=True,
                text=True,
            )
            
            if result.returncode != 0:
                print(f"    ⚠ Docker run failed: {result.stderr}")
                return None
            
            # Get the assigned host port
            time.sleep(2)
            inspect_result = subprocess.run(
                ["docker", "port", container_name, str(port)],
                capture_output=True,
                text=True,
            )
            
            if inspect_result.returncode == 0:
                port_mapping = inspect_result.stdout.strip()
                # port_mapping is like "0.0.0.0:32768"
                host_port = port_mapping.split(":")[-1] if port_mapping else str(port)
                # URL for MCP must use host.docker.internal so sandbox containers can reach it
                url = f"http://host.docker.internal:{host_port}/mcp"
                
                return ToolDeployment(
                    name=name,
                    deployment_id=deployment_id,
                    url=url,
                    status="DEPLOYED",
                )
            else:
                # Container running but couldn't get port - use container name as fallback
                # (won't work from sandbox but better than nothing)
                return ToolDeployment(
                    name=name,
                    deployment_id=deployment_id,
                    url=f"http://{container_name}:{port}/mcp",
                    status="DEPLOYED",
                )
                
        except Exception as e:
            print(f"    ⚠ Error with direct Docker deployment: {e}")
            return None

    def wait_for_deployment(
        self,
        deployment_id: str,
        timeout: int = 120,
        poll_interval: int = 5,
    ) -> bool:
        """Wait for deployment to reach DEPLOYED status."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            deployments = self.list_deployments()
            deployment = next(
                (d for d in deployments if d.get("id") == deployment_id), None
            )
            if not deployment:
                return False

            status = deployment.get("status", "UNKNOWN")
            if status == "DEPLOYED":
                return True
            elif status in ["FAILED", "ERROR"]:
                return False

            time.sleep(poll_interval)

        return False

    def ensure_tool_deployed(
        self,
        template_name: str,
        deployment_name: str,
        env_vars: Optional[dict] = None,
        tools_source: Optional[Path] = None,
    ) -> Optional[ToolDeployment]:
        """
        Ensure a tool is deployed, registering template if needed.

        Args:
            template_name: Name of the template (e.g., "tool-indopac-tracking")
            deployment_name: Name for the deployment (e.g., "indopac-tracking")
            env_vars: Environment variables for the deployment
            tools_source: Path to the geo-tools repo (for template registration)

        Returns:
            ToolDeployment if successful, None otherwise.
        """
        # Check if already deployed
        existing = self.get_deployment_by_name(deployment_name)
        if existing and existing.get("status") == "DEPLOYED":
            return ToolDeployment(
                name=deployment_name,
                deployment_id=existing.get("id"),
                url=existing.get("url", ""),
                status="DEPLOYED",
            )

        # Check if template exists in the API
        template = self.get_template_by_name(template_name)
        if not template:
            # Try to register from source via database AND sync the API
            if tools_source:
                tool_path = tools_source / "tools" / template_name
                if tool_path.exists():
                    self.register_template(tool_path)
                    # Force the API to reload templates by triggering an import
                    # This is a workaround for the ORM session cache
                    time.sleep(1)
                    template = self.get_template_by_name(template_name)

        if not template:
            print(f"    ⚠ Template {template_name} not in API, trying direct Docker deployment...")
            # Try direct Docker deployment as fallback
            # First check the tool config for image info
            tool_config = next(
                (t for t in get_default_toolshed_tools() if t.get("template") == template_name),
                None,
            )
            if tool_config and tool_config.get("image"):
                deployment = self.deploy_tool_direct(
                    name=deployment_name,
                    image=tool_config["image"],
                    env_vars=env_vars,
                    port=tool_config.get("port", 8000),
                )
                if deployment:
                    print(f"    ✓ Direct Docker deployment successful")
                    return deployment
            elif tools_source:
                # Fall back to reading from kamiwaza.json
                kj_path = tools_source / "tools" / template_name / "kamiwaza.json"
                if kj_path.exists():
                    with open(kj_path) as f:
                        config = json.load(f)
                    image = config.get("image")
                    if image:
                        deployment = self.deploy_tool_direct(
                            name=deployment_name,
                            image=image,
                            env_vars=env_vars,
                            port=int(config.get("env_defaults", {}).get("PORT", "8000")),
                        )
                        if deployment:
                            print(f"    ✓ Direct Docker deployment successful")
                            return deployment
            
            print(f"    ⚠ Could not deploy {template_name}")
            return None

        # Deploy the tool
        deployment = self.deploy_tool(template_name, deployment_name, env_vars)
        if not deployment:
            return None

        # Wait for it to be ready
        print(f"    ⏳ Waiting for {deployment_name} to be ready...")
        if self.wait_for_deployment(deployment.deployment_id):
            deployment.status = "DEPLOYED"
            # Get the URL from the deployment list
            dep = self.get_deployment_by_name(deployment_name)
            if dep:
                deployment.url = dep.get("url", "")
            return deployment
        else:
            print(f"    ⚠ {deployment_name} did not become ready in time")
            return None


class KamiwazaClient:
    """HTTP client for Kamiwaza REST APIs."""

    def __init__(
        self,
        base_url: str = "https://localhost",
        username: str = "admin",
        password: str = "kamiwaza",
        verify_ssl: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.token: Optional[str] = None

    def authenticate(self) -> bool:
        """Authenticate and obtain access token."""
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/api/auth/token",
                    data={"username": self.username, "password": self.password},
                )
                if response.status_code == 200:
                    data = response.json()
                    self.token = data.get("access_token")
                    return True
                print(f"  ✗ Authentication failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Authentication error: {e}")
            return False

    def _headers(self) -> dict:
        """Get authorization headers."""
        return {"Authorization": f"Bearer {self.token}"}

    def create_operator_user(
        self,
        username: str,
        email: str,
        password: str = "kamiwaza",
    ) -> Tuple[bool, str]:
        """
        Create an operator user with admin role via /api/auth/users/local.

        This endpoint creates the user in both local store and Keycloak.

        Returns:
            Tuple of (success, message)
        """
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                # Operators get all roles including analyst (analyst role is included)
                response = client.post(
                    f"{self.base_url}/api/auth/users/local",
                    json={
                        "username": username,
                        "email": email,
                        "password": password,
                        "roles": ["admin", "developer", "analyst", "viewer", "user"],
                    },
                    headers=self._headers(),
                )

                if response.status_code == 201:
                    return True, f"Created operator user {email} with admin role"
                elif response.status_code == 400:
                    # User might already exist
                    detail = response.json().get("detail", "")
                    if "exists" in detail.lower() or "duplicate" in detail.lower():
                        return True, f"Operator user {email} already exists"
                    return False, f"Bad request: {detail}"
                else:
                    return False, f"HTTP {response.status_code}: {response.text}"

        except Exception as e:
            return False, f"Error creating operator user: {e}"

    def get_template_by_name(self, name: str) -> Optional[dict]:
        """Get template by name if it exists."""
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.get(
                    f"{self.base_url}/api/apps/app_templates",
                    headers=self._headers(),
                )
                if response.status_code == 200:
                    templates = response.json()
                    for template in templates:
                        if template.get("name") == name:
                            return template
        except Exception as e:
            print(f"  ⚠ Error listing templates: {e}")
        return None

    def create_kaizen_template(
        self,
        template_name: str,
        kaizen_source: Path,
    ) -> Optional[str]:
        """
        Create Kaizen App Garden template.

        Returns template ID if successful, None otherwise.
        """
        metadata_file = kaizen_source / "kamiwaza.json"
        compose_file = kaizen_source / "docker-compose.appgarden.yml"

        if not metadata_file.exists():
            print(f"  ✗ Metadata not found: {metadata_file}")
            return None

        if not compose_file.exists():
            print(f"  ✗ Compose file not found: {compose_file}")
            return None

        with open(metadata_file) as f:
            metadata = json.load(f)

        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)

        # Remove hardcoded container_name from services to allow unique naming
        # per deployment (Docker Compose will use project-based naming)
        for service_name, service_config in compose_data.get("services", {}).items():
            if "container_name" in service_config:
                del service_config["container_name"]

        # Convert back to YAML string
        compose_content = yaml.dump(compose_data, default_flow_style=False, sort_keys=False)

        # Use display name from metadata if available, otherwise use template_name
        display_name = metadata.get("name", template_name)

        template_payload = {
            "name": template_name,
            "display_name": display_name,
            "description": metadata.get("description", "Kaizen AI Assistant instance"),
            "version": metadata.get("version", "1.2.62"),
            "source_type": "kamiwaza",
            "compose_yml": compose_content,
            "metadata": metadata,
            "env_defaults": {
                **metadata.get("env_defaults", {}),
                "KAMIWAZA_USE_AUTH": "true",
            },
            "visibility": "private",
        }

        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/api/apps/app_templates",
                    json=template_payload,
                    headers=self._headers(),
                )

                if response.status_code in [200, 201]:
                    data = response.json()
                    return data.get("id")
                else:
                    print(f"  ✗ Template creation failed: HTTP {response.status_code}")
                    print(f"    {response.text}")
                    return None

        except Exception as e:
            print(f"  ✗ Error creating template: {e}")
            return None

    def get_deployment_by_name(self, name: str) -> Optional[dict]:
        """Get deployment by name if it exists."""
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.get(
                    f"{self.base_url}/api/apps/deployments",
                    headers=self._headers(),
                )
                if response.status_code == 200:
                    deployments = response.json()
                    for deployment in deployments:
                        if deployment.get("name") == name:
                            return deployment
        except Exception as e:
            print(f"  ⚠ Error listing deployments: {e}")
        return None

    def deploy_kaizen(
        self,
        deployment_name: str,
        template_id: str,
    ) -> Optional[dict]:
        """
        Deploy a Kaizen instance from template.

        Returns deployment dict if successful, None otherwise.
        """
        deploy_payload = {
            "name": deployment_name,
            "template_id": template_id,
            "min_copies": 1,
            "starting_copies": 1,
            "lb_port": 0,
        }

        try:
            with httpx.Client(verify=self.verify_ssl, timeout=120.0) as client:
                response = client.post(
                    f"{self.base_url}/api/apps/deploy_app",
                    json=deploy_payload,
                    headers=self._headers(),
                )

                if response.status_code in [200, 201]:
                    return response.json()
                else:
                    print(f"  ✗ Deployment failed: HTTP {response.status_code}")
                    print(f"    {response.text}")
                    return None

        except Exception as e:
            print(f"  ✗ Error deploying: {e}")
            return None

    def wait_for_deployment_healthy(
        self,
        deployment_id: str,
        access_path: str,
        timeout: int = 180,
        poll_interval: int = 5,
    ) -> bool:
        """Wait for deployment to become healthy and Kaizen API to respond."""
        start_time = time.time()

        # First wait for deployment status
        while time.time() - start_time < timeout:
            try:
                with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                    response = client.get(
                        f"{self.base_url}/api/apps/deployments/{deployment_id}",
                        headers=self._headers(),
                    )
                    if response.status_code == 200:
                        data = response.json()
                        status = data.get("status", "")
                        if status == "DEPLOYED":
                            break
                        elif status in ("FAILED", "ERROR"):
                            return False
            except Exception:
                pass
            time.sleep(poll_interval)
        else:
            return False  # Timed out waiting for DEPLOYED status

        # Now wait for Kaizen API to be ready
        kaizen_api_url = f"{self.base_url}{access_path}/api/agents"
        while time.time() - start_time < timeout:
            try:
                with httpx.Client(verify=self.verify_ssl, timeout=10.0) as client:
                    response = client.get(
                        kaizen_api_url,
                        headers=self._headers(),
                    )
                    # Any response (even 401) means API is up
                    if response.status_code in [200, 401, 403]:
                        return True
            except Exception:
                pass
            time.sleep(poll_interval)

        return False

    def check_kaizen_api_ready(self, access_path: str, timeout: int = 30) -> bool:
        """Quick check if Kaizen API is responding (for existing deployments)."""
        kaizen_api_url = f"{self.base_url}{access_path}/api/agents"
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with httpx.Client(verify=self.verify_ssl, timeout=10.0) as client:
                    response = client.get(
                        kaizen_api_url,
                        headers=self._headers(),
                    )
                    if response.status_code in [200, 401, 403]:
                        return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def create_demo_agent(self, access_path: str, api_key: str = "") -> bool:
        """
        Create Demo Agent in a Kaizen instance.

        Args:
            access_path: The access path for the Kaizen deployment (e.g., /runtime/apps/xxx)
            api_key: Anthropic API key for the agent (required for Claude models)

        Returns:
            True if agent created successfully, False otherwise.
        """
        # Use Claude if API key provided, otherwise use local model config
        if api_key:
            llm_config = {
                "model": "claude-sonnet-4-20250514",
                "temperature": 0.0,
                "timeout": 120,
            }
            llm_api_key = api_key
        else:
            # Fallback to local model (may not work if no inference server running)
            llm_config = {
                "model": "openai/Qwen3-Coder-30B-A3B-Instruct",
                "base_url": "https://host.docker.internal:61109/v1",
                "temperature": 0.0,
                "timeout": 120,
                "native_tool_calling": True,
            }
            llm_api_key = "not-needed"

        # Demo Agent configuration
        demo_agent_payload = {
            "name": "Demo Agent",
            "description": "Pre-configured demo agent for Kaizen AI Assistant",
            "agent_config": {
                "llm": llm_config,
                "tools": [
                    {"name": "BashTool", "params": {}},
                    {"name": "FileEditorTool", "params": {}},
                    {"name": "TaskTrackerTool", "params": {}},
                ],
            },
            "llm_api_key": llm_api_key,
            "custom_instructions": """You are the Demo Agent, a helpful AI assistant for demonstrating Kaizen capabilities.

You can help users with:
- Writing and editing code
- Running bash commands
- Managing tasks and tracking progress

Be helpful, concise, and demonstrate the power of AI-assisted development.""",
        }

        # Kaizen API is at {access_path}/api/agents
        kaizen_api_url = f"{self.base_url}{access_path}/api/agents"

        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                # First check if Demo Agent already exists
                response = client.get(
                    kaizen_api_url,
                    headers=self._headers(),
                )
                existing_agent_id = None
                if response.status_code == 200:
                    agents = response.json().get("agents", [])
                    for agent in agents:
                        if agent.get("name") == "Demo Agent":
                            existing_agent_id = agent.get("id")
                            break

                if existing_agent_id:
                    # Update existing agent with new config (especially API key)
                    # Use PUT (not PATCH) as required by Kaizen API
                    update_url = f"{kaizen_api_url}/{existing_agent_id}"
                    response = client.put(
                        update_url,
                        json=demo_agent_payload,
                        headers=self._headers(),
                    )
                    if response.status_code in [200, 201]:
                        return True
                    else:
                        # Update failed, agent exists but couldn't update
                        return False
                else:
                    # Create the Demo Agent
                    response = client.post(
                        kaizen_api_url,
                        json=demo_agent_payload,
                        headers=self._headers(),
                    )

                    if response.status_code in [200, 201]:
                        return True
                    else:
                        print(f"      ⚠ Could not create Demo Agent: HTTP {response.status_code}")
                        return False

        except Exception as e:
            print(f"      ⚠ Error creating Demo Agent: {e}")
            return False

    def get_demo_agent_id(self, access_path: str) -> Optional[str]:
        """Get the ID of the Demo Agent in a Kaizen instance."""
        kaizen_api_url = f"{self.base_url}{access_path}/api/agents"
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.get(
                    kaizen_api_url,
                    headers=self._headers(),
                )
                if response.status_code == 200:
                    agents = response.json().get("agents", [])
                    for agent in agents:
                        if agent.get("name") == "Demo Agent":
                            return agent.get("id")
        except Exception:
            pass
        return None

    def add_mcp_server_to_agent(
        self,
        access_path: str,
        agent_id: str,
        server_name: str,
        server_url: str,
        description: Optional[str] = None,
        timeout: int = 30,
    ) -> bool:
        """
        Add an MCP server to an agent in Kaizen.

        Args:
            access_path: The Kaizen deployment access path
            agent_id: The agent ID to add the MCP server to
            server_name: Name for the MCP server
            server_url: URL of the MCP server (must be http:// not https://)
            description: Optional description
            timeout: Request timeout in seconds

        Returns:
            True if successful, False otherwise.
        """
        kaizen_api_url = f"{self.base_url}{access_path}/api/agents/{agent_id}/mcp-servers"
        
        payload = {
            "name": server_name,
            "url": server_url,
            "headers": {},
            "description": description or f"MCP server: {server_name}",
            "timeout": timeout,
        }

        try:
            with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
                response = client.post(
                    kaizen_api_url,
                    json=payload,
                    headers=self._headers(),
                )
                if response.status_code in [200, 201]:
                    return True
                elif response.status_code == 400:
                    # Server might already exist
                    detail = response.json().get("detail", "")
                    if "already exists" in detail.lower():
                        return True
                    print(f"      ⚠ Failed to add MCP server: {detail}")
                    return False
                else:
                    print(f"      ⚠ Failed to add MCP server: HTTP {response.status_code}")
                    return False

        except Exception as e:
            print(f"      ⚠ Error adding MCP server: {e}")
            return False

    def attach_toolshed_mcp_to_agent(
        self,
        access_path: str,
        agent_id: str,
        deployments: List["ToolDeployment"],
    ) -> int:
        """
        Attach deployed Toolshed MCP servers to an agent.

        Args:
            access_path: The Kaizen deployment access path
            agent_id: The agent ID
            deployments: List of ToolDeployment objects to attach

        Returns:
            Number of successfully attached MCP servers.
        """
        attached = 0
        for deployment in deployments:
            if not deployment.url:
                continue

            # Convert URL for Docker networking if needed
            # The deployment URL is typically something like http://host:port/mcp
            # We need to ensure it's accessible from within the Kaizen container
            mcp_url = deployment.url
            if not mcp_url.endswith("/mcp"):
                mcp_url = mcp_url.rstrip("/") + "/mcp"

            success = self.add_mcp_server_to_agent(
                access_path=access_path,
                agent_id=agent_id,
                server_name=deployment.name,
                server_url=mcp_url,
                description=f"Toolshed MCP: {deployment.name}",
            )
            if success:
                attached += 1

        return attached


class KeycloakUserManager:
    """Manages Keycloak user creation via Docker exec."""

    def __init__(
        self,
        container_name: str = "default_kamiwaza-keycloak-web",
        realm: str = "kamiwaza",
    ):
        self.container_name = container_name
        self.realm = realm
        self._configured = False

    def configure(self) -> bool:
        """Configure kcadm CLI with admin credentials."""
        try:
            subprocess.run(
                [
                    "docker", "exec", self.container_name,
                    "/opt/keycloak/bin/kcadm.sh", "config", "credentials",
                    "--server", "http://localhost:8080",
                    "--realm", "master",
                    "--user", "admin",
                    "--password", "kamiwaza-admin",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self._configured = True
            return True
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Failed to configure Keycloak CLI: {e.stderr}")
            return False

    def user_exists(self, username: str) -> bool:
        """Check if user exists in Keycloak."""
        try:
            result = subprocess.run(
                [
                    "docker", "exec", self.container_name,
                    "/opt/keycloak/bin/kcadm.sh", "get", "users",
                    "-r", self.realm,
                    "--query", f"username={username}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            users = json.loads(result.stdout)
            return len(users) > 0
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return False

    def create_analyst_user(
        self,
        email: str,
        password: str = "kamiwaza",
        roles: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Create analyst user in Keycloak with viewer/user roles.

        This creates the user directly in Keycloak (not in Kamiwaza local store),
        suitable for SSO-only access to Kaizen.

        Returns:
            Tuple of (success, message)
        """
        if roles is None:
            roles = ["viewer", "user"]

        username = email.split("@")[0]
        first_name = username.title()

        # Check if user exists
        if self.user_exists(username):
            return True, f"Analyst user {email} already exists in Keycloak"

        try:
            # Create user
            subprocess.run(
                [
                    "docker", "exec", self.container_name,
                    "/opt/keycloak/bin/kcadm.sh", "create", "users",
                    "-r", self.realm,
                    "-s", f"username={username}",
                    "-s", f"email={email}",
                    "-s", f"firstName={first_name}",
                    "-s", "lastName=User",
                    "-s", "enabled=true",
                    "-s", "emailVerified=true",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            # Set password
            subprocess.run(
                [
                    "docker", "exec", self.container_name,
                    "/opt/keycloak/bin/kcadm.sh", "set-password",
                    "-r", self.realm,
                    "--username", username,
                    "--new-password", password,
                ],
                capture_output=True,
                check=True,
            )

            # Assign roles
            for role in roles:
                subprocess.run(
                    [
                        "docker", "exec", self.container_name,
                        "/opt/keycloak/bin/kcadm.sh", "add-roles",
                        "-r", self.realm,
                        "--uusername", username,
                        "--rolename", role,
                    ],
                    capture_output=True,
                    check=False,  # Don't fail if role doesn't exist
                )

            return True, f"Created analyst user {email} with roles: {', '.join(roles)}"

        except subprocess.CalledProcessError as e:
            return False, f"Failed to create analyst user: {e.stderr}"


def read_csv(csv_path: Path) -> List[UserEntry]:
    """Read user entries from CSV file."""
    users = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("email", "").strip().lower()
                role = row.get("role", "analyst").strip().lower()

                if not email:
                    continue

                if role not in ("operator", "analyst"):
                    print(f"  ⚠ Invalid role '{role}' for {email}, defaulting to 'analyst'")
                    role = "analyst"

                users.append(UserEntry(email=email, role=role))

        return users
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        sys.exit(1)


def provision_operator(
    user: UserEntry,
    kamiwaza: KamiwazaClient,
    kaizen_template_id: str,
    user_password: str,
    anthropic_api_key: str = "",
    tool_deployments: Optional[List[ToolDeployment]] = None,
) -> ProvisioningResult:
    """Provision an operator user with Kaizen instance."""
    success, message = kamiwaza.create_operator_user(
        username=user.username,
        email=user.email,
        password=user_password,
    )

    if not success:
        return ProvisioningResult(
            email=user.email,
            role="operator",
            status="failed",
            message=message,
        )

    print(f"  ✓ {message}")

    # Operators also get a Kaizen instance (they have analyst role)
    deployment_name = f"{user.username} kaizen"

    # Check for existing deployment
    existing_deployment = kamiwaza.get_deployment_by_name(deployment_name)
    if existing_deployment:
        deployment_id = existing_deployment.get("id")
        access_path = existing_deployment.get(
            "access_path", f"/runtime/apps/{deployment_id}"
        )
        url = f"{kamiwaza.base_url}{access_path}"
        print(f"    ℹ Deployment already exists: {deployment_name}")

        # Ensure Demo Agent exists even for existing deployments
        print(f"      ⏳ Ensuring Demo Agent is configured...")
        if kamiwaza.check_kaizen_api_ready(access_path, timeout=30):
            if kamiwaza.create_demo_agent(access_path, anthropic_api_key):
                print(f"      ✓ Demo Agent ready")
            else:
                print(f"      ℹ Demo Agent already exists")

            # Attach Toolshed MCP servers to Demo Agent
            if tool_deployments:
                agent_id = kamiwaza.get_demo_agent_id(access_path)
                if agent_id:
                    attached = kamiwaza.attach_toolshed_mcp_to_agent(
                        access_path, agent_id, tool_deployments
                    )
                    if attached > 0:
                        print(f"      ✓ Attached {attached} MCP tool(s)")
        else:
            print(f"      ⚠ Kaizen not responding, Demo Agent check skipped")

        return ProvisioningResult(
            email=user.email,
            role="operator",
            status="success",
            message="Operator ready with Kaizen instance",
            deployment_url=url,
        )

    # Deploy Kaizen instance from shared template
    deployment = kamiwaza.deploy_kaizen(deployment_name, kaizen_template_id)
    if not deployment:
        return ProvisioningResult(
            email=user.email,
            role="operator",
            status="failed",
            message="User created but failed to deploy Kaizen instance",
        )

    deployment_id = deployment.get("id")
    access_path = deployment.get("access_path") or f"/runtime/apps/{deployment_id}"
    url = f"{kamiwaza.base_url}{access_path}"

    print(f"    ✓ Deployed Kaizen instance: {deployment_name}")
    print(f"      URL: {url}")

    # Wait for deployment to be healthy, then create Demo Agent
    print(f"      ⏳ Waiting for Kaizen to be ready...")
    if kamiwaza.wait_for_deployment_healthy(deployment_id, access_path, timeout=240):
        if kamiwaza.create_demo_agent(access_path, anthropic_api_key):
            print(f"      ✓ Demo Agent created")

            # Attach Toolshed MCP servers to Demo Agent
            if tool_deployments:
                agent_id = kamiwaza.get_demo_agent_id(access_path)
                if agent_id:
                    attached = kamiwaza.attach_toolshed_mcp_to_agent(
                        access_path, agent_id, tool_deployments
                    )
                    if attached > 0:
                        print(f"      ✓ Attached {attached} MCP tool(s)")
        else:
            print(f"      ⚠ Demo Agent creation skipped (can be added manually)")
    else:
        print(f"      ⚠ Kaizen not ready in time, Demo Agent skipped")

    return ProvisioningResult(
        email=user.email,
        role="operator",
        status="success",
        message="Operator created with Kaizen instance",
        deployment_url=url,
    )


def provision_analyst(
    user: UserEntry,
    kamiwaza: KamiwazaClient,
    keycloak: KeycloakUserManager,
    kaizen_template_id: str,
    user_password: str,
    anthropic_api_key: str = "",
    tool_deployments: Optional[List[ToolDeployment]] = None,
) -> ProvisioningResult:
    """Provision an analyst user with Kaizen instance."""
    # Step 1: Create Keycloak user
    success, message = keycloak.create_analyst_user(
        email=user.email,
        password=user_password,
    )

    if not success:
        return ProvisioningResult(
            email=user.email,
            role="analyst",
            status="failed",
            message=message,
        )

    print(f"    ✓ {message}")

    # Step 2: Check for existing deployment
    deployment_name = f"{user.username} kaizen"
    existing_deployment = kamiwaza.get_deployment_by_name(deployment_name)
    if existing_deployment:
        deployment_id = existing_deployment.get("id")
        access_path = existing_deployment.get(
            "access_path", f"/runtime/apps/{deployment_id}"
        )
        url = f"{kamiwaza.base_url}{access_path}"
        print(f"    ℹ Deployment already exists: {deployment_name}")

        # Ensure Demo Agent exists even for existing deployments
        print(f"      ⏳ Ensuring Demo Agent is configured...")
        if kamiwaza.check_kaizen_api_ready(access_path, timeout=30):
            if kamiwaza.create_demo_agent(access_path, anthropic_api_key):
                print(f"      ✓ Demo Agent ready")
            else:
                print(f"      ℹ Demo Agent already exists")

            # Attach Toolshed MCP servers to Demo Agent
            if tool_deployments:
                agent_id = kamiwaza.get_demo_agent_id(access_path)
                if agent_id:
                    attached = kamiwaza.attach_toolshed_mcp_to_agent(
                        access_path, agent_id, tool_deployments
                    )
                    if attached > 0:
                        print(f"      ✓ Attached {attached} MCP tool(s)")
        else:
            print(f"      ⚠ Kaizen not responding, Demo Agent check skipped")

        return ProvisioningResult(
            email=user.email,
            role="analyst",
            status="success",
            message="Kaizen instance ready with Demo Agent",
            deployment_url=url,
        )

    # Step 3: Deploy Kaizen instance from shared template
    deployment = kamiwaza.deploy_kaizen(deployment_name, kaizen_template_id)
    if not deployment:
        return ProvisioningResult(
            email=user.email,
            role="analyst",
            status="failed",
            message="Failed to deploy Kaizen instance",
        )

    deployment_id = deployment.get("id")
    access_path = deployment.get("access_path") or f"/runtime/apps/{deployment_id}"
    url = f"{kamiwaza.base_url}{access_path}"

    print(f"    ✓ Deployed Kaizen instance")
    print(f"      URL: {url}")

    # Wait for deployment to be healthy, then create Demo Agent
    print(f"      ⏳ Waiting for Kaizen to be ready...")
    if kamiwaza.wait_for_deployment_healthy(deployment_id, access_path, timeout=240):
        if kamiwaza.create_demo_agent(access_path, anthropic_api_key):
            print(f"      ✓ Demo Agent created")

            # Attach Toolshed MCP servers to Demo Agent
            if tool_deployments:
                agent_id = kamiwaza.get_demo_agent_id(access_path)
                if agent_id:
                    attached = kamiwaza.attach_toolshed_mcp_to_agent(
                        access_path, agent_id, tool_deployments
                    )
                    if attached > 0:
                        print(f"      ✓ Attached {attached} MCP tool(s)")
        else:
            print(f"      ⚠ Demo Agent creation skipped (can be added manually)")
    else:
        print(f"      ⚠ Kaizen not ready in time, Demo Agent skipped")

    return ProvisioningResult(
        email=user.email,
        role="analyst",
        status="success",
        message="Kaizen instance deployed with Demo Agent",
        deployment_url=url,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Unified User Provisioning for Kamiwaza and Kaizen"
    )
    parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="Path to CSV file with email,role columns",
    )
    parser.add_argument(
        "--kaizen-source",
        type=Path,
        default=Path("/Users/steffenmerten/Code/kaizen-v3/apps/kaizenv3"),
        help="Path to kaizen-v3/apps/kaizenv3 source (default: %(default)s)",
    )
    parser.add_argument(
        "--kamiwaza-url",
        default=os.environ.get("KAMIWAZA_URL", "https://localhost"),
        help="Kamiwaza base URL (default: from KAMIWAZA_URL env or https://localhost)",
    )
    parser.add_argument(
        "--kamiwaza-username",
        default=os.environ.get("KAMIWAZA_USERNAME", "admin"),
        help="Kamiwaza admin username (default: from KAMIWAZA_USERNAME env or admin)",
    )
    parser.add_argument(
        "--kamiwaza-password",
        default=os.environ.get("KAMIWAZA_PASSWORD", "kamiwaza"),
        help="Kamiwaza admin password (default: from KAMIWAZA_PASSWORD env)",
    )
    parser.add_argument(
        "--user-password",
        default=os.environ.get("DEFAULT_USER_PASSWORD", "kamiwaza"),
        help="Default password for created users (default: from DEFAULT_USER_PASSWORD env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--anthropic-api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key for Demo Agent (default: from ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--tools-source",
        type=Path,
        default=Path("/Users/steffenmerten/Code/kamiwaza-extensions-geo-tools"),
        help="Path to kamiwaza-extensions-geo-tools for MCP tool templates (default: %(default)s)",
    )
    parser.add_argument(
        "--kamiwaza-db-path",
        default=os.environ.get("KAMIWAZA_DB_PATH", "/opt/kamiwaza/db-lite/kamiwaza.db"),
        help="Path to Kamiwaza SQLite database for template registration (default: from KAMIWAZA_DB_PATH env)",
    )
    parser.add_argument(
        "--skip-toolshed",
        action="store_true",
        help="Skip Toolshed tool deployment",
    )

    args = parser.parse_args()

    # Read CSV
    print(f"\n📄 Reading CSV: {args.csv}")
    users = read_csv(args.csv)
    if not users:
        print("✗ No users found in CSV")
        sys.exit(1)

    operators = [u for u in users if u.is_operator()]
    analysts = [u for u in users if u.is_analyst()]

    print(f"✓ Found {len(users)} user(s):")
    print(f"  - Operators: {len(operators)}")
    print(f"  - Analysts: {len(analysts)}")

    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made\n")
        for user in users:
            if user.is_operator():
                print(f"Would create operator: {user.email}")
                print(f"  - Username: {user.username}")
                print(f"  - Roles: admin, developer, analyst, viewer, user")
                print(f"  - Deploy Kaizen instance: {user.username} kaizen")
            else:
                print(f"Would create analyst: {user.email}")
                print(f"  - Username: {user.username}")
                print(f"  - Roles: viewer, user")
                print(f"  - Deploy Kaizen instance: {user.username} kaizen")
            print()
        return

    # Initialize clients
    print("\n🔧 Initializing...")

    kamiwaza = KamiwazaClient(
        base_url=args.kamiwaza_url,
        username=args.kamiwaza_username,
        password=args.kamiwaza_password,
    )

    keycloak = KeycloakUserManager()

    # Authenticate to Kamiwaza
    print("\n🔐 Authenticating to Kamiwaza...")
    if not kamiwaza.authenticate():
        print("✗ Failed to authenticate to Kamiwaza")
        sys.exit(1)
    print(f"  ✓ Authenticated as {args.kamiwaza_username}")

    # Configure Keycloak CLI (only needed for analysts)
    if analysts:
        print("\n🔧 Configuring Keycloak CLI...")
        if not keycloak.configure():
            print("✗ Failed to configure Keycloak - is the container running?")
            sys.exit(1)
        print("  ✓ Keycloak CLI configured")

    # Check Kaizen source exists (needed for all users now since all get Kaizen)
    if not args.kaizen_source.exists():
        print(f"\n✗ Kaizen source not found: {args.kaizen_source}")
        print("  Please provide --kaizen-source path to kaizen-v3/apps/kaizenv3")
        sys.exit(1)

    # Check for Anthropic API key
    if not args.anthropic_api_key:
        print("\n⚠️  Warning: No Anthropic API key provided.")
        print("   Demo Agent will be configured with local model endpoint.")
        print("   If no local model is running, chats will fail.")
        print("   Use --anthropic-api-key or set ANTHROPIC_API_KEY env var.")

    # Create or get shared Kaizen template (ONE template for all deployments)
    print("\n📦 Setting up Kaizen template...")
    kaizen_template_name = "Kaizen"
    existing_template = kamiwaza.get_template_by_name(kaizen_template_name)

    if existing_template:
        kaizen_template_id = existing_template.get("id")
        print(f"  ✓ Using existing template: {kaizen_template_name}")
    else:
        kaizen_template_id = kamiwaza.create_kaizen_template(
            kaizen_template_name, args.kaizen_source
        )
        if not kaizen_template_id:
            print("✗ Failed to create Kaizen template")
            sys.exit(1)
        print(f"  ✓ Created template: {kaizen_template_name}")

    # Deploy Toolshed tools
    tool_deployments: List[ToolDeployment] = []
    if not args.skip_toolshed:
        print("\n🔧 Setting up Toolshed MCP tools...")
        
        toolshed = ToolshedManager(
            api_url=f"{args.kamiwaza_url}/api",
            db_path=args.kamiwaza_db_path,
            verify_ssl=False,
        )
        toolshed.set_token(kamiwaza.token)

        for tool_config in get_default_toolshed_tools():
            template_name = tool_config["template"]
            deployment_name = tool_config["name"]
            env_vars = tool_config.get("env_vars", {})

            print(f"  📦 {deployment_name}...")
            deployment = toolshed.ensure_tool_deployed(
                template_name=template_name,
                deployment_name=deployment_name,
                env_vars=env_vars,
                tools_source=args.tools_source,
            )
            if deployment:
                tool_deployments.append(deployment)
                print(f"    ✓ {deployment_name} ready at {deployment.url}")
            else:
                print(f"    ⚠ {deployment_name} failed to deploy")

        if tool_deployments:
            print(f"  ✓ {len(tool_deployments)} tool(s) ready for attachment to agents")
        else:
            print("  ⚠ No Toolshed tools deployed")
    else:
        print("\n⏭️  Skipping Toolshed tool deployment")

    # Process users
    results: List[ProvisioningResult] = []

    # Process operators first
    if operators:
        print("\n" + "=" * 60)
        print("PROVISIONING OPERATORS")
        print("=" * 60)

        for i, user in enumerate(operators, 1):
            print(f"\n[{i}/{len(operators)}] {user.email}")
            result = provision_operator(
                user, kamiwaza, kaizen_template_id, args.user_password,
                args.anthropic_api_key, tool_deployments
            )
            results.append(result)
            time.sleep(2)  # Brief pause between deployments

    # Process analysts
    if analysts:
        print("\n" + "=" * 60)
        print("PROVISIONING ANALYSTS")
        print("=" * 60)

        for i, user in enumerate(analysts, 1):
            print(f"\n[{i}/{len(analysts)}] {user.email}")
            result = provision_analyst(
                user,
                kamiwaza,
                keycloak,
                kaizen_template_id,
                args.user_password,
                args.anthropic_api_key,
                tool_deployments,
            )
            results.append(result)
            time.sleep(2)  # Brief pause between deployments

    # Summary
    print("\n" + "=" * 60)
    print("PROVISIONING SUMMARY")
    print("=" * 60)

    successful = [r for r in results if r.status == "success"]
    failed = [r for r in results if r.status == "failed"]

    print(f"\n✓ Successful: {len(successful)}/{len(results)}")

    # Group by role
    successful_ops = [r for r in successful if r.role == "operator"]
    successful_analysts = [r for r in successful if r.role == "analyst"]

    if successful_ops:
        print("\n  Operators (with Kaizen instances):")
        for r in successful_ops:
            url = r.deployment_url or "(no URL)"
            print(f"    - {r.email}")
            print(f"      URL: {url}")
            print(f"      Login: {r.email} / {args.user_password}")

    if successful_analysts:
        print("\n  Analysts (with Kaizen instances):")
        for r in successful_analysts:
            url = r.deployment_url or "(no URL)"
            print(f"    - {r.email}")
            print(f"      URL: {url}")
            print(f"      Login: {r.email} / {args.user_password}")

    if failed:
        print(f"\n✗ Failed: {len(failed)}/{len(results)}")
        for r in failed:
            print(f"  - {r.email} ({r.role}): {r.message}")

    print()


if __name__ == "__main__":
    main()
