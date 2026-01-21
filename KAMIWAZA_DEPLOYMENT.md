# Deploying Kamiwaza to AWS EC2

This guide explains how to deploy the full Kamiwaza platform to AWS EC2 using the kz-demo-provisioning system.

## Overview

The deployment system provisions an EC2 instance and automatically installs and configures the complete Kamiwaza stack, including:

- **Infrastructure Services**: Traefik, etcd, Redis
- **Databases**: CockroachDB, Milvus (vector database)
- **Authentication**: Keycloak
- **Data Catalog**: DataHub
- **Observability** (optional): Loki, Grafana, OTEL Collector
- **Kamiwaza Platform**: Core application and Ray cluster

## Prerequisites

### 1. AWS Account Setup

You need an AWS account with appropriate IAM permissions. Follow the AWS setup guide in the [AWS_CDK_INTEGRATION.md](AWS_CDK_INTEGRATION.md) document to:

1. Create an IAM role for provisioning
2. Configure AWS credentials in the Settings UI

### 2. GitHub Access Token (for private repository)

If the Kamiwaza repository is private, you need a GitHub Personal Access Token:

1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate a new token with `repo` scope
3. Save the token securely

### 3. System Requirements

For a full Kamiwaza deployment, we recommend:

- **Instance Type**: `t3.xlarge` or larger (4 vCPU, 16 GB RAM minimum)
- **Volume Size**: 100 GB minimum
- **Region**: Any AWS region (us-east-1, us-west-2, etc.)
- **OS**: Amazon Linux 2023 (default AMI) or Ubuntu 22.04 LTS

### 4. Network Requirements

The deployment will configure security groups to allow:

- **SSH** (port 22): For administrative access
- **HTTP** (port 80): Redirects to HTTPS
- **HTTPS** (port 443): Main application access
- **Docker App Ports** (8000-8100): For containerized services

## Quick Start

### Option 1: Using Python Script (Recommended)

```bash
cd /Users/steffenmerten/Code/kz-demo-provisioning

# Activate virtual environment
source venv/bin/activate

# Set GitHub token (if using private repository)
export GITHUB_TOKEN="ghp_your_token_here"

# Generate user data
python3 scripts/generate_kamiwaza_userdata.py \
    --branch develop \
    --github-token "$GITHUB_TOKEN" \
    --output base64 \
    --output-file /tmp/kamiwaza-userdata.b64

# The base64-encoded user data is now in /tmp/kamiwaza-userdata.b64
cat /tmp/kamiwaza-userdata.b64
```

### Option 2: Using CDK Python Deployment

Create a deployment using the AWS CDK provisioner:

```python
import os
import base64
from pathlib import Path

# Read the deployment script
script_path = Path("scripts/deploy_kamiwaza_full.sh")
deployment_script = script_path.read_text()

# Add environment variables
user_data = f"""#!/bin/bash

export KAMIWAZA_BRANCH='develop'
export GITHUB_TOKEN='{os.environ.get("GITHUB_TOKEN", "")}'
export KAMIWAZA_ROOT='/opt/kamiwaza'

{deployment_script}
"""

# Encode to base64
user_data_b64 = base64.b64encode(user_data.encode()).decode()

print(f"User data (base64): {user_data_b64}")
```

## Step-by-Step Deployment

### Step 1: Configure AWS Credentials

1. Navigate to `http://localhost:8000/settings`
2. Configure your AWS authentication method (IAM Role or Access Keys)
3. Test the connection
4. Save configuration

### Step 2: Prepare User Data

Generate the user data script:

```bash
# With GitHub token (for private repo)
python3 scripts/generate_kamiwaza_userdata.py \
    --branch develop \
    --github-token "ghp_YOUR_TOKEN" \
    --output-file /tmp/userdata.b64

# Without GitHub token (for public repo or if using SSH keys)
python3 scripts/generate_kamiwaza_userdata.py \
    --branch develop \
    --output-file /tmp/userdata.b64
```

### Step 3: Create Deployment via UI

