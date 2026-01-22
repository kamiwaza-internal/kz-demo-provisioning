"""
Kamiwaza App and Tool Hydration Handler

Hydrates Kamiwaza with app garden applications and toolshed tools
after user provisioning is complete.
"""

import os
import httpx
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class KamiwazaAppHydrationError(Exception):
    """Exception raised during app/tool hydration"""
    pass


class KamiwazaAppHydrator:
    """
    Handler for hydrating Kamiwaza with app garden apps and toolshed tools.

    This class fetches app definitions from the app garden JSON endpoint
    and uploads them to a Kamiwaza instance via its API.
    """

    def __init__(self):
        # Configuration from environment variables
        self.kamiwaza_url = os.environ.get("KAMIWAZA_URL", "https://localhost")
        self.kamiwaza_username = os.environ.get("KAMIWAZA_USERNAME", "admin")
        self.kamiwaza_password = os.environ.get("KAMIWAZA_PASSWORD", "kamiwaza")
        self.app_garden_url = os.environ.get(
            "APP_GARDEN_URL",
            "https://dev-info.kamiwaza.ai/garden/v2/apps.json"
        )

    def fetch_app_garden_data(self) -> Tuple[bool, List[Dict], str]:
        """
        Fetch app definitions from the app garden JSON endpoint.

        Returns:
            Tuple of (success, list of app dicts, error message)
        """
        try:
            logger.info(f"Fetching app garden data from {self.app_garden_url}")

            with httpx.Client(timeout=30.0) as client:
                response = client.get(self.app_garden_url)

                if response.status_code != 200:
                    error_msg = f"Failed to fetch app garden data: HTTP {response.status_code}"
                    logger.error(error_msg)
                    return (False, [], error_msg)

                apps_data = response.json()

                if not isinstance(apps_data, list):
                    error_msg = "App garden data is not a list"
                    logger.error(error_msg)
                    return (False, [], error_msg)

                logger.info(f"Successfully fetched {len(apps_data)} apps from app garden")
                return (True, apps_data, "")

        except Exception as e:
            error_msg = f"Error fetching app garden data: {str(e)}"
            logger.error(error_msg)
            return (False, [], error_msg)

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
                    logger.error(error_msg)
                    return (False, None, error_msg)

                token = auth_response.json().get("access_token")
                if not token:
                    error_msg = "No access token in authentication response"
                    logger.error(error_msg)
                    return (False, None, error_msg)

                logger.info("✓ Authentication successful")
                return (True, token, "")

        except Exception as e:
            error_msg = f"Authentication error: {str(e)}"
            logger.error(error_msg)
            return (False, None, error_msg)

    def check_kamiwaza_health(self) -> Tuple[bool, str]:
        """
        Check if Kamiwaza is accessible and healthy.

        Returns:
            Tuple of (is_healthy, message)
        """
        try:
            with httpx.Client(verify=False, timeout=10.0) as client:
                response = client.get(f"{self.kamiwaza_url}/health")
                if response.status_code == 200:
                    return (True, "Kamiwaza is healthy")
                else:
                    return (False, f"Kamiwaza health check failed: HTTP {response.status_code}")
        except Exception as e:
            return (False, f"Cannot reach Kamiwaza: {str(e)}")

    def upload_app_template(
        self,
        token: str,
        app_data: Dict,
        callback=None
    ) -> Tuple[bool, str]:
        """
        Upload a single app template to Kamiwaza.

        Args:
            token: Kamiwaza API access token
            app_data: App definition dict from app garden
            callback: Optional callback function(message: str) for log output

        Returns:
            Tuple of (success, message)
        """
        app_name = app_data.get("name", "Unknown")

        try:
            if callback:
                callback(f"  • Uploading app: {app_name} v{app_data.get('version', '?')}")

            with httpx.Client(verify=False, timeout=60.0) as client:
                # Check if app already exists
                list_response = client.get(
                    f"{self.kamiwaza_url}/api/apps/app_templates",
                    headers={"Authorization": f"Bearer {token}"}
                )

                if list_response.status_code == 200:
                    existing_apps = list_response.json()
                    for existing_app in existing_apps:
                        if existing_app.get("name") == app_name:
                            # App already exists, update it
                            if callback:
                                callback(f"    ↻ App '{app_name}' already exists, updating...")

                            update_response = client.put(
                                f"{self.kamiwaza_url}/api/apps/app_templates/{existing_app['id']}",
                                headers={"Authorization": f"Bearer {token}"},
                                json=app_data
                            )

                            if update_response.status_code in [200, 204]:
                                msg = f"    ✓ Updated app: {app_name}"
                                if callback:
                                    callback(msg)
                                return (True, msg)
                            else:
                                error_msg = f"Failed to update app '{app_name}': HTTP {update_response.status_code}"
                                logger.warning(error_msg)
                                if callback:
                                    callback(f"    ✗ {error_msg}")
                                return (False, error_msg)

                # App doesn't exist, create it
                create_response = client.post(
                    f"{self.kamiwaza_url}/api/apps/app_templates",
                    headers={"Authorization": f"Bearer {token}"},
                    json=app_data
                )

                if create_response.status_code in [200, 201]:
                    msg = f"    ✓ Created app: {app_name}"
                    if callback:
                        callback(msg)
                    return (True, msg)
                else:
                    error_msg = f"Failed to create app '{app_name}': HTTP {create_response.status_code}"
                    logger.warning(error_msg)
                    if callback:
                        callback(f"    ✗ {error_msg}")
                    return (False, error_msg)

        except Exception as e:
            error_msg = f"Error uploading app '{app_name}': {str(e)}"
            logger.error(error_msg)
            if callback:
                callback(f"    ✗ {error_msg}")
            return (False, error_msg)

    def hydrate_apps_and_tools(
        self,
        callback=None,
        selected_apps=None
    ) -> Tuple[bool, str, List[str]]:
        """
        Hydrate Kamiwaza with apps and tools from app garden.

        Args:
            callback: Optional callback function(line: str) to receive log output
            selected_apps: Optional list of app names to deploy. If None, deploys all apps.

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
            log("KAMIWAZA APP & TOOL HYDRATION")
            log("=" * 60)
            log("")

            # Step 1: Check Kamiwaza health
            log("Step 1: Checking Kamiwaza health...")
            is_healthy, health_msg = self.check_kamiwaza_health()
            if not is_healthy:
                error_msg = f"Kamiwaza health check failed: {health_msg}"
                log(f"✗ {error_msg}")
                return (False, error_msg, log_lines)
            log(f"✓ {health_msg}")
            log("")

            # Step 2: Authenticate
            log("Step 2: Authenticating with Kamiwaza...")
            success, token, error_msg = self.authenticate()
            if not success:
                log(f"✗ {error_msg}")
                return (False, error_msg, log_lines)
            log("")

            # Step 3: Fetch app garden data
            log("Step 3: Fetching app garden data...")
            success, apps_data, error_msg = self.fetch_app_garden_data()
            if not success:
                log(f"✗ {error_msg}")
                return (False, error_msg, log_lines)
            log(f"✓ Found {len(apps_data)} apps in app garden")
            log("")

            # Filter apps if selected_apps is provided
            if selected_apps is not None and len(selected_apps) > 0:
                log(f"📋 Filtering to selected apps: {', '.join(selected_apps)}")
                apps_data = [app for app in apps_data if app.get("name") in selected_apps]
                log(f"✓ Will deploy {len(apps_data)} selected app(s)")
                log("")

                if len(apps_data) == 0:
                    log("⚠ No matching apps found in app garden")
                    return (True, "No matching apps to deploy", log_lines)

            # Step 4: Upload apps
            log("Step 4: Uploading apps to Kamiwaza...")
            uploaded_count = 0
            failed_count = 0

            for app_data in apps_data:
                success, msg = self.upload_app_template(token, app_data, callback=log)
                if success:
                    uploaded_count += 1
                else:
                    failed_count += 1

            log("")
            log("=" * 60)
            log("HYDRATION COMPLETE")
            log("=" * 60)
            log(f"✓ Successfully uploaded/updated: {uploaded_count} apps")
            if failed_count > 0:
                log(f"✗ Failed to upload: {failed_count} apps")
            log("")

            summary = f"App hydration completed: {uploaded_count} apps uploaded, {failed_count} failed"
            return (True, summary, log_lines)

        except Exception as e:
            error_msg = f"✗ Hydration error: {str(e)}"
            log(error_msg)
            return (False, error_msg, log_lines)
