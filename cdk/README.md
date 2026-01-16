# AWS CDK for Kamiwaza EC2 Provisioning

This directory contains the AWS CDK application for provisioning EC2 instances.

## Setup

```bash
# Install CDK CLI
npm install -g aws-cdk

# Install Python dependencies
pip install -r requirements.txt

# Bootstrap CDK (one-time per AWS account/region)
cdk bootstrap
```

## Usage

The CDK app is invoked automatically by the `aws_cdk_provisioner.py` module.

### Manual Deployment

```bash
# Synth CloudFormation template
cdk synth

# Deploy stack
cdk deploy

# Destroy stack
cdk destroy
```

### Context Parameters

- `jobId` - Job ID for tracking
- `instanceType` - EC2 instance type (default: t3.medium)
- `amiId` - AMI ID (optional, defaults to Amazon Linux 2023)
- `vpcId` - VPC ID (optional, creates new VPC if not specified)
- `subnetId` - Subnet ID (optional)
- `keyPairName` - EC2 key pair name (optional)
- `userData` - Base64-encoded user data script (optional)
- `tags` - Dict of tags to apply (optional)

## Stack Resources

The CDK stack creates:

- EC2 Instance with proper IAM role
- Security Group with necessary ports
- VPC (if not provided)
- CloudWatch Logs integration
- SSM Session Manager support

## Outputs

- InstanceId - EC2 instance ID
- PublicIP - Public IP address
- PrivateIP - Private IP address
- SecurityGroupId - Security group ID
