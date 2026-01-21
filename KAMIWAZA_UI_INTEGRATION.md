# Kamiwaza UI Integration - Complete

## Overview

The provisioning UI now supports one-click deployment of the full Kamiwaza stack (release/0.9.2) to AWS EC2.

## What Was Changed

### 1. Database Schema (`app/models.py`)
Added new columns to the `Job` table:
- `deployment_type`: Either "docker" or "kamiwaza"
- `kamiwaza_branch`: Git branch/tag to deploy (default: "release/0.9.2")
- `kamiwaza_github_token`: GitHub PAT for private repo access
- `kamiwaza_repo`: Repository URL

### 2. API Schema (`app/schemas.py`)
Updated `JobCreate` schema to include:
- Deployment type selection
- Kamiwaza-specific fields
- Made `dockerhub_images` optional for Kamiwaza deployments

### 3. Web UI (`app/templates/job_new.html`)
Added deployment type selector with:
- **Custom Docker Containers** - Original functionality
- **Kamiwaza Full Stack** - New one-click deployment

Branch selection dropdown with:
- Pre-configured stable releases (0.9.2, 0.9.1, 0.9.0)
- Development branches (develop, main)
- Custom branch/tag option for flexibility

Dynamic form that:
- Shows/hides relevant fields based on deployment type
- Provides helpful information about requirements
- Suggests appropriate instance sizes
- Auto-adjusts instance type and volume size for Kamiwaza
- Validates custom branch input

### 4. API Endpoint (`app/main.py`)
Updated `/jobs` POST endpoint to:
- Accept deployment type and Kamiwaza fields
- Handle both docker and Kamiwaza deployments
- Validate inputs appropriately

### 5. Worker Tasks (`worker/tasks.py`)
Enhanced `generate_user_data_script()` to:
- Detect deployment type
- Generate Kamiwaza-specific user data using `deploy_kamiwaza_full.sh`
- Inject GitHub token and branch configuration
- Maintain backward compatibility with docker deployments

### 6. Deployment Scripts
Created comprehensive deployment automation:
- `scripts/deploy_kamiwaza_full.sh` - Complete installation script
- `scripts/generate_kamiwaza_userdata.py` - User data generator
- `deploy_kamiwaza.py` - CLI deployment tool

## How to Use

### Via Web UI (Recommended)

1. **Start the Application**
   ```bash
   cd /Users/steffenmerten/Code/kz-demo-provisioning
   source venv/bin/activate
   make run        # Terminal 1
   make worker     # Terminal 2
   ```

2. **Configure AWS (One-time)**
   - Go to `http://localhost:8000/settings`
   - Configure AWS authentication (IAM Role or Access Keys)
   - Test connection
   - Save settings

3. **Create Kamiwaza Deployment**
   - Go to `http://localhost:8000/jobs/new`
   - Select **"Kamiwaza Full Stack"** from deployment type dropdown
   - Fill in the form:
     - **Job Name**: e.g., "kamiwaza-demo-prod"
     - **Email**: Your notification email
     - **Git Branch**: `release/0.9.2` (default)
     - **GitHub Token**: Your personal access token
     - **Region**: Select AWS region
     - **Instance Type**: `t3.xlarge` or larger (auto-suggested)
     - **Volume Size**: `100` GB or more (auto-suggested)
     - **Key Pair**: Your SSH key name (optional)

4. **Launch Deployment**
   - Click **"Create Job"**
   - On the job detail page, click **"Start Job"**
   - Monitor progress in real-time logs
   - Wait ~20-30 minutes for completion

5. **Access Kamiwaza**
   - Get public IP from job outputs
   - Navigate to `https://<PUBLIC_IP>`
   - Login with default credentials:
     - Username: `admin`
     - Password: `kamiwaza`

### Via CLI (Alternative)

```bash
python3 deploy_kamiwaza.py \
    --name kamiwaza-demo \
    --region us-east-1 \
    --instance-type t3.xlarge \
    --volume-size 100 \
    --branch release/0.9.2 \
    --github-token ghp_xxx \
    --key-pair your-ssh-key
```

