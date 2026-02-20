# AWS CDK Integration - Complete Implementation

## Overview

Integrated AWS CDK as the recommended provisioning method with support for IAM role assumption (AssumeRole) instead of long-lived access keys.

## Key Benefits

### Security
- **No Long-Lived Credentials**: IAM roles use temporary credentials that auto-expire
- **External ID Support**: Additional security layer for trust relationships
- **CloudTrail Audit**: Every AssumeRole action is logged
- **Automatic Rotation**: Temporary credentials rotate automatically
- **Least Privilege**: Granular permissions via IAM policies

### Developer Experience
- **Type-Safe Infrastructure**: CDK uses Python/TypeScript for IaC
- **Better Error Messages**: CDK provides clearer feedback than Terraform
- **Native AWS Integration**: First-class AWS service support
- **Faster Deployments**: CloudFormation-based with proper state management

## Architecture

```
Deployment Manager
    │
    ├─→ AWS CDK Provisioner (app/aws_cdk_provisioner.py)
    │       │
    │       ├─→ AssumeRole via boto3 STS
    │       │   ├─→ Gets temporary credentials
    │       │   └─→ Credentials expire after 1 hour
    │       │
    │       ├─→ CDK App (cdk/app.py)
    │       │   ├─→ Defines EC2 Stack
    │       │   ├─→ Security Groups
    │       │   ├─→ IAM Roles
    │       │   └─→ CloudFormation synthesis
    │       │
    │       └─→ CDK Deploy
    │           ├─→ Creates CloudFormation stack
    │           ├─→ Provisions EC2 instance
    │           └─→ Returns outputs (IP, instance ID, etc.)
    │
    └─→ Settings UI
        ├─→ Choose auth method (AssumeRole/AccessKeys/SSO)
        ├─→ Enter Role ARN and External ID
        ├─→ Copy-paste CloudFormation templates
        └─→ Test connection before saving
```

## Files Created

### CDK Application
- `cdk/app.py` - CDK stack definition for EC2 provisioning
- `cdk/cdk.json` - CDK configuration
- `cdk/requirements.txt` - CDK dependencies
- `cdk/README.md` - CDK documentation

### Provisioner Module
- `app/aws_cdk_provisioner.py` - AWS CDK provisioning logic
  - AssumeRole implementation
  - CDK deployment orchestration
  - Temporary credential management
  - Stack creation/destruction

### IAM Setup
- `aws-iam-setup/kamiwaza-iam-assume-role.yaml` - CloudFormation template for AssumeRole setup
- Updated `aws-iam-setup/README.md` with AssumeRole instructions

### UI Updates
- `app/templates/settings.html` - Added auth method selection
  - IAM Role (AssumeRole) - Recommended
  - Access Keys - Legacy
  - AWS SSO Profile
- Conditional field display based on auth method
- Copy-paste ready CloudFormation templates
- Step-by-step setup instructions

## Authentication Methods

### 1. IAM Role (AssumeRole) - RECOMMENDED

**Setup Steps:**

1. Deploy CloudFormation template (copy-paste from Settings UI)
2. Enter your AWS account ARN as `TrustedPrincipalArn`
3. Generate random `ExternalId` for security
4. Copy Role ARN from stack outputs
5. Enter Role ARN in Settings
6. Save configuration

**How it works:**
```python
# Assume role to get temporary credentials
creds = provisioner.assume_role(
    role_arn="arn:aws:iam::123456789012:role/KamiwazaProvisionerRole",
    session_name="kamiwaza-provisioner",
    external_id="random-external-id"
)

# Credentials are temporary and expire in 1 hour
{
    'access_key': 'ASIA...',
    'secret_key': '...',
    'session_token': '...',
    'expiration': '2026-01-16T19:00:00Z'
}

# Use credentials for CDK deployment
deploy_ec2_instance(credentials=creds, ...)
```

**Benefits:**
- No long-lived credentials stored
- Automatic expiration (1 hour)
- CloudTrail audit log of every assume
- Easy to rotate (no manual key rotation)
- External ID prevents confused deputy attacks

