# Quick Start: Deploy Kamiwaza via UI

## 🚀 One-Click Deployment to AWS EC2

Your provisioning UI now supports deploying the full Kamiwaza platform (release/0.9.2) with just a few clicks.

## Prerequisites

1. **AWS Credentials Configured**
   - IAM Role with EC2 provisioning permissions
   - Or AWS Access Keys

2. **GitHub Personal Access Token** (for private repository)
   - Go to: https://github.com/settings/tokens
   - Generate new token with `repo` scope
   - Save it securely

## Step-by-Step

### 1. Start the Application

```bash
cd /Users/steffenmerten/Code/kz-demo-provisioning

# Terminal 1 - Web Server
source venv/bin/activate
make run

# Terminal 2 - Background Worker
source venv/bin/activate
make worker
```

### 2. Configure AWS (First Time Only)

1. Open http://localhost:8000/settings
2. Select your authentication method:
   - **IAM Role (Recommended)**: Enter Role ARN and External ID
   - **Access Keys**: Enter AWS Access Key and Secret Key
3. Click "Test Connection"
4. Click "Save Configuration"

### 3. Create Kamiwaza Deployment

1. Go to http://localhost:8000/jobs/new
2. Select **"Kamiwaza Full Stack"** from the "What would you like to deploy?" dropdown

The form will automatically:
- Show Kamiwaza-specific configuration fields
- Hide Docker container configuration
- Suggest t3.xlarge instance type
- Suggest 100 GB volume size

### 4. Fill in the Form

**Basic Information:**
- Job Name: `kamiwaza-demo` (or your preferred name)
- Requester Email: `your@email.com`

**Kamiwaza Configuration:**
- Git Branch/Release: Select from dropdown:
  - `release/0.9.2` (Stable - Recommended) ✅
  - `release/0.9.1` (Previous Stable)
  - `release/0.9.0` (Previous Stable)
  - `develop` (Latest Development)
  - `main` (Main Branch)
  - `Custom Branch/Tag...` (Enter any branch, tag, or commit)
- GitHub Token: `ghp_your_token_here` (required for private repo)

**AWS Region:**
- Region: `us-east-1` (or your preferred region)

**Network Configuration (Optional):**
- Leave empty for default VPC
- Or specify your VPC ID, Subnet ID, etc.

**EC2 Configuration:**
- Instance Type: `t3.xlarge` (minimum recommended)
- Volume Size: `100` GB (minimum recommended)
- Key Pair: Your SSH key name (for SSH access)
- AMI ID: Leave empty for latest Amazon Linux 2023
- Tags: Optional JSON tags

### 5. Launch Deployment

1. Click **"Create Job"**
2. You'll be redirected to the job detail page
3. Click **"Start Job"**
4. Watch real-time logs as deployment progresses

### 6. Wait for Completion

Deployment takes approximately **20-30 minutes**:
- ⏱️ 2-3 min: EC2 instance provisioned
- ⏱️ 3-5 min: System setup (Docker, dependencies)
- ⏱️ 5-10 min: Kamiwaza installation
- ⏱️ 5-10 min: Container startup
- ⏱️ 5-10 min: Application ready

### 7. Access Kamiwaza

Once deployment completes:

1. **Get the Public IP** from job outputs
2. **Navigate to**: `https://<PUBLIC_IP>`
3. **Accept the security warning** (self-signed certificate)
4. **Login** with:
   - Username: `admin`
   - Password: `kamiwaza`

🎉 **You're now running Kamiwaza!**

## What You Get

Your deployment includes:

✅ **Infrastructure**
- Traefik (reverse proxy)
- etcd (configuration)
- Redis (caching)

✅ **Databases**
- CockroachDB (SQL)
- Milvus (vector database)
- DataHub (catalog)

✅ **Authentication**
- Keycloak (SSO)

✅ **Kamiwaza Platform**
- Core application
- Ray cluster
- Web UI

## Monitoring Deployment

### From the UI
- Real-time logs at http://localhost:8000/jobs/{id}
- Auto-refreshes every 5 seconds
- Shows all deployment stages

### Via SSH (After Instance Launches)
```bash
# Get IP from job outputs
PUBLIC_IP="<your-instance-ip>"

# SSH in
ssh -i ~/.ssh/your-key.pem ubuntu@$PUBLIC_IP

# Watch deployment logs
sudo tail -f /var/log/kamiwaza-deployment.log

# Check Kamiwaza status
sudo systemctl status kamiwaza

# Check containers
docker ps
```

## Troubleshooting

### "AWS authentication failed"
- Check AWS credentials in Settings
- Verify IAM role has EC2 permissions
- Test connection in Settings page

### "Failed to clone repository"
- Verify GitHub token has `repo` scope
- Check token hasn't expired
- Try regenerating token

### "Deployment taking too long"
- SSH to instance (see command above)
- Check `/var/log/kamiwaza-deployment.log`
- Look for errors in the logs

### "Cannot access UI"
- Wait full 30 minutes for deployment
- Check security group allows HTTPS (443)
- Try HTTP first: `http://<PUBLIC_IP>`

## Cost Estimate

Running Kamiwaza 24/7 on t3.xlarge:
- **EC2**: ~$150/month
- **Storage**: ~$10/month
- **Total**: ~$160-200/month

💡 **Tip**: Stop the instance when not in use to save costs

## Next Steps

Once Kamiwaza is running:

1. **Change Password**: Go to Settings → Change admin password
2. **Add Users**: Use the provisioning scripts or Keycloak UI
3. **Explore Features**: Navigate through the Kamiwaza UI
4. **Deploy Apps**: Use App Garden to deploy applications
5. **Configure**: Customize settings in `/opt/kamiwaza/env.sh`

## Cleanup

When done testing:

1. Go to job detail page
2. Note the instance ID
3. In AWS Console:
   - EC2 → Instances → Terminate instance
   - CloudFormation → Delete stack
   - EBS → Delete volumes

Or use AWS CLI:
```bash
aws ec2 terminate-instances --instance-ids i-xxxxx
```

## Support

- 📖 **Full Guide**: See `KAMIWAZA_DEPLOYMENT.md`
- 📖 **Integration Details**: See `KAMIWAZA_UI_INTEGRATION.md`
- 🐛 **Issues**: Report bugs or ask questions
- 📧 **Email**: support@kamiwaza.ai

## Example Session

```
$ cd /Users/steffenmerten/Code/kz-demo-provisioning
$ make run
✓ Starting web server on http://localhost:8000

# In browser: http://localhost:8000/jobs/new
# Select "Kamiwaza Full Stack"
# Fill in form
# Click "Create Job" → "Start Job"

# Watch logs...
[2026-01-20 10:00:00] Job execution started
[2026-01-20 10:01:30] ✓ Assumed role successfully
[2026-01-20 10:02:00] Deploying EC2 instance with AWS CDK...
[2026-01-20 10:05:00] ✓ CDK deployment completed successfully
[2026-01-20 10:05:00] Instance ID: i-0123456789abcdef0
[2026-01-20 10:05:00] Public IP: 54.123.45.67
[2026-01-20 10:25:00] Kamiwaza Deployment Completed!

# Access: https://54.123.45.67
# Login: admin / kamiwaza
# ✅ Success!
```

---

**Ready to deploy? Start at Step 1 above! 🚀**
