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

    # Email
    email_provider: str = "ses"  # ses or smtp
    ses_region: str = "us-east-1"
    ses_from_email: str = "noreply@example.com"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@example.com"

    # AWS
    aws_default_region: str = "us-east-1"

    # Security & Validation
    allowed_regions: str = "us-east-1,us-west-2,eu-west-1,eu-central-1"
    allowed_instance_types: str = "t3.micro,t3.small,t3.medium,t3.large,t2.micro,t2.small"
    allow_access_key_auth: bool = False

    # Terraform
    terraform_binary: str = "terraform"
    jobs_workdir: str = "./jobs_workdir"

    @property
    def allowed_regions_list(self) -> List[str]:
        return [r.strip() for r in self.allowed_regions.split(",")]

    @property
    def allowed_instance_types_list(self) -> List[str]:
        return [t.strip() for t in self.allowed_instance_types.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
