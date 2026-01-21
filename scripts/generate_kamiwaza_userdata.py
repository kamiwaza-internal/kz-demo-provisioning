#!/usr/bin/env python3
"""
Generate user data script for Kamiwaza EC2 deployment

This script creates a base64-encoded user data script that can be used
with the kz-demo-provisioning CDK deployment.

Usage:
    python3 scripts/generate_kamiwaza_userdata.py [options]

Example:
    python3 scripts/generate_kamiwaza_userdata.py \
        --branch develop \
        --github-token ghp_xxxx
"""

import argparse
import base64
import sys
from pathlib import Path


def generate_user_data(
    branch: str = "release/0.9.2",
    github_token: str = "",
    kamiwaza_root: str = "/opt/kamiwaza",
    environment_vars: dict = None
) -> str:
    """Generate user data script for Kamiwaza deployment"""

    # Read the deployment script
    script_path = Path(__file__).parent / "deploy_kamiwaza_full.sh"
    if not script_path.exists():
        print(f"Error: Deployment script not found at {script_path}", file=sys.stderr)
        sys.exit(1)

    deployment_script = script_path.read_text()

    # Build environment variable exports
    env_exports = []
    if branch:
        env_exports.append(f"export KAMIWAZA_BRANCH='{branch}'")
    if github_token:
        env_exports.append(f"export GITHUB_TOKEN='{github_token}'")
    if kamiwaza_root:
        env_exports.append(f"export KAMIWAZA_ROOT='{kamiwaza_root}'")

    # Add any custom environment variables
    if environment_vars:
        for key, value in environment_vars.items():
            env_exports.append(f"export {key}='{value}'")

    # Combine environment exports with the deployment script
    user_data = "#!/bin/bash\n\n"
    user_data += "# Environment variables\n"
    user_data += "\n".join(env_exports)
    user_data += "\n\n"
    user_data += deployment_script

    return user_data


def main():
    parser = argparse.ArgumentParser(
        description="Generate user data for Kamiwaza EC2 deployment"
    )
    parser.add_argument(
        "--branch",
        default="release/0.9.2",
        help="Git branch to deploy (default: release/0.9.2)"
    )
    parser.add_argument(
        "--github-token",
        default="",
        help="GitHub personal access token for private repository access"
    )
    parser.add_argument(
        "--kamiwaza-root",
        default="/opt/kamiwaza",
        help="Installation directory (default: /opt/kamiwaza)"
    )
    parser.add_argument(
        "--output",
        choices=["script", "base64"],
        default="base64",
        help="Output format: 'script' for raw bash, 'base64' for encoded (default: base64)"
    )
    parser.add_argument(
        "--output-file",
        help="Write output to file instead of stdout"
    )

    args = parser.parse_args()

    # Generate user data
    user_data = generate_user_data(
        branch=args.branch,
        github_token=args.github_token,
        kamiwaza_root=args.kamiwaza_root
    )

    # Format output
    if args.output == "base64":
        output = base64.b64encode(user_data.encode()).decode()
    else:
        output = user_data

    # Write output
    if args.output_file:
        Path(args.output_file).write_text(output)
        print(f"User data written to {args.output_file}")
    else:
        print(output)


if __name__ == "__main__":
    main()
