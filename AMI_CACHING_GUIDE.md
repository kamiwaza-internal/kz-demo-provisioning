# Kamiwaza AMI Caching Guide

## Overview

This guide explains how to use AMI caching to dramatically speed up Kamiwaza deployments from **30+ minutes to ~5 minutes**.

## Why Use AMI Caching?

### Without AMI Caching (Standard Deployment)
- Downloads .deb package (~200MB+)
- Installs Kamiwaza and all dependencies
- Downloads all Docker images
- Configures system
- **Total time: 20-30 minutes**

### With AMI Caching (Fast Deployment)
- Uses pre-configured AMI with Kamiwaza already installed
- Skips .deb download and installation
- Docker images already present
- Just starts Kamiwaza
- **Total time: ~5 minutes**

## Workflow

### Phase 1: Create Golden AMI (One-Time Setup)

1. **Deploy Kamiwaza once using standard method**
   ```bash
   python3 deploy_kamiwaza.py \
       --name kamiwaza-golden \
       --instance-type t3.xlarge \
       --region us-east-1 \
       --skip-login-test
   ```

2. **Wait for deployment to complete fully** (20-30 minutes)
   - Monitor logs: `aws ssm start-session --target i-xxxxx`
   - Check: `sudo tail -f /var/log/kamiwaza-deployment.log`
   - Verify: `docker ps | grep kamiwaza` shows containers running

3. **Create AMI from the running instance**
   ```bash
   # Option A: Using instance ID
   ./scripts/create_kamiwaza_ami.sh --instance-id i-0123456789abcdef0

   # Option B: Using CloudFormation stack name
   ./scripts/create_kamiwaza_ami.sh --stack-name kamiwaza-golden

   # Option C: Fast AMI creation (no reboot, less consistent)
   ./scripts/create_kamiwaza_ami.sh --instance-id i-xxxxx --no-reboot
   ```

4. **Save the AMI ID**
   ```bash
   # The script outputs something like:
   # AMI ID: ami-0a1b2c3d4e5f6g7h8

   # Save it to a file
   echo 'ami-0a1b2c3d4e5f6g7h8' > kamiwaza-ami-v0.9.2.txt
   ```

### Phase 2: Fast Deployments (Ongoing)

Use the cached AMI for all future deployments:

```bash
# Load AMI ID
AMI_ID=$(cat kamiwaza-ami-v0.9.2.txt)

# Deploy with cached AMI (~5 minutes)
python3 deploy_kamiwaza.py \
    --name kamiwaza-demo-001 \
    --ami-id $AMI_ID \
    --instance-type t3.xlarge \
    --region us-east-1
```

## Complete Examples

### Example 1: First-Time Setup

```bash
# 1. Deploy fresh instance to create golden AMI
python3 deploy_kamiwaza.py \
    --name kamiwaza-golden \
    --instance-type t3.xlarge \
    --region us-east-1 \
    --key-pair my-ssh-key \
    --skip-login-test

# Wait 30 minutes for full deployment...

# 2. Get the instance ID from the output
INSTANCE_ID="i-0123456789abcdef0"

# 3. Verify Kamiwaza is fully running
aws ssm start-session --target $INSTANCE_ID --region us-east-1
# On the instance:
docker ps | grep kamiwaza
sudo tail -f /var/log/kamiwaza-deployment.log
# Exit: Ctrl+D

# 4. Create AMI
./scripts/create_kamiwaza_ami.sh \
    --instance-id $INSTANCE_ID \
    --region us-east-1

# 5. Note the AMI ID from output
# Example output: AMI ID: ami-0a1b2c3d4e5f6g7h8

# 6. Save it
echo 'ami-0a1b2c3d4e5f6g7h8' > kamiwaza-ami-v0.9.2.txt

# 7. Optionally, destroy the golden instance (AMI is saved)
cd cdk
npx cdk destroy kamiwaza-golden
```

### Example 2: Using Cached AMI for Fast Deployments

```bash
# Deploy multiple instances quickly
AMI_ID=$(cat kamiwaza-ami-v0.9.2.txt)

# Demo instance 1
python3 deploy_kamiwaza.py \
    --name kamiwaza-demo-001 \
    --ami-id $AMI_ID

# Demo instance 2
python3 deploy_kamiwaza.py \
    --name kamiwaza-demo-002 \
    --ami-id $AMI_ID \
    --instance-type t3.large

# Production instance
python3 deploy_kamiwaza.py \
    --name kamiwaza-prod \
    --ami-id $AMI_ID \
    --instance-type t3.2xlarge \
    --volume-size 200
```

