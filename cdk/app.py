#!/usr/bin/env python3
"""
AWS CDK App for Kamiwaza EC2 Provisioning

This CDK app provisions EC2 instances for Kamiwaza deployments.
"""

import os
import json
import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    CfnOutput,
    Tags
)


class KamiwazaEC2Stack(Stack):
    """CDK Stack for provisioning EC2 instances"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get context parameters
        job_id = self.node.try_get_context("jobId")
        instance_type = self.node.try_get_context("instanceType") or "t3.medium"
        ami_id = self.node.try_get_context("amiId")
        vpc_id = self.node.try_get_context("vpcId")
        key_pair_name = self.node.try_get_context("keyPairName")
        user_data_b64 = self.node.try_get_context("userData")
        
        # Volume size - parse as int, default to 100GB for Kamiwaza
        volume_size_raw = self.node.try_get_context("volumeSize")
        try:
            volume_size = int(volume_size_raw) if volume_size_raw else 100
        except (ValueError, TypeError):
            volume_size = 100
        
        # Ensure minimum volume size for Kamiwaza (80GB minimum)
        volume_size = max(volume_size, 80)

        # Parse tags - handle both string (JSON) and dict
        tags_raw = self.node.try_get_context("tags") or {}
        if isinstance(tags_raw, str):
            try:
                tags_dict = json.loads(tags_raw)
            except json.JSONDecodeError:
                tags_dict = {}
        else:
            tags_dict = tags_raw

        # Use existing VPC or create new
        if vpc_id:
            vpc = ec2.Vpc.from_lookup(self, "VPC", vpc_id=vpc_id)
        else:
            vpc = ec2.Vpc(
                self, "KamiwazaVPC",
                max_azs=2,
                nat_gateways=1
            )

        # Security group
        security_group = ec2.SecurityGroup(
            self, "KamiwazaSG",
            vpc=vpc,
            description=f"Security group for Kamiwaza job {job_id}",
            allow_all_outbound=True
        )

        # SSH: only from explicitly allowed CIDRs (never 0.0.0.0/0). Use SSM for access when no CIDRs set.
        ssh_allowed_raw = self.node.try_get_context("sshAllowedCidrs")
        if ssh_allowed_raw is not None:
            ssh_cidrs = ssh_allowed_raw if isinstance(ssh_allowed_raw, list) else (json.loads(ssh_allowed_raw) if isinstance(ssh_allowed_raw, str) else [])
            for cidr in (c.strip() for c in ssh_cidrs if c and isinstance(c, str)):
                if cidr and cidr != "0.0.0.0/0":
                    security_group.add_ingress_rule(
                        ec2.Peer.ipv4(cidr),
                        ec2.Port.tcp(22),
                        f"Allow SSH from {cidr}"
                    )

        # Allow HTTP/HTTPS
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow HTTP"
        )
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "Allow HTTPS"
        )

        # Allow Docker ports (8000-8100)
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp_range(8000, 8100),
            "Allow Docker app ports"
        )

        # Get AMI
        if ami_id:
            machine_image = ec2.MachineImage.generic_linux({
                self.region: ami_id
            })
        else:
            # Use latest Red Hat Enterprise Linux 9
            machine_image = ec2.MachineImage.lookup(
                name="RHEL-9*_HVM-*-x86_64-*",
                owners=["309956199498"]  # Red Hat
            )

        # IAM role for EC2 instance
        role = iam.Role(
            self, "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description=f"IAM role for Kamiwaza EC2 instance (job {job_id})"
        )

        # Add SSM permissions for remote access
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )

        # User data
        user_data = None
        if user_data_b64:
            import base64
            user_data_str = base64.b64decode(user_data_b64).decode('utf-8')
            user_data = ec2.UserData.custom(user_data_str)
        else:
            # Default user data for RHEL 9 (basic setup only)
            user_data = ec2.UserData.for_linux()
            user_data.add_commands(
                "#!/bin/bash",
                "# RHEL 9 basic setup",
                "dnf update -y -q",
                "dnf install -y -q wget curl",
                "# For full Kamiwaza installation, provide custom user_data_b64"
            )

        # EC2 Instance
        instance = ec2.Instance(
            self, "KamiwazaInstance",
            instance_type=ec2.InstanceType(instance_type),
            machine_image=machine_image,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            ),
            security_group=security_group,
            role=role,
            user_data=user_data,
            key_name=key_pair_name,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=volume_size,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=True
                    )
                )
            ],
            # Require IMDSv2 for enhanced security (optional but recommended)
            require_imdsv2=True
        )

        # Add tags
        Tags.of(instance).add("Name", f"kamiwaza-job-{job_id}")
        Tags.of(instance).add("ManagedBy", "KamiwazaDeploymentManager")
        Tags.of(instance).add("JobId", str(job_id))

        # Add custom tags if provided
        if isinstance(tags_dict, dict):
            for key, value in tags_dict.items():
                Tags.of(instance).add(key, str(value))

        # Outputs
        CfnOutput(
            self, "InstanceId",
            value=instance.instance_id,
            description="EC2 Instance ID"
        )

        CfnOutput(
            self, "PublicIP",
            value=instance.instance_public_ip,
            description="Public IP address"
        )

        CfnOutput(
            self, "PrivateIP",
            value=instance.instance_private_ip,
            description="Private IP address"
        )

        CfnOutput(
            self, "SecurityGroupId",
            value=security_group.security_group_id,
            description="Security Group ID"
        )

        CfnOutput(
            self, "VpcId",
            value=vpc.vpc_id,
            description="VPC ID (for reuse in future deployments)"
        )

        CfnOutput(
            self, "VolumeSize",
            value=str(volume_size),
            description="EBS volume size in GB"
        )

        CfnOutput(
            self, "InstanceType",
            value=instance_type,
            description="EC2 instance type"
        )


app = cdk.App()

# Stack name from environment or default
stack_name = os.environ.get("CDK_STACK_NAME", "kamiwaza-provisioning")

KamiwazaEC2Stack(
    app,
    stack_name,
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
    )
)

app.synth()
