#!/usr/bin/env python3
"""
AWS CDK App for Kamiwaza EC2 Provisioning

This CDK app provisions EC2 instances for Kamiwaza deployments.
"""

import os
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
        subnet_id = self.node.try_get_context("subnetId")
        key_pair_name = self.node.try_get_context("keyPairName")
        user_data_b64 = self.node.try_get_context("userData")
        tags_dict = self.node.try_get_context("tags") or {}

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

        # Allow SSH from anywhere (adjust for production)
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(22),
            "Allow SSH"
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
            # Use latest Amazon Linux 2023
            machine_image = ec2.MachineImage.latest_amazon_linux2023()

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
            user_data = ec2.UserData.for_linux()
            user_data.add_commands(
                "#!/bin/bash",
                "yum update -y",
                "yum install -y docker",
                "systemctl start docker",
                "systemctl enable docker",
                "usermod -a -G docker ec2-user"
            )

        # EC2 Instance
        instance = ec2.Instance(
            self, "KamiwazaInstance",
            instance_type=ec2.InstanceType(instance_type),
            machine_image=machine_image,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            ) if not subnet_id else ec2.SubnetSelection(
                subnets=[ec2.Subnet.from_subnet_id(self, "Subnet", subnet_id)]
            ),
            security_group=security_group,
            role=role,
            user_data=user_data,
            key_name=key_pair_name,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=30,
                        encrypted=True,
                        delete_on_termination=True
                    )
                )
            ]
        )

        # Add tags
        Tags.of(instance).add("Name", f"kamiwaza-job-{job_id}")
        Tags.of(instance).add("ManagedBy", "KamiwazaDeploymentManager")
        Tags.of(instance).add("JobId", str(job_id))

        for key, value in tags_dict.items():
            Tags.of(instance).add(key, value)

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