### Example 3: Multi-Region Deployment

AMIs are region-specific. To deploy in multiple regions:

```bash
# Create AMI in us-east-1
./scripts/create_kamiwaza_ami.sh \
    --instance-id i-xxxxx \
    --region us-east-1

# Copy AMI to us-west-2
SOURCE_AMI="ami-0a1b2c3d4e5f6g7h8"
aws ec2 copy-image \
    --source-region us-east-1 \
    --source-image-id $SOURCE_AMI \
    --name "kamiwaza-golden-v0.9.2-us-west-2" \
    --region us-west-2

# Deploy in us-west-2
python3 deploy_kamiwaza.py \
    --name kamiwaza-west \
    --ami-id ami-copied-west-id \
    --region us-west-2
```

## Script Reference

### create_kamiwaza_ami.sh

Creates a golden AMI from a running Kamiwaza instance.

**Syntax:**
```bash
./scripts/create_kamiwaza_ami.sh [OPTIONS]
```

**Required Options (one of):**
- `--instance-id ID` - EC2 Instance ID
- `--stack-name NAME` - CloudFormation stack name

**Optional Parameters:**
- `--region REGION` - AWS region (default: us-east-1)
- `--no-reboot` - Create AMI without rebooting (faster, less consistent)
- `--version VERSION` - Kamiwaza version tag (default: v0.9.2)
- `--name-prefix PREFIX` - AMI name prefix (default: kamiwaza-golden)
- `--dry-run` - Show what would be done without creating AMI
- `--help` - Show help message

**Examples:**
```bash
# Create AMI from instance ID
./scripts/create_kamiwaza_ami.sh --instance-id i-xxxxx

# Create AMI from CloudFormation stack
./scripts/create_kamiwaza_ami.sh --stack-name kamiwaza-job-17

# Fast AMI creation (no reboot)
./scripts/create_kamiwaza_ami.sh --instance-id i-xxxxx --no-reboot

# Dry run
./scripts/create_kamiwaza_ami.sh --instance-id i-xxxxx --dry-run

# Custom version tag
./scripts/create_kamiwaza_ami.sh \
    --instance-id i-xxxxx \
    --version v1.0.0 \
    --name-prefix kamiwaza-prod
```

### deploy_kamiwaza.py

Deploys Kamiwaza to AWS EC2, with optional AMI caching.

**New Parameter:**
- `--ami-id AMI_ID` - Pre-configured Kamiwaza AMI ID for faster deployment

**Examples:**
```bash
# Standard deployment (30 minutes)
python3 deploy_kamiwaza.py --name kamiwaza-demo

# Fast deployment with AMI (5 minutes)
python3 deploy_kamiwaza.py \
    --name kamiwaza-demo \
    --ami-id ami-0123456789abcdef0
```

## Best Practices

### 1. AMI Versioning

Create separate AMIs for different Kamiwaza versions:

```bash
# v0.9.2
./scripts/create_kamiwaza_ami.sh \
    --instance-id i-xxxxx \
    --version v0.9.2 \
    --name-prefix kamiwaza-golden

# Save AMI IDs per version
echo 'ami-xxxxx' > kamiwaza-ami-v0.9.2.txt
```

### 2. Testing New AMIs

Always test a new AMI before using it for production:

```bash
# Create test deployment with new AMI
python3 deploy_kamiwaza.py \
    --name kamiwaza-ami-test \
    --ami-id ami-new-id \
    --instance-type t3.medium

# Verify it works, then use for production
```

### 3. AMI Maintenance

- **Update regularly**: Create new AMIs when Kamiwaza releases updates
- **Document AMI IDs**: Keep a record of AMI IDs and their versions
- **Clean up old AMIs**: Delete outdated AMIs to reduce costs
  ```bash
  aws ec2 deregister-image --image-id ami-old-id --region us-east-1
  ```

### 4. Sharing AMIs

Share AMIs across AWS accounts:

