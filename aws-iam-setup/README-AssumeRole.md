# AWS IAM Role Setup for AssumeRole Authentication

This is the **recommended** setup for Kamiwaza Deployment Manager using temporary credentials via AssumeRole.

## Quick Start

### Prerequisites
You already have AWS credentials (the base credentials you entered in Settings):
- User: `arn:aws:iam::916994818137:user/kamiwaza-provisioner`
- These base credentials will be used to **assume** the provisioning role

### Deploy the Role

1. **Open CloudFormation Console**
   ```
   https://console.aws.amazon.com/cloudformation/home?region=us-west-2#/stacks/create
   ```

2. **Upload Template**
   - Select: "Upload a template file"
   - Choose: `kamiwaza-iam-assume-role.yaml`
   - Click "Next"

3. **Configure Stack**
   - Stack name: `kamiwaza-iam-role`
   - **TrustedPrincipalArn**: `arn:aws:iam::916994818137:user/kamiwaza-provisioner`
     *(This is your base user that will assume the role)*
   - **ExternalId**: *(optional - leave blank or generate random string for security)*
   - Click "Next"

4. **Review and Create**
   - Scroll to bottom
   - Check: "I acknowledge that AWS CloudFormation might create IAM resources with custom names"
   - Click "Create stack"

5. **Wait for Completion** (2-3 minutes)
   - Status will change to `CREATE_COMPLETE`

6. **Get the Role ARN**
   - Go to "Outputs" tab
   - Copy the **RoleArn** value
   - Example: `arn:aws:iam::916994818137:role/KamiwazaProvisionerRole`

7. **Update Deployment Manager Settings**
   - The Role ARN should already be set to the correct value in Settings
   - If not, paste it into: http://localhost:8000/settings
   - Save configuration

## What This Creates

### IAM Role: `KamiwazaProvisionerRole`
- **Trust Relationship**: Allows your base user to assume this role
- **Session Duration**: 1 hour (credentials auto-expire)
- **Permissions**: Full EC2, CDK, and CloudFormation access

### Managed Policy: `KamiwazaEC2ProvisioningPolicy`
Includes permissions for:
- ✓ EC2 instance provisioning and management
- ✓ Security groups and networking
- ✓ IAM roles for EC2 instances
- ✓ CloudFormation (for CDK deployments)
- ✓ S3 (for CDK asset storage)
- ✓ SSM Session Manager

## Security Benefits

1. **Temporary Credentials**
   - Credentials expire after 1 hour
   - No long-lived access keys stored

2. **External ID** (optional)
   - Additional security layer
   - Prevents "confused deputy" attacks

3. **Audit Trail**
   - All AssumeRole calls logged in CloudTrail
   - Track who accessed what and when

4. **Least Privilege**
   - Role only has permissions needed for EC2 provisioning
   - No admin access

## Testing

After deploying the stack:

```bash
# Test assuming the role (from your terminal)
aws sts assume-role \
  --role-arn arn:aws:iam::916994818137:role/KamiwazaProvisionerRole \
  --role-session-name test-session

# Should return temporary credentials if successful
```

## Troubleshooting

### "Access Denied" when assuming role
- Verify the TrustedPrincipalArn matches your base user
- Check that your base credentials have `sts:AssumeRole` permission
- Verify External ID matches (if using one)

### "Role already exists"
- Delete the existing stack and redeploy
- Or update the stack with new parameters

### CDK Bootstrap Required
If you see "toolkit stack must be deployed", run:
```bash
npx cdk bootstrap aws://916994818137/us-west-2
```

## CLI Deployment (Alternative)

Instead of the AWS Console, you can deploy via CLI:

```bash
aws cloudformation create-stack \
  --stack-name kamiwaza-iam-role \
  --template-body file://aws-iam-setup/kamiwaza-iam-assume-role.yaml \
  --parameters \
    ParameterKey=TrustedPrincipalArn,ParameterValue=arn:aws:iam::916994818137:user/kamiwaza-provisioner \
    ParameterKey=ExternalId,ParameterValue="" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2

# Wait for completion
aws cloudformation wait stack-create-complete \
  --stack-name kamiwaza-iam-role \
  --region us-west-2

# Get the Role ARN
aws cloudformation describe-stacks \
  --stack-name kamiwaza-iam-role \
  --region us-west-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue' \
  --output text
```

## Next Steps

After deploying the role:
1. Create a new EC2 job at http://localhost:8000/jobs/new
2. Select instance type (e.g., t2.micro)
3. Click "Create Job" → "Run Job"
4. Watch the CDK deployment in real-time!
