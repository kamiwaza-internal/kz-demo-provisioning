from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(255), nullable=False)
    status = Column(String(50), default="pending")  # pending, queued, running, success, failed

    # Deployment Type
    deployment_type = Column(String(20), default="docker")  # docker or kamiwaza

    # Kamiwaza-specific Configuration
    kamiwaza_branch = Column(String(255), default="release/0.9.2", nullable=True)
    kamiwaza_github_token = Column(String(500), nullable=True)
    kamiwaza_repo = Column(String(500), default="https://github.com/kamiwaza-internal/kamiwaza.git", nullable=True)
    kamiwaza_deployment_mode = Column(String(20), default="lite", nullable=True)  # lite or full

    # AWS Configuration
    aws_region = Column(String(50), nullable=False)
    aws_auth_method = Column(String(20), nullable=False)  # assume_role or access_key
    assume_role_arn = Column(String(500), nullable=True)
    external_id = Column(String(255), nullable=True)
    session_name = Column(String(255), nullable=True)
    aws_account_id = Column(String(50), nullable=True)

    # Network Configuration
    vpc_id = Column(String(100), nullable=True)
    subnet_id = Column(String(100), nullable=True)
    security_group_ids = Column(JSON, nullable=True)  # List of SG IDs

    # EC2 Configuration
    key_pair_name = Column(String(255), nullable=True)
    instance_type = Column(String(50), nullable=False)
    volume_size_gb = Column(Integer, default=30)
    ami_id = Column(String(100), nullable=True)
    tags = Column(JSON, nullable=True)  # Dict of tags

    # Docker Configuration
    dockerhub_images = Column(JSON, nullable=False)  # List of container configs

    # User Configuration
    csv_file_id = Column(Integer, ForeignKey("job_files.id"), nullable=True)
    users_data = Column(JSON, nullable=True)  # Parsed CSV data

    # Outputs
    instance_id = Column(String(100), nullable=True)
    public_ip = Column(String(50), nullable=True)
    private_ip = Column(String(50), nullable=True)
    terraform_outputs = Column(JSON, nullable=True)

    # Kamiwaza deployment status
    kamiwaza_ready = Column(Boolean, default=False)
    kamiwaza_checked_at = Column(DateTime, nullable=True)
    kamiwaza_check_attempts = Column(Integer, default=0)

    # Notifications
    requester_email = Column(String(255), nullable=False)
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Relationships
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")
    csv_file = relationship("JobFile", foreign_keys=[csv_file_id])


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(20), default="info")  # info, warning, error, debug
    message = Column(Text, nullable=False)
    source = Column(String(50), default="system")  # system, terraform, docker, email

    job = relationship("Job", back_populates="logs")


class JobFile(Base):
    __tablename__ = "job_files"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), default="csv")  # csv, log, etc
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
