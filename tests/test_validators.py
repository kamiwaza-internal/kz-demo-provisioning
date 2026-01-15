import pytest
from pydantic import ValidationError
from app.schemas import JobCreate, ContainerConfig


class TestContainerConfig:
    """Test ContainerConfig validation"""

    def test_valid_container(self):
        """Test valid container configuration"""
        config = ContainerConfig(
            name="webapp",
            image="nginx:latest",
            ports=["80:80"],
            environment={"ENV": "prod"},
            restart="unless-stopped"
        )

        assert config.name == "webapp"
        assert config.image == "nginx:latest"
        assert config.ports == ["80:80"]

    def test_minimal_container(self):
        """Test minimal container configuration"""
        config = ContainerConfig(
            name="app",
            image="alpine:latest"
        )

        assert config.name == "app"
        assert config.ports == []
        assert config.environment == {}

    def test_volume_validation_valid(self):
        """Test valid volume path"""
        config = ContainerConfig(
            name="app",
            image="nginx:latest",
            volumes=["/opt/app:/app"]
        )

        assert len(config.volumes) == 1

    def test_volume_validation_invalid(self):
        """Test invalid volume path (not under /opt/app)"""
        with pytest.raises(ValidationError, match="Host volumes must be under /opt/app"):
            ContainerConfig(
                name="app",
                image="nginx:latest",
                volumes=["/etc/passwd:/app"]
            )


class TestJobCreate:
    """Test JobCreate validation"""

    def test_valid_job(self):
        """Test valid job creation"""
        job = JobCreate(
            job_name="test-job",
            aws_region="us-east-1",
            aws_auth_method="assume_role",
            assume_role_arn="arn:aws:iam::123456789012:role/MyRole",
            instance_type="t3.micro",
            dockerhub_images=[
                ContainerConfig(name="web", image="nginx:latest")
            ],
            requester_email="user@example.com"
        )

        assert job.job_name == "test-job"
        assert job.aws_region == "us-east-1"

    def test_assume_role_requires_arn(self):
        """Test that AssumeRole requires role ARN"""
        with pytest.raises(ValidationError, match="assume_role_arn is required"):
            JobCreate(
                job_name="test",
                aws_region="us-east-1",
                aws_auth_method="assume_role",
                instance_type="t3.micro",
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="user@example.com"
            )

    def test_invalid_region(self):
        """Test invalid AWS region"""
        with pytest.raises(ValidationError, match="not in allowed list"):
            JobCreate(
                job_name="test",
                aws_region="invalid-region",
                aws_auth_method="assume_role",
                assume_role_arn="arn:aws:iam::123456789012:role/MyRole",
                instance_type="t3.micro",
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="user@example.com"
            )

    def test_invalid_instance_type(self):
        """Test invalid instance type"""
        with pytest.raises(ValidationError, match="not in allowed list"):
            JobCreate(
                job_name="test",
                aws_region="us-east-1",
                aws_auth_method="assume_role",
                assume_role_arn="arn:aws:iam::123456789012:role/MyRole",
                instance_type="m5.24xlarge",  # Not in allowed list
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="user@example.com"
            )

    def test_invalid_email(self):
        """Test invalid email format"""
        with pytest.raises(ValidationError):
            JobCreate(
                job_name="test",
                aws_region="us-east-1",
                aws_auth_method="assume_role",
                assume_role_arn="arn:aws:iam::123456789012:role/MyRole",
                instance_type="t3.micro",
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="not-an-email"
            )

    def test_volume_size_validation(self):
        """Test volume size bounds"""
        # Too small
        with pytest.raises(ValidationError):
            JobCreate(
                job_name="test",
                aws_region="us-east-1",
                aws_auth_method="assume_role",
                assume_role_arn="arn:aws:iam::123456789012:role/MyRole",
                instance_type="t3.micro",
                volume_size_gb=5,  # Min is 8
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="user@example.com"
            )

        # Too large
        with pytest.raises(ValidationError):
            JobCreate(
                job_name="test",
                aws_region="us-east-1",
                aws_auth_method="assume_role",
                assume_role_arn="arn:aws:iam::123456789012:role/MyRole",
                instance_type="t3.micro",
                volume_size_gb=2000,  # Max is 1000
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="user@example.com"
            )

    def test_invalid_auth_method(self):
        """Test invalid authentication method"""
        with pytest.raises(ValidationError):
            JobCreate(
                job_name="test",
                aws_region="us-east-1",
                aws_auth_method="invalid_method",
                instance_type="t3.micro",
                dockerhub_images=[
                    ContainerConfig(name="web", image="nginx:latest")
                ],
                requester_email="user@example.com"
            )

    def test_access_key_auth_when_disabled(self):
        """Test that access_key auth is rejected when disabled"""
        # This requires the settings to have allow_access_key_auth=False
        from app.config import settings
        original_value = settings.allow_access_key_auth
        try:
            settings.allow_access_key_auth = False

            with pytest.raises(ValidationError, match="Access key authentication is disabled"):
                JobCreate(
                    job_name="test",
                    aws_region="us-east-1",
                    aws_auth_method="access_key",
                    access_key="AKIAIOSFODNN7EXAMPLE",
                    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                    instance_type="t3.micro",
                    dockerhub_images=[
                        ContainerConfig(name="web", image="nginx:latest")
                    ],
                    requester_email="user@example.com"
                )
        finally:
            settings.allow_access_key_auth = original_value