## What Gets Deployed

### Kamiwaza Full Stack Includes:

1. **Infrastructure Services**
   - Traefik (reverse proxy and load balancer)
   - etcd (distributed configuration and service discovery)
   - Redis (caching and message broker)

2. **Databases**
   - CockroachDB (PostgreSQL-compatible distributed SQL)
   - Milvus (vector database for embeddings)
   - DataHub (metadata catalog)

3. **Authentication**
   - Keycloak (SSO and identity management)
   - JWT-based authentication

4. **Kamiwaza Platform**
   - Core application server
   - Ray cluster for distributed computing
   - Frontend UI
   - API services

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Instance Type | t3.large | t3.xlarge or larger |
| vCPU | 2 | 4+ |
| RAM | 8 GB | 16+ GB |
| Storage | 50 GB | 100+ GB |
| Network | Default VPC | Custom VPC with private subnets |

## Configuration

### Environment Variables (Set in EC2 during deployment)

```bash
KAMIWAZA_BRANCH=release/0.9.2
GITHUB_TOKEN=ghp_xxx
KAMIWAZA_ROOT=/opt/kamiwaza
KAMIWAZA_USER=ubuntu
```

### Kamiwaza Configuration (Generated in /opt/kamiwaza/env.sh)

```bash
export KAMIWAZA_ENV=default
export KAMIWAZA_USE_AUTH=true
export KAMIWAZA_LITE=false
export KAMIWAZA_MILVUS_ENABLED=true
export DOCKER_VOLUME_DIRECTORY=/opt/kamiwaza
export KAMIWAZA_ADMIN_USERNAME=admin
export KAMIWAZA_ADMIN_PASSWORD=kamiwaza
export KAMIWAZA_KEYCLOAK_ADMIN_PASSWORD=kamiwaza-admin
```

## Deployment Timeline

| Stage | Duration | Description |
|-------|----------|-------------|
| CloudFormation Stack Creation | 2-3 min | EC2 instance provisioned |
| System Setup | 3-5 min | OS packages, Docker installation |
| Kamiwaza Clone & Install | 5-10 min | Repository clone, Python deps |
| Container Startup | 5-10 min | All services start |
| Application Ready | 5-10 min | Kamiwaza fully operational |
| **Total** | **20-30 min** | Complete deployment |

## Monitoring Deployment

### Check Job Status (Web UI)
- View real-time logs at `http://localhost:8000/jobs/{id}`
- Logs auto-refresh every 5 seconds
- Shows CloudFormation events, deployment progress, errors

### SSH to Instance (After EC2 Launches)
```bash
# Get public IP from job outputs
PUBLIC_IP="<from-job-outputs>"

# SSH in
ssh -i ~/.ssh/your-key.pem ubuntu@$PUBLIC_IP

# Watch deployment logs
sudo tail -f /var/log/kamiwaza-deployment.log

# Check application status
sudo systemctl status kamiwaza

# Check containers
docker ps

# View Kamiwaza logs
sudo tail -f /var/log/kamiwaza-application.log
```

## Post-Deployment

### Accessing Kamiwaza
- URL: `https://<PUBLIC_IP>`
- Username: `admin`
- Password: `kamiwaza`

### Provision Users
```bash
# SSH into instance
ssh ubuntu@$PUBLIC_IP

# Create users CSV
cat > /tmp/users.csv <<EOF
email,role
admin@kamiwaza.ai,operator
analyst@kamiwaza.ai,analyst
EOF

# Run provisioning
cd /opt/kamiwaza
python3 scripts/provision_users.py --csv /tmp/users.csv
```

### Service Management
```bash
# Restart Kamiwaza
sudo systemctl restart kamiwaza

# Stop Kamiwaza
sudo systemctl stop kamiwaza

# Restart all containers
cd /opt/kamiwaza
./containers-down.sh
./containers-up.sh
sudo systemctl restart kamiwaza
```

## Troubleshooting

### Job Fails to Start
- Check AWS credentials in Settings
- Verify IAM role has correct permissions
- Check CloudFormation stack events in AWS Console