1. Go to `http://localhost:8000`
2. Click **"Create New Job"**
3. Fill in the deployment form:

   **Basic Information:**
   - Job Name: `kamiwaza-demo-prod`
   - Requester Email: `your@email.com`

   **AWS Configuration:**
   - Region: `us-east-1` (or your preferred region)
   - Instance Type: `t3.xlarge`
   - Volume Size: `100` GB
   - Key Pair: Select your SSH key pair

   **User Data:**
   - Paste the base64-encoded content from `/tmp/userdata.b64`

   **Network (Optional):**
   - Leave empty for default VPC setup
   - Or specify your VPC/Subnet IDs

   **Tags (Optional):**
   ```json
   {
     "Environment": "demo",
     "Project": "Kamiwaza",
     "Purpose": "Full Stack Demo"
   }
   ```

4. Click **"Create Job"**
5. On the job detail page, click **"Start Job"**

### Step 4: Monitor Deployment

The deployment will take approximately 20-30 minutes. You can monitor progress:

1. **Job Logs**: Watch real-time logs in the UI
2. **CloudFormation**: Check AWS Console → CloudFormation
3. **EC2 Instance**: Once created, check AWS Console → EC2

### Step 5: Access Kamiwaza

Once deployment completes:

1. Get the public IP from the job outputs
2. Navigate to `https://<PUBLIC_IP>`
3. Accept the self-signed certificate warning (production deployments should use valid certificates)
4. Login with default credentials:
   - Username: `admin`
   - Password: `kamiwaza`

## Deployment Architecture

The deployment script performs these steps:

```
1. System Setup
   ├─ Update OS packages
   ├─ Install Docker & Docker Compose
   ├─ Install system dependencies
   └─ Install uv (Python package manager)

2. Kamiwaza Installation
   ├─ Clone Kamiwaza repository
   ├─ Configure environment variables
   ├─ Run install.sh (Python dependencies)
   └─ Run setup.sh (virtual environments)

3. Container Deployment
   ├─ Start etcd cluster
   ├─ Start Traefik reverse proxy
   ├─ Start databases (CockroachDB, Milvus)
   ├─ Start Keycloak (authentication)
   ├─ Start DataHub (data catalog)
   └─ Start Redis and other services

4. Application Startup
   ├─ Create systemd service
   ├─ Start Kamiwaza application
   └─ Configure Ray cluster

5. Verification
   ├─ Check service health
   ├─ Display access information
   └─ Create README for user
```

## Configuration Options

### Environment Variables

You can customize the deployment by setting environment variables:

```bash
# Repository configuration
export KAMIWAZA_REPO="https://github.com/kamiwaza-internal/kamiwaza.git"
export KAMIWAZA_BRANCH="develop"  # or "main", "feature/xyz"
export GITHUB_TOKEN="ghp_xxx"     # For private repositories

# Installation paths
export KAMIWAZA_ROOT="/opt/kamiwaza"
export KAMIWAZA_USER="ubuntu"

# Deployment options
export KAMIWAZA_LITE="false"              # true for lite mode
export KAMIWAZA_USE_AUTH="true"           # false to disable auth
export KAMIWAZA_MILVUS_ENABLED="true"     # false to disable Milvus
export KAMIWAZA_OTEL_ENABLED="false"      # true for observability
export KAMIWAZA_LOKI_ENABLED="false"      # true for log aggregation
```

### Instance Sizing Guide

| Deployment Type | Instance Type | vCPU | RAM | Storage | Use Case |
|----------------|---------------|------|-----|---------|----------|
| **Minimal** | t3.large | 2 | 8 GB | 50 GB | Testing, small demos |
| **Standard** | t3.xlarge | 4 | 16 GB | 100 GB | Full demos, development |
| **Production** | t3.2xlarge | 8 | 32 GB | 200 GB | Production workloads |
| **GPU-enabled** | g5.xlarge | 4 | 16 GB | 100 GB | AI/ML workloads |

## Post-Deployment

### Accessing the Instance

SSH into your instance:

```bash
# Get the public IP from job outputs
PUBLIC_IP="<from-job-outputs>"

# SSH using your key pair
ssh -i ~/.ssh/your-key.pem ubuntu@$PUBLIC_IP
```

### Checking Status

```bash
# Check Kamiwaza service
sudo systemctl status kamiwaza

# Check Docker containers
docker ps

# View application logs
sudo tail -f /var/log/kamiwaza-application.log

# View deployment logs
sudo cat /var/log/kamiwaza-deployment.log
```

### Service Management

```bash
# Restart Kamiwaza
sudo systemctl restart kamiwaza

# Stop Kamiwaza
sudo systemctl stop kamiwaza

# Start Kamiwaza
sudo systemctl start kamiwaza

# Restart all containers
cd /opt/kamiwaza
./containers-down.sh
./containers-up.sh
sudo systemctl restart kamiwaza
```

