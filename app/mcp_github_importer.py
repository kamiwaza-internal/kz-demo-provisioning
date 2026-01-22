"""
MCP GitHub Importer

Handles validation and import of MCP servers from GitHub repositories.
Performs basic validation of MCP tool structure before registering to Kamiwaza.
"""

import httpx
import logging
from typing import Tuple, Dict, Optional, List
from urllib.parse import urlparse
import json
import re

logger = logging.getLogger(__name__)


class MCPGitHubImporterError(Exception):
    """Exception raised during MCP GitHub import"""
    pass


class MCPGitHubImporter:
    """
    Handler for importing and validating MCP tools from GitHub repositories.

    Validates MCP tool structure:
    - Checks for tool.json configuration file
    - Validates GitHub URL format
    - Fetches tool metadata
    """

    def __init__(self, github_token: Optional[str] = None):
        """
        Initialize the importer.

        Args:
            github_token: Optional GitHub personal access token for private repos
        """
        self.github_token = github_token
        self.required_files = ["tool.json"]

    def parse_github_url(self, github_url: str) -> Tuple[bool, Dict[str, str], str]:
        """
        Parse a GitHub URL to extract owner, repo, branch/ref, and path.

        Supports formats:
        - https://github.com/owner/repo
        - https://github.com/owner/repo/tree/branch/path/to/tool
        - https://github.com/owner/repo/blob/branch/path/to/file

        Args:
            github_url: GitHub repository or tree URL

        Returns:
            Tuple of (success, parsed_data dict, error_message)
        """
        try:
            github_url = github_url.strip()

            # Extract parts using regex
            # Pattern: https://github.com/owner/repo(/tree|/blob/branch(/path)?)?
            pattern = r'https://github\.com/([^/]+)/([^/]+)(?:/(?:tree|blob)/([^/]+)(/.*)?)?'
            match = re.match(pattern, github_url)

            if not match:
                return (False, {}, "Invalid GitHub URL format")

            owner, repo, branch, path = match.groups()

            # Remove .git suffix if present
            if repo.endswith('.git'):
                repo = repo[:-4]

            # Default to main branch if not specified
            if not branch:
                branch = "main"

            # Clean up path
            if path:
                path = path.lstrip('/')
            else:
                path = ""

            parsed_data = {
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "path": path,
                "url": github_url
            }

            logger.info(f"Parsed GitHub URL: {parsed_data}")
            return (True, parsed_data, "")

        except Exception as e:
            error_msg = f"Error parsing GitHub URL: {str(e)}"
            logger.error(error_msg)
            return (False, {}, error_msg)

    def fetch_file_from_github(
        self,
        owner: str,
        repo: str,
        path: str,
        branch: str = "main"
    ) -> Tuple[bool, Optional[str], str]:
        """
        Fetch a file's content from GitHub via raw content URL.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path within the repo
            branch: Branch name

        Returns:
            Tuple of (success, file_content, error_message)
        """
        try:
            # Use raw.githubusercontent.com for file content
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"

            logger.info(f"Fetching file from: {raw_url}")

            headers = {}
            if self.github_token:
                headers["Authorization"] = f"token {self.github_token}"

            with httpx.Client(timeout=30.0) as client:
                response = client.get(raw_url, headers=headers)

                if response.status_code == 404:
                    return (False, None, f"File not found: {path}")
                elif response.status_code != 200:
                    return (False, None, f"GitHub API error: HTTP {response.status_code}")

                return (True, response.text, "")

        except Exception as e:
            error_msg = f"Error fetching file from GitHub: {str(e)}"
            logger.error(error_msg)
            return (False, None, error_msg)

    def validate_tool_json(self, tool_json_content: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Validate tool.json content and parse it.

        Args:
            tool_json_content: Raw JSON content as string

        Returns:
            Tuple of (success, parsed_json, error_message)
        """
        try:
            # Parse JSON
            tool_config = json.loads(tool_json_content)

            # Check required fields
            required_fields = ["name"]
            missing_fields = [field for field in required_fields if field not in tool_config]

            if missing_fields:
                return (False, None, f"Missing required fields in tool.json: {', '.join(missing_fields)}")

            # Validate field types
            if not isinstance(tool_config["name"], str):
                return (False, None, "Field 'name' must be a string")

            logger.info(f"Validated tool.json for tool: {tool_config['name']}")
            return (True, tool_config, "")

        except json.JSONDecodeError as e:
            return (False, None, f"Invalid JSON in tool.json: {str(e)}")
        except Exception as e:
            return (False, None, f"Error validating tool.json: {str(e)}")

    def validate_mcp_repo(
        self,
        github_url: str
    ) -> Tuple[bool, Optional[Dict], List[str]]:
        """
        Validate an MCP tool repository structure.

        Performs basic validation:
        1. Parses GitHub URL
        2. Fetches tool.json
        3. Validates tool.json structure

        Args:
            github_url: GitHub repository or tree URL

        Returns:
            Tuple of (success, tool_config dict, list of validation log lines)
        """
        log_lines = []

        def log(msg: str):
            log_lines.append(msg)
            logger.info(msg)

        try:
            log("=" * 60)
            log("MCP TOOL VALIDATION")
            log("=" * 60)
            log(f"GitHub URL: {github_url}")
            log("")

            # Step 1: Parse GitHub URL
            log("Step 1: Parsing GitHub URL...")
            success, parsed, error_msg = self.parse_github_url(github_url)
            if not success:
                log(f"✗ {error_msg}")
                return (False, None, log_lines)

            log(f"✓ Repository: {parsed['owner']}/{parsed['repo']}")
            log(f"✓ Branch: {parsed['branch']}")
            if parsed['path']:
                log(f"✓ Path: {parsed['path']}")
            log("")

            # Step 2: Fetch tool.json
            log("Step 2: Fetching tool.json...")
            tool_json_path = f"{parsed['path']}/tool.json" if parsed['path'] else "tool.json"
            success, content, error_msg = self.fetch_file_from_github(
                parsed['owner'],
                parsed['repo'],
                tool_json_path,
                parsed['branch']
            )

            if not success:
                log(f"✗ {error_msg}")
                log("")
                log("Note: Make sure your repository contains a tool.json file")
                log("Example structure:")
                log("  ├── tool.json       (required)")
                log("  ├── main.py or index.js")
                log("  ├── requirements.txt or package.json")
                log("  └── README.md")
                return (False, None, log_lines)

            log(f"✓ Found tool.json ({len(content)} bytes)")
            log("")

            # Step 3: Validate tool.json
            log("Step 3: Validating tool.json...")
            success, tool_config, error_msg = self.validate_tool_json(content)
            if not success:
                log(f"✗ {error_msg}")
                return (False, None, log_lines)

            log(f"✓ Tool name: {tool_config['name']}")
            if 'version' in tool_config:
                log(f"✓ Version: {tool_config['version']}")
            if 'description' in tool_config:
                log(f"✓ Description: {tool_config['description']}")
            log("")

            # Add GitHub metadata to tool config
            tool_config['github_url'] = github_url
            tool_config['github_owner'] = parsed['owner']
            tool_config['github_repo'] = parsed['repo']
            tool_config['github_branch'] = parsed['branch']
            tool_config['github_path'] = parsed['path']

            log("=" * 60)
            log("VALIDATION COMPLETE")
            log("=" * 60)
            log(f"✓ Tool '{tool_config['name']}' is valid and ready to import")
            log("")

            return (True, tool_config, log_lines)

        except Exception as e:
            error_msg = f"✗ Validation error: {str(e)}"
            log(error_msg)
            return (False, None, log_lines)

    def import_to_kamiwaza(
        self,
        kamiwaza_url: str,
        kamiwaza_token: str,
        tool_config: Dict,
        github_url: str
    ) -> Tuple[bool, str]:
        """
        Import/register an MCP tool to Kamiwaza's toolshed.

        Args:
            kamiwaza_url: Kamiwaza instance URL
            kamiwaza_token: Authentication token
            tool_config: Parsed tool configuration
            github_url: GitHub repository URL

        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info(f"Importing tool '{tool_config['name']}' to Kamiwaza at {kamiwaza_url}")

            # Prepare import payload
            import_payload = {
                "name": tool_config['name'],
                "github_url": github_url,
                "branch": tool_config.get('github_branch', 'main'),
                "path": tool_config.get('github_path', ''),
                "metadata": tool_config
            }

            # Call Kamiwaza API to register the tool
            with httpx.Client(verify=False, timeout=60.0) as client:
                response = client.post(
                    f"{kamiwaza_url}/api/tool/import-from-github",
                    headers={"Authorization": f"Bearer {kamiwaza_token}"},
                    json=import_payload
                )

                if response.status_code in [200, 201]:
                    return (True, f"Successfully imported tool '{tool_config['name']}' to Kamiwaza")
                else:
                    error_detail = response.text if response.text else f"HTTP {response.status_code}"
                    return (False, f"Failed to import tool to Kamiwaza: {error_detail}")

        except Exception as e:
            error_msg = f"Error importing tool to Kamiwaza: {str(e)}"
            logger.error(error_msg)
            return (False, error_msg)
