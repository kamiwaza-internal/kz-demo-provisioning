from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    app_admin_user: str = "admin"
    app_admin_pass: str = "changeme123"
    secret_key: str = "dev-secret-key-change-in-production"

    # Database
    database_url: str = "sqlite:///./app.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Kamiwaza Connection
    kamiwaza_url: str = "https://localhost"
    kamiwaza_username: str = "admin"
    kamiwaza_password: str = "kamiwaza"
    kamiwaza_db_path: str = "/opt/kamiwaza/db-lite/kamiwaza.db"

    # Kamiwaza Package (RPM for RHEL 9)
    kamiwaza_package_url: str = "https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/rpm/rhel9/x86_64/kamiwaza_v0.9.2_rhel9_x86_64-online_rc18.rpm"

    # App Garden & Toolshed
    app_garden_url: str = "https://dev-info.kamiwaza.ai/garden/v2/apps.json"
    app_garden_api_url: str = ""  # API endpoint for publishing apps (e.g., https://app-garden.kamiwaza.ai/api)
    app_garden_api_key: str = ""  # API key for App Garden (if required)

    # Toolshed Configuration
    toolshed_stage: str = "DEV"  # LOCAL, DEV, STAGE, PROD
    toolshed_url_map: dict = {
        "LOCAL": "http://localhost:58888",
        "DEV": "https://dev-info.kamiwaza.ai",
        "STAGE": "https://stage-info.kamiwaza.ai",
        "PROD": "https://info.kamiwaza.ai",
    }

    # Script Paths
    kamiwaza_provision_script: str = "/Users/steffenmerten/Code/kamiwaza/scripts/provision_users.py"
    kaizen_source: str = "/Users/steffenmerten/Code/kaizen-v3/apps/kaizenv3"

    # User Credentials
    default_user_password: str = "kamiwaza"

    # AWS Authentication
    aws_auth_method: str = "assume_role"
    aws_assume_role_arn: str = "arn:aws:iam::916994818137:role/KamiwazaProvisionerRole"
    aws_external_id: str = ""
    aws_session_name: str = "kamiwaza-provisioner"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_sso_profile: str = ""
    aws_region: str = "us-west-2"
    aws_provisioning_method: str = "cdk"

    # API Keys
    anthropic_api_key: str = ""
    n2yo_api_key: str = ""
    datalastic_api_key: str = ""
    flightradar24_api_key: str = ""

    # Email
    email_provider: str = "ses"  # ses or smtp
    ses_region: str = "us-east-1"
    ses_from_email: str = "noreply@example.com"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@example.com"

    # AWS (legacy)
    aws_default_region: str = "us-east-1"

    # Security & Validation
    allowed_regions: str = "us-east-1,us-west-2,eu-west-1,eu-central-1"
    allowed_instance_types: str = "t3.xlarge,c7i.48xlarge"
    allow_access_key_auth: bool = False
    # SSH: list of CIDRs allowed to reach port 22 (default empty = no public SSH; use SSM). Comma-separated in env.
    ssh_allowed_cidrs: str = ""

    # Terraform
    terraform_binary: str = "terraform"
    jobs_workdir: str = "./jobs_workdir"

    @property
    def allowed_regions_list(self) -> List[str]:
        return [r.strip() for r in self.allowed_regions.split(",")]

    @property
    def allowed_instance_types_list(self) -> List[str]:
        return [t.strip() for t in self.allowed_instance_types.split(",")]

    @property
    def ssh_allowed_cidrs_list(self) -> List[str]:
        return [c.strip() for c in self.ssh_allowed_cidrs.split(",") if c.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
