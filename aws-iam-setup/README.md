# AWS IAM Setup for Kamiwaza Deployment Manager

This directory contains IAM policy and CloudFormation templates for setting up AWS credentials with least-privilege access for EC2 provisioning.

## Files

- **kamiwaza-iam-policy.json** - IAM policy JSON (for manual setup)
- **kamiwaza-iam-cloudformation.yaml** - CloudFormation template (for automated setup)

## Quick Start - CloudFormation (Recommended)

1. Log into AWS Console with admin access
2. Go to [CloudFormation Console](https://console.aws.amazon.com/cloudformation/)
3. Click **Create stack** → **With new resources**
4. Select **Upload a template file**
5. Upload `kamiwaza-iam-cloudformation.yaml`
6. Click **Next** → **Next**
7. Check **"I acknowledge that AWS CloudFormation might create IAM resources"**
8. Click **Create stack**
9. Wait for stack to complete (1-2 minutes)
10. Go to **Outputs** tab
11. Copy **AccessKeyId** and **SecretAccessKey**
12. Enter them in the Deployment Manager Settings page

## Manual Setup

### Step 1: Create IAM Policy

1. Go to [IAM Console](https://console.aws.amazon.com/iam/)
2. Click **Policies** → **Create policy**
3. Click **JSON** tab
4. Copy contents of `kamiwaza-iam-policy.json` and paste
5. Click **Next: Tags** → **Next: Review**
6. Policy name: `KamiwazaEC2ProvisioningPolicy`
7. Click **Create policy**

### Step 2: Create IAM User

1. Go to [IAM Console](https://console.aws.amazon.com/iam/)
2. Click **Users** → **Add users**
3. Username: `kamiwaza-provisioner`
4. Select **Programmatic access**
5. Click **Next: Permissions**
6. Click **Attach policies directly**
7. Search for and select `KamiwazaEC2ProvisioningPolicy`
8. Click **Next: Tags** → **Next: Review** → **Create user**
9. **Save the Access Key ID and Secret Access Key** - you won't see the secret again!

### Step 3: Enter Credentials

1. Go to Deployment Manager Settings: http://localhost:8000/settings
2. Scroll to **AWS Credentials** section
3. Click **Show Setup Instructions** to see this guide in the UI
4. Enter your Access Key ID and Secret Access Key
5. Select your default AWS region (e.g., `us-west-2`)
6. Click **Save Configuration**

## Permissions Explained

The IAM policy grants the following permissions:

### EC2 Provisioning
- Create and terminate EC2 instances
- Describe EC2 resources (instances, AMIs, key pairs, etc.)
- Manage instance tags
- Modify instance attributes
- Associate/disassociate IAM instance profiles

### Networking
- Create, modify, and delete security groups
- Manage security group rules (ingress/egress)

### Terraform State (Optional)
- Read/write to S3 buckets prefixed with `terraform-state-*`
- Required if using S3 for Terraform remote state

## Security Best Practices

1. **Rotate Keys**: Rotate access keys every 90 days
2. **Least Privilege**: Only grant permissions actually needed
3. **Monitor Usage**: Enable CloudTrail to log API calls
4. **Use IAM Roles**: For production, consider using IAM roles instead of access keys
5. **Separate Environments**: Use different IAM users for dev/staging/prod

## Troubleshooting

### "Access Denied" Errors

If you get access denied errors during provisioning:

1. Verify the policy is attached to the user
2. Check AWS region matches your configuration
3. Verify the specific EC2 action is included in the policy
4. Check CloudTrail logs for denied API calls

### CloudFormation Stack Fails

Common reasons:
- Missing IAM permissions to create policies/users
- Policy name already exists (delete old policy first)
- User name already exists (delete old user first)

### Access Keys Not Working

1. Verify keys were copied correctly (no extra spaces)
2. Check if keys were deactivated in IAM console
3. Verify user exists and has policy attached
4. Try creating new access keys

## Additional Resources

- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [EC2 API Permissions Reference](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/ec2-api-permissions.html)
- [CloudFormation IAM Resources](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/AWS_IAM.html)

## Support

For issues with IAM setup:
1. Check this README
2. Review AWS IAM console for user/policy status
3. Check CloudTrail logs for denied API calls
4. Contact: devops@kamiwaza.ai