### 2. Access Keys - LEGACY

Traditional access key/secret key authentication. Still supported for backwards compatibility.

**Security Concerns:**
- Long-lived credentials
- Manual rotation required
- Risk of exposure/leakage
- Hard to track usage

**When to use:**
- Testing/development only
- When IAM role setup not possible
- Legacy systems

### 3. AWS SSO Profile

Use AWS Single Sign-On profiles from `~/.aws/config`.

**Setup:**
```bash
aws configure sso
# Follow prompts to set up SSO

# Then in Settings, enter profile name: "default" or "my-sso-profile"
```

## CDK Stack Resources

The CDK stack creates:

### EC2 Instance
- Instance type: configurable (default: t3.medium)
- AMI: Latest Amazon Linux 2023 (or custom)
- Root volume: 30GB EBS, encrypted
- User data: Docker installation + custom scripts
- IAM instance role with SSM Session Manager

### Networking
- VPC: Use existing or create new
- Subnet: Public subnet with IGW
- Security Group:
  - SSH (22) - only from allowed CIDRs when configured (default: no public SSH; use SSM)
  - HTTP (80) - from anywhere
  - HTTPS (443) - from anywhere
  - Docker ports (8000-8100) - from anywhere

### IAM
- EC2 instance role with SSM permissions
- Passrole permissions for CDK

### Outputs
- Instance ID
- Public IP
- Private IP
- Security Group ID

## Settings UI

### Auth Method Selector

Dropdown with 3 options:
1. **IAM Role (AssumeRole)** - Shows Role ARN, External ID, Session Name fields
2. **Access Keys** - Shows Access Key ID, Secret Access Key fields
3. **AWS SSO Profile** - Shows Profile Name field

### Provisioning Method Selector

Dropdown with 2 options:
1. **AWS CDK** (Recommended) - Modern, type-safe IaC
2. **Terraform** - Legacy, still supported

### Setup Instructions

Click "Show Setup Instructions" button to see:
- Step-by-step CloudFormation deployment
- IAM policy with CDK permissions
- Trust relationship configuration
- Copy buttons for all templates
- Links to AWS Console

## Environment Variables

New variables added to `.env`:

```bash
# AWS Authentication
AWS_AUTH_METHOD=assume_role  # or 'access_keys' or 'sso'
AWS_ASSUME_ROLE_ARN=arn:aws:iam::123456789012:role/KamiwazaProvisionerRole
AWS_EXTERNAL_ID=random-external-id-12345
AWS_SESSION_NAME=kamiwaza-provisioner

# AWS SSO (if using SSO method)
AWS_SSO_PROFILE=default

# AWS Credentials (if using access_keys method)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...

# AWS Region
AWS_REGION=us-west-2

# Provisioning Method
AWS_PROVISIONING_METHOD=cdk  # or 'terraform'
```

## Usage Example

### 1. Setup IAM Role

```bash
# Deploy CloudFormation template (from Settings UI)
aws cloudformation create-stack \
  --stack-name kamiwaza-iam-role \
  --template-body file://aws-iam-setup/kamiwaza-iam-assume-role.yaml \
  --parameters \
    ParameterKey=TrustedPrincipalArn,ParameterValue=arn:aws:iam::123456789012:root \
    ParameterKey=ExternalId,ParameterValue=my-external-id \
  --capabilities CAPABILITY_NAMED_IAM

# Wait for stack creation
aws cloudformation wait stack-create-complete \
  --stack-name kamiwaza-iam-role

# Get role ARN
aws cloudformation describe-stacks \
  --stack-name kamiwaza-iam-role \
  --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue' \
  --output text
```

### 2. Configure Settings

1. Go to http://localhost:8000/settings
2. Under "AWS Authentication":
   - Select "IAM Role (AssumeRole)"
   - Enter Role ARN: `arn:aws:iam::123456789012:role/KamiwazaProvisionerRole`
   - Enter External ID: `my-external-id`
   - Session Name: `kamiwaza-provisioner` (default)