```bash
# Share AMI with another account
aws ec2 modify-image-attribute \
    --image-id ami-xxxxx \
    --launch-permission "Add=[{UserId=123456789012}]" \
    --region us-east-1
```

### 5. Cost Optimization

- AMIs incur storage costs (~$0.05 per GB-month in us-east-1)
- Delete golden instances after creating AMI (AMI is preserved)
- Consider using smaller instance types for golden AMI creation

## Troubleshooting

### AMI Creation Fails

**Problem**: `create_kamiwaza_ami.sh` fails with permission error

**Solution**: Ensure AWS credentials have `ec2:CreateImage` permission
```bash
aws sts get-caller-identity
# Verify your IAM role/user has EC2 full access
```

### AMI-Based Deployment Fails to Start Kamiwaza

**Problem**: Instance starts but Kamiwaza doesn't run

**Solution**:
1. Check user data logs: `sudo cat /var/log/kamiwaza-firstboot.log`
2. Manually start Kamiwaza: `kamiwaza start`
3. Verify Docker containers: `docker ps`

### AMI Not Found in Different Region

**Problem**: AMI ID works in us-east-1 but not us-west-2

**Solution**: AMIs are region-specific. Copy AMI to the target region:
```bash
aws ec2 copy-image \
    --source-region us-east-1 \
    --source-image-id ami-xxxxx \
    --region us-west-2 \
    --name "kamiwaza-golden-v0.9.2"
```

### Deployment Still Slow with AMI

**Problem**: Using AMI but deployment takes longer than 5 minutes

**Possible causes:**
1. Wrong AMI ID (using base Ubuntu instead of Kamiwaza AMI)
2. User data still running .deb installation
3. Network issues with AWS

**Debug:**
```bash
# SSH into instance
aws ssm start-session --target i-xxxxx

# Check what's running
sudo tail -f /var/log/kamiwaza-firstboot.log
ps aux | grep kamiwaza
```

### AMI Too Large

**Problem**: AMI exceeds expected size

**Solution**: Clean up before creating AMI
```bash
# SSH into golden instance before creating AMI
sudo apt-get clean
docker system prune -af
sudo rm -rf /tmp/*
sudo journalctl --vacuum-time=1d
```

## Cost Comparison

### Standard Deployment (Without AMI Caching)
- Deployment time: 30 minutes
- Data transfer: ~500MB (package + Docker images)
- EC2 costs: 30 min × instance type
- Example (t3.xlarge): 30 min × $0.1664/hour = $0.083

### AMI-Cached Deployment
- AMI storage: ~10GB × $0.05/GB-month = $0.50/month
- Deployment time: 5 minutes
- Data transfer: Minimal (< 10MB)
- EC2 costs: 5 min × instance type
- Example (t3.xlarge): 5 min × $0.1664/hour = $0.014

**Savings per deployment**: ~$0.069 + 25 minutes time saved

## Integration with Web UI

To add AMI caching to your web UI, update the job creation form:

```python
# In app/models.py
class DeploymentJob(Base):
    # ... existing fields ...
    ami_id = Column(String, nullable=True)  # Add this field

# In worker/tasks.py
def deploy_kamiwaza_task(job_id: int):
    # ... existing code ...
    cdk_command = [
        "npx", "cdk", "deploy",
        # ... existing args ...
    ]

    # Add AMI ID to context if provided
    if job.ami_id:
        context["amiId"] = job.ami_id
```

## Summary

| Aspect | Standard | AMI Cached |
|--------|----------|------------|
| First deployment | 30 min | N/A (creating AMI) |
| Subsequent deployments | 30 min | 5 min |
| Setup complexity | Low | Medium |
| Maintenance | None | Update AMIs periodically |
| Cost per deployment | Higher | Lower (after initial AMI creation) |
| Best for | One-off deployments | Multiple/repeated deployments |

## Additional Resources

- [AWS AMI Documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AMIs.html)
- [Kamiwaza Installation Guide](https://docs.kamiwaza.ai/installation)
- [CDK Documentation](https://docs.aws.amazon.com/cdk/latest/guide/home.html)

## Support

For issues:
1. Check this guide's Troubleshooting section
2. Verify AMI ID is correct for your region
3. Check AWS CloudFormation console for detailed errors
4. Review `/var/log/kamiwaza-firstboot.log` on the instance
