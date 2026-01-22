"""
Kamiwaza Toolshed Tools Provisioner

Handles syncing and deploying MCP tools from the toolshed to Kamiwaza instances.
"""

import os
import httpx
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class KamiwazaToolsProvisionerError(Exception):
    """Exception raised during tool provisioning"""
    pass


class KamiwazaToolsProvisioner:
    """
    Handler for provisioning toolshed tools to Kamiwaza instances.

    This class syncs tools from the remote toolshed and deploys them to Kamiwaza.
    """

    def __init__(self, kamiwaza_url: str = None, username: str = None, password: str = None, toolshed_stage: str = "DEV"):
        """
        Initialize the tools provisioner.

        Args:
            kamiwaza_url: Kamiwaza instance URL (defaults to env var)
            username: Kamiwaza username (defaults to env var)
            password: Kamiwaza password (defaults to env var)
            toolshed_stage: Toolshed stage to sync from (LOCAL, DEV, STAGE, PROD)
        """
        self.kamiwaza_url = kamiwaza_url or os.environ.get("KAMIWAZA_URL", "https://localhost")
        self.kamiwaza_username = username or os.environ.get("KAMIWAZA_USERNAME", "admin")
        self.kamiwaza_password = password or os.environ.get("KAMIWAZA_PASSWORD", "kamiwaza")
        self.toolshed_stage = toolshed_stage

    def authenticate(self) -> Tuple[bool, Optional[str], str]:
        """
        Authenticate with Kamiwaza and get access token.

        Returns:
            Tuple of (success, token, error message)
        """
        try:
            logger.info(f"Authenticating with Kamiwaza at {self.kamiwaza_url}")

            with httpx.Client(verify=False, timeout=30.0) as client:
                auth_response = client.post(
                    f"{self.kamiwaza_url}/api/auth/token",
                    data={
                        "username": self.kamiwaza_username,
                        "password": self.kamiwaza_password
                    }
                )

                if auth_response.status_code != 200:
                    error_msg = f"Authentication failed: HTTP {auth_response.status_code}"
                    try:
                        # Try to get more details from response
                        error_detail = auth_response.text
                        if error_detail:
                            error_msg += f" - {error_detail[:200]}"
                    except:
                        pass
                    logger.error(error_msg)
                    return (False, None, error_msg)

                token = auth_response.json().get("access_token")
                if not token:
                    error_msg = "No access token in authentication response"
                    logger.error(error_msg)
                    return (False, None, error_msg)

                logger.info("✓ Authentication successful")
                return (True, token, "")

        except httpx.ConnectError as e:
            error_msg = f"Connection failed: Cannot reach Kamiwaza at {self.kamiwaza_url}. Check if the instance is running."
            logger.error(f"{error_msg} - {str(e)}")
            return (False, None, error_msg)
        except httpx.TimeoutException as e:
            error_msg = f"Connection timeout: Kamiwaza at {self.kamiwaza_url} is not responding"
            logger.error(f"{error_msg} - {str(e)}")
            return (False, None, error_msg)
        except Exception as e:
            error_msg = f"Authentication error: {str(e)}"
            logger.error(error_msg)
            return (False, None, error_msg)

    def sync_toolshed(self, token: str, callback=None) -> Tuple[bool, str]:
        """
        Sync tools from the remote toolshed to this Kamiwaza instance.

        Args:
            token: Kamiwaza API access token
            callback: Optional callback function(message: str) for log output

        Returns:
            Tuple of (success, message)
        """
        try:
            if callback:
                callback(f"  • Syncing toolshed from stage: {self.toolshed_stage}")

            with httpx.Client(verify=False, timeout=120.0) as client:
                sync_response = client.post(
                    f"{self.kamiwaza_url}/api/tool/remote/sync",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"stage": self.toolshed_stage},
                    json={}
                )

                if sync_response.status_code not in [200, 201]:
                    error_msg = f"Toolshed sync failed: HTTP {sync_response.status_code}"
                    if callback:
                        callback(f"    ✗ {error_msg}")
                    logger.error(error_msg)
                    return (False, error_msg)

                sync_result = sync_response.json()
                msg = f"    ✓ Toolshed sync completed: {sync_result.get('message', 'Success')}"
                if callback:
                    callback(msg)
                return (True, msg)

        except Exception as e:
            error_msg = f"Error syncing toolshed: {str(e)}"
            logger.error(error_msg)
            if callback:
                callback(f"    ✗ {error_msg}")
            return (False, error_msg)

    def get_available_tool_templates(self, token: str) -> Tuple[bool, List[Dict], str]:
        """
        Get list of available tool templates from Kamiwaza.

        Args:
            token: Kamiwaza API access token

        Returns:
            Tuple of (success, list of tool template dicts, error message)
        """
        try:
            logger.info("Fetching available tool templates")

            with httpx.Client(verify=False, timeout=30.0) as client:
                response = client.get(
                    f"{self.kamiwaza_url}/api/tool/templates",
                    headers={"Authorization": f"Bearer {token}"}
                )

                if response.status_code != 200:
                    error_msg = f"Failed to fetch tool templates: HTTP {response.status_code}"
                    logger.error(error_msg)
                    return (False, [], error_msg)

                tools = response.json()

                if not isinstance(tools, list):
                    error_msg = "Tool templates response is not a list"
                    logger.error(error_msg)
                    return (False, [], error_msg)

                logger.info(f"Successfully fetched {len(tools)} tool templates")
                return (True, tools, "")

        except Exception as e:
            error_msg = f"Error fetching tool templates: {str(e)}"
            logger.error(error_msg)
            return (False, [], error_msg)

    def deploy_tool(
        self,
        token: str,
        template_name: str,
        deployment_name: str = None,
        env_vars: Dict[str, str] = None,
        callback=None
    ) -> Tuple[bool, str]:
        """
        Deploy a single tool from a template.

        Args:
            token: Kamiwaza API access token
            template_name: Name of the tool template to deploy
            deployment_name: Custom name for the deployment (defaults to template name)
            env_vars: Environment variables for the tool
            callback: Optional callback function(message: str) for log output

        Returns:
            Tuple of (success, message)
        """
        deployment_name = deployment_name or template_name

        try:
            if callback:
                callback(f"  • Deploying tool: {template_name} as '{deployment_name}'")

            with httpx.Client(verify=False, timeout=120.0) as client:
                deploy_response = client.post(
                    f"{self.kamiwaza_url}/api/tool/deploy-template/{template_name}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "name": deployment_name,
                        "env_vars": env_vars or {}
                    }
                )

                if deploy_response.status_code not in [200, 201]:
                    error_msg = f"Tool deployment failed: HTTP {deploy_response.status_code}"
                    error_detail = deploy_response.text
                    if callback:
                        callback(f"    ✗ {error_msg}: {error_detail}")
                    logger.error(f"{error_msg}: {error_detail}")
                    return (False, error_msg)

                result = deploy_response.json()
                msg = f"    ✓ Deployed tool: {template_name}"
                if callback:
                    callback(msg)
                return (True, msg)

        except Exception as e:
            error_msg = f"Error deploying tool '{template_name}': {str(e)}"
            logger.error(error_msg)
            if callback:
                callback(f"    ✗ {error_msg}")
            return (False, error_msg)

    def provision_tools(
        self,
        callback=None,
        selected_tools: List[str] = None,
        sync_first: bool = True
    ) -> Tuple[bool, str, List[str]]:
        """
        Provision tools to Kamiwaza from the toolshed.

        Args:
            callback: Optional callback function(line: str) to receive log output
            selected_tools: Optional list of tool template names to deploy. If None, lists available tools.
            sync_first: Whether to sync the toolshed before deploying (default: True)

        Returns:
            Tuple of (success, summary_message, list of log lines)
        """
        log_lines = []

        def log(msg: str):
            log_lines.append(msg)
            if callback:
                callback(msg)
            logger.info(msg)

        try:
            log("=" * 60)
            log("KAMIWAZA TOOLSHED PROVISIONING")
            log("=" * 60)
            log("")

            # Step 1: Authenticate
            log("Step 1: Authenticating with Kamiwaza...")
            success, token, error_msg = self.authenticate()
            if not success:
                log(f"✗ {error_msg}")
                return (False, error_msg, log_lines)
            log("")

            # Step 2: Sync toolshed (if requested)
            if sync_first:
                log("Step 2: Syncing toolshed from remote...")
                success, msg = self.sync_toolshed(token, callback=log)
                if not success:
                    log(f"✗ Toolshed sync failed: {msg}")
                    log("⚠ Continuing with existing tool templates...")
                log("")

            # Step 3: Get available tool templates
            log("Step 3: Fetching available tool templates...")
            success, tools_data, error_msg = self.get_available_tool_templates(token)
            if not success:
                log(f"✗ {error_msg}")
                return (False, error_msg, log_lines)
            log(f"✓ Found {len(tools_data)} tool templates")
            log("")

            # If no tools selected, just list available tools
            if selected_tools is None or len(selected_tools) == 0:
                log("📋 Available tool templates:")
                for tool in tools_data:
                    log(f"  • {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}")
                log("")
                return (True, f"Listed {len(tools_data)} available tools", log_lines)

            # Step 4: Deploy selected tools
            log(f"Step 4: Deploying selected tools: {', '.join(selected_tools)}")
            deployed_count = 0
            failed_count = 0

            # Verify all selected tools exist
            available_tool_names = [tool.get('name') for tool in tools_data]
            for tool_name in selected_tools:
                if tool_name not in available_tool_names:
                    log(f"  ⚠ Warning: Tool '{tool_name}' not found in toolshed")

            for tool_name in selected_tools:
                if tool_name not in available_tool_names:
                    failed_count += 1
                    continue

                success, msg = self.deploy_tool(token, tool_name, callback=log)
                if success:
                    deployed_count += 1
                else:
                    failed_count += 1

            log("")
            log("=" * 60)
            log("PROVISIONING COMPLETE")
            log("=" * 60)
            log(f"✓ Successfully deployed: {deployed_count} tools")
            if failed_count > 0:
                log(f"✗ Failed to deploy: {failed_count} tools")
            log("")

            summary = f"Tool provisioning completed: {deployed_count} tools deployed, {failed_count} failed"
            return (True, summary, log_lines)

        except Exception as e:
            error_msg = f"✗ Provisioning error: {str(e)}"
            log(error_msg)
            return (False, error_msg, log_lines)