3. Under "Provisioning Method": Select "AWS CDK"
4. Enter AWS Region: `us-west-2`
5. Click "Save Configuration"

### 3. Create Provisioning Job

1. Go to "New Job"
2. Fill in job details
3. Upload user CSV (optional)
4. Click "Create Job"
5. Click "Run Job"

### 4. Monitor Deployment

Watch real-time CDK deployment logs:
- CDK synth
- CloudFormation stack creation
- EC2 instance launch
- Security group configuration
- Outputs (IP addresses, instance ID)

## Security Best Practices

### IAM Role Setup

1. **Use External ID**: Prevents confused deputy attacks
   ```yaml
   ExternalId: !Ref ExternalId  # Random string, keep secret
   ```

2. **Limit Trust Relationship**: Only allow specific principals
   ```yaml
   Principal:
     AWS: arn:aws:iam::123456789012:user/specific-user  # Not :root
   ```

3. **Short Session Duration**: 1 hour maximum
   ```yaml
   MaxSessionDuration: 3600  # 1 hour
   ```

4. **Audit CloudTrail**: Monitor all AssumeRole calls
   ```bash
   aws cloudtrail lookup-events \
     --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRole
   ```

### CDK Deployment

1. **Resource Tags**: Tag all resources
   ```python
   Tags.of(instance).add("ManagedBy", "KamiwazaDeploymentManager")
   Tags.of(instance).add("JobId", str(job_id))
   ```

2. **Encrypted Volumes**: Always encrypt EBS
   ```python
   volume=ec2.BlockDeviceVolume.ebs(
       volume_size=30,
       encrypted=True
   )
   ```

3. **Least Privilege**: Minimal security group rules
   ```python
   # Only open required ports
   security_group.add_ingress_rule(
       ec2.Peer.ipv4("10.0.0.0/8"),  # Not any_ipv4()
       ec2.Port.tcp(22)
   )
   ```

## Troubleshooting

### AssumeRole Fails

**Error:** `Access Denied`

**Solutions:**
1. Check trust relationship in IAM role
2. Verify External ID matches
3. Ensure current credentials have `sts:AssumeRole` permission
4. Check role ARN is correct

### CDK Bootstrap Required

**Error:** `This stack uses assets, so the toolkit stack must be deployed`

**Solution:**
```bash
npx cdk bootstrap aws://ACCOUNT-ID/REGION
```

### CDK Deploy Fails

**Error:** `CREATE_FAILED`

**Solutions:**
1. Check CloudFormation logs in AWS Console
2. Verify IAM permissions (CloudFormation, EC2, S3)
3. Check VPC/subnet configuration
4. Ensure AMI exists in region

### Temporary Credentials Expired

**Error:** `The security token included in the request is expired`

**Solution:**
- Credentials auto-expire after 1 hour
- Job will automatically re-assume role if needed
- Check `credentials['expiration']` timestamp

## Migration from Terraform

To migrate existing jobs from Terraform to CDK:

1. Update Settings to use AWS CDK
2. New jobs will use CDK automatically
3. Existing Terraform jobs continue to work
4. Gradually transition as old jobs complete

## Future Enhancements

- [ ] CDK Pipelines for CI/CD
- [ ] Multi-region deployments
- [ ] VPC peering automation
- [ ] Auto-scaling groups
- [ ] ECS/Fargate support
- [ ] RDS database provisioning
- [ ] Lambda function deployments
- [ ] CloudWatch dashboards

## Support

For issues with AWS CDK integration:
1. Check CDK logs: `tail -f cdk/cdk.out/logs`
2. Check CloudFormation console for stack status
3. Review IAM role permissions
4. Verify CDK is installed: `npx cdk --version`
5. Contact: devops@kamiwaza.ai

## Additional Resources

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [AssumeRole Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use.html)
- [External ID Usage](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-user_externalid.html)
- [CDK Patterns](https://cdkpatterns.com/)