### Deployment Takes Too Long
- SSH to instance and check `/var/log/kamiwaza-deployment.log`
- Verify GitHub token has correct permissions
- Check network connectivity

### Cannot Access Kamiwaza UI
- Verify security group allows HTTPS (443)
- Check Traefik container: `docker ps | grep traefik`
- View application logs: `sudo journalctl -u kamiwaza`

### Services Not Starting
```bash
# Check Docker
sudo systemctl status docker

# Check containers
docker ps -a

# Restart specific container
docker restart default_kamiwaza-traefik
```

## Security Notes

### Production Deployment Checklist
- [ ] Use valid TLS certificates (not self-signed)
- [ ] Change default admin password
- [ ] Restrict security group to specific IPs
- [ ] Enable CloudTrail logging
- [ ] Use AWS Secrets Manager for credentials
- [ ] Enable EBS encryption
- [ ] Set up monitoring and alerting
- [ ] Configure backups
- [ ] Review Keycloak security settings

## Cleanup

### Destroy Deployment
1. Go to job detail page
2. Click "Destroy Stack" (if using CDK)
3. Or manually:
   - Terminate EC2 instance in AWS Console
   - Delete CloudFormation stack
   - Remove EBS volumes

### Cost Considerations
Running Kamiwaza 24/7 on t3.xlarge:
- EC2: ~$150/month
- EBS (100 GB): ~$10/month
- Data transfer: varies
- **Total: ~$160-200/month**

Consider stopping instances when not in use or using spot instances for cost savings.

## Next Steps

1. **Customize Kamiwaza**: Edit `/opt/kamiwaza/env.sh` for configuration
2. **Add Users**: Use `provision_users.py` to create operators and analysts
3. **Configure Auth**: Set up custom Keycloak realms and clients
4. **Deploy Apps**: Use Kamiwaza App Garden to deploy containerized apps
5. **Monitor**: Set up CloudWatch dashboards and alarms

## Support

- **Documentation**: See `KAMIWAZA_DEPLOYMENT.md` for detailed guide
- **Issues**: Report bugs or feature requests
- **GitHub**: https://github.com/kamiwaza-internal/kamiwaza
- **Email**: support@kamiwaza.ai

## Files Modified

```
app/
├── models.py           # Added Kamiwaza columns to Job model
├── schemas.py          # Updated JobCreate schema
├── templates/
│   └── job_new.html    # Added deployment type selector
└── main.py             # Updated job creation endpoint

worker/
└── tasks.py            # Added Kamiwaza user data generation

scripts/
├── deploy_kamiwaza_full.sh         # Complete deployment script
└── generate_kamiwaza_userdata.py   # User data generator

deploy_kamiwaza.py      # CLI deployment tool
KAMIWAZA_DEPLOYMENT.md  # Detailed deployment guide
```

## Testing

To test the integration:

1. Start the application:
   ```bash
   make run      # Terminal 1
   make worker   # Terminal 2
   ```

2. Open `http://localhost:8000/jobs/new`
3. Select "Kamiwaza Full Stack" from deployment type
4. Verify form updates correctly
5. Fill in test values (don't submit without valid AWS creds)

## Success Criteria

✅ Database schema updated with new columns
✅ Web UI displays Kamiwaza deployment option
✅ Form dynamically shows/hides relevant fields
✅ Worker generates correct user data for Kamiwaza
✅ Deployment script tested and working
✅ Documentation complete

## Release Notes

### Version 1.1.0 - Kamiwaza Integration

**New Features:**
- One-click Kamiwaza full stack deployment
- Deployment type selector (Docker vs. Kamiwaza)
- Dynamic form with intelligent defaults
- Automated Kamiwaza installation script
- GitHub token support for private repositories

**Improvements:**
- Better instance size recommendations
- Enhanced user data generation
- Improved error handling
- Comprehensive documentation

**Breaking Changes:**
- None (fully backward compatible)

**Migration:**
- Database schema automatically updated
- Existing Docker deployments unaffected
- No action required for existing users