### User Provisioning

After Kamiwaza is running, you can provision users:

```bash
# SSH into the instance
ssh ubuntu@$PUBLIC_IP

# Create a CSV file with users
cat > /tmp/users.csv <<EOF
email,role
admin@kamiwaza.ai,operator
analyst@kamiwaza.ai,analyst
EOF

# Run provisioning script
cd /opt/kamiwaza
python3 scripts/provision_users.py --csv /tmp/users.csv
```

## Troubleshooting

### Deployment Fails

1. Check job logs in the UI
2. SSH into instance and check `/var/log/kamiwaza-deployment.log`
3. Verify GitHub token has correct permissions
4. Check AWS CloudFormation stack events

### Services Not Starting

```bash
# Check Docker
sudo systemctl status docker

# Check containers
docker ps -a

# Restart containers
cd /opt/kamiwaza
./containers-up.sh
```

### Cannot Access Kamiwaza UI

1. Verify security group allows HTTPS (port 443)
2. Check Traefik is running: `docker ps | grep traefik`
3. Check application logs: `sudo journalctl -u kamiwaza -n 100`
4. Verify certificate: `curl -k https://localhost`

### Keycloak Issues

```bash
# Check Keycloak container
docker ps | grep keycloak

# View Keycloak logs
docker logs default_kamiwaza-keycloak-web

# Restart Keycloak
docker restart default_kamiwaza-keycloak-web
```

### Database Connection Issues

```bash
# Check CockroachDB
docker ps | grep cockroach
docker logs default_kamiwaza-cockroachdb

# Check Milvus
docker ps | grep milvus
docker logs default_kamiwaza-milvus-standalone
```

## Security Considerations

### Production Deployment Checklist

- [ ] Use valid TLS certificates (not self-signed)
- [ ] Change default admin password
- [ ] Restrict security group rules to specific IP ranges
- [ ] Enable AWS CloudTrail logging
- [ ] Use AWS Secrets Manager for sensitive credentials
- [ ] Enable encryption at rest for EBS volumes
- [ ] Configure backup and disaster recovery
- [ ] Set up monitoring and alerting
- [ ] Review and harden Keycloak configuration
- [ ] Enable audit logging

### Network Security

```bash
# Recommended security group rules for production:
# - SSH (22): Only from your office/VPN IP range
# - HTTPS (443): From specific IP ranges or 0.0.0.0/0 for public access
# - All other ports: Blocked from external access
```

## Cleanup

### Destroy Deployment

To remove all resources:

1. Go to the job detail page
2. Click **"Destroy Stack"** (if using CDK)
3. Or manually:
   - Terminate EC2 instance
   - Delete CloudFormation stack
   - Remove EBS volumes

### Local Cleanup

```bash
# Remove generated files
rm -f /tmp/kamiwaza-userdata.b64
rm -f /tmp/userdata.b64
```

## Advanced Topics

### Distributed Ray Cluster

For multi-node Ray deployments:

1. Deploy head node using this guide
2. Note the head node's private IP
3. Deploy worker nodes with additional environment variables:
   ```bash
   export KAMIWAZA_HEAD_IP="<head-node-private-ip>"
   export KAMIWAZA_HEAD_PORT="6379"
   ```

### Custom Domain Setup

1. Allocate an Elastic IP
2. Associate with EC2 instance
3. Create DNS A record pointing to Elastic IP
4. Configure Traefik with your domain
5. Set up Let's Encrypt certificates

### Backup Strategy

```bash
# Create EBS snapshots
aws ec2 create-snapshot \
    --volume-id vol-xxx \
    --description "Kamiwaza data backup $(date +%Y-%m-%d)"

# Backup PostgreSQL databases
docker exec default_kamiwaza-cockroachdb \
    cockroach dump --insecure > backup.sql
```

## Support

For issues and questions:
- **Documentation**: https://code.kamiwaza.com/docs
- **GitHub**: https://github.com/kamiwaza-internal/kamiwaza/issues
- **Email**: support@kamiwaza.ai
- **Slack**: #kamiwaza-support

## See Also

- [AWS CDK Integration](AWS_CDK_INTEGRATION.md)
- [Main README](README.md)
- [Kamiwaza Documentation](https://code.kamiwaza.com/docs)
- [Deployment Manager Guide](DEPLOYMENT_MANAGER_README.md)
