from pydantic import BaseModel, EmailStr, validator, Field
from typing import List, Dict, Optional
from datetime import datetime


class ContainerConfig(BaseModel):
    name: str
    image: str
    ports: Optional[List[str]] = []  # e.g., ["8080:80", "443:443"]
    environment: Optional[Dict[str, str]] = {}
    volumes: Optional[List[str]] = []  # e.g., ["/opt/app:/app"]
    command: Optional[str] = None
    restart: str = "unless-stopped"
    user_import_endpoint: Optional[str] = None  # e.g., "http://localhost:8080/api/users/import"

    @validator("volumes")
    def validate_volumes(cls, v):
        if v:
            for vol in v:
                if ":" in vol:
                    host_path = vol.split(":")[0]
                    if not host_path.startswith("/opt/app"):
                        raise ValueError(f"Host volumes must be under /opt/app, got: {host_path}")
        return v


class JobCreate(BaseModel):
    job_name: str = Field(..., min_length=1, max_length=255)
    aws_region: str
    aws_auth_method: str = Field(..., pattern="^(assume_role|access_key)$")

    # AssumeRole fields
    assume_role_arn: Optional[str] = None
    external_id: Optional[str] = None
    session_name: Optional[str] = "terraform-provisioning"

    # AccessKey fields (if enabled)
    access_key: Optional[str] = None
    secret_key: Optional[str] = None

    # Network
    vpc_id: Optional[str] = None
    subnet_id: Optional[str] = None
    security_group_ids: Optional[List[str]] = []

    # EC2
    key_pair_name: Optional[str] = None
    instance_type: str = "t3.micro"
    volume_size_gb: int = Field(default=30, ge=8, le=1000)
    ami_id: Optional[str] = None
    tags: Optional[Dict[str, str]] = {}

    # Docker
    dockerhub_images: List[ContainerConfig]

    # Notification
    requester_email: EmailStr

    @validator("aws_auth_method")
    def validate_auth_method(cls, v, values):
        from app.config import settings
        if v == "access_key" and not settings.allow_access_key_auth:
            raise ValueError("Access key authentication is disabled")
        return v

    @validator("assume_role_arn")
    def validate_assume_role(cls, v, values):
        if values.get("aws_auth_method") == "assume_role" and not v:
            raise ValueError("assume_role_arn is required when using AssumeRole")
        return v

    @validator("aws_region")
    def validate_region(cls, v):
        from app.config import settings
        if v not in settings.allowed_regions_list:
            raise ValueError(f"Region {v} not in allowed list: {settings.allowed_regions_list}")
        return v

    @validator("instance_type")
    def validate_instance_type(cls, v):
        from app.config import settings
        if v not in settings.allowed_instance_types_list:
            raise ValueError(f"Instance type {v} not in allowed list: {settings.allowed_instance_types_list}")
        return v


class JobResponse(BaseModel):
    id: int
    job_name: str
    status: str
    aws_region: str
    instance_type: str
    instance_id: Optional[str]
    public_ip: Optional[str]
    private_ip: Optional[str]
    requester_email: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class JobLogResponse(BaseModel):
    id: int
    timestamp: datetime
    level: str
    message: str
    source: str

    class Config:
        from_attributes = True


class UserRow(BaseModel):
    email: EmailStr
