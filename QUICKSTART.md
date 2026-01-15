# Quick Start Guide

Get the AWS EC2 Provisioning Service running in under 5 minutes.

## Prerequisites Checklist

- [ ] Python 3.9 or higher installed
- [ ] Terraform installed (`terraform --version`)
- [ ] Docker installed (for Redis)
- [ ] AWS credentials configured (for testing)
- [ ] Git installed

## Step-by-Step Setup

### 1. Clone and Navigate

```bash
cd kz-demo-provisioning
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:
```bash
APP_ADMIN_USER=admin
APP_ADMIN_PASS=your-secure-password

# Email (choose one):
EMAIL_PROVIDER=ses
SES_FROM_EMAIL=your-email@example.com

# Or for SMTP:
# EMAIL_PROVIDER=smtp
# SMTP_HOST=smtp.gmail.com
# SMTP_USER=your-email@gmail.com
# SMTP_PASS=your-app-password
```

### 5. Initialize Database

```bash
python -c "from app.database import init_db; init_db()"
```

### 6. Start Redis

**Option A: Using Docker (Recommended)**
```bash
docker run -d --name kz-redis -p 6379:6379 redis:7-alpine
```

**Option B: Using docker-compose**
```bash
docker-compose -f docker-compose.dev.yml up -d
```

**Option C: Local Redis Installation**
```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis
```

### 7. Start the Application

Open **THREE terminal windows** (all with venv activated):

**Terminal 1 - Web Server:**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 - Background Worker:**
```bash
celery -A worker.celery_app worker --loglevel=info
```

**Terminal 3 - Optional Monitoring:**
```bash
# Watch logs
tail -f app.db  # Or use your preferred log viewer
```

### 8. Access the Application

Open your browser and navigate to:
```
http://localhost:8000
```

Login with:
- **Username**: `admin`
- **Password**: (what you set in `.env`)

## Create Your First Job

1. Click **"Create New Job"**

2. Fill in the form:
   ```
   Job Name: my-first-job
   Requester Email: your-email@example.com

   AWS Region: us-east-1
   Auth Method: AssumeRole
   Role ARN: arn:aws:iam::YOUR-ACCOUNT-ID:role/YOUR-ROLE

   Instance Type: t3.micro
   Volume Size: 30 GB

   Docker Containers (JSON):
   [
     {
       "name": "nginx",
       "image": "nginx:latest",
       "ports": ["80:80"],
       "restart": "unless-stopped"
     }
   ]
   ```

3. **(Optional)** Upload a CSV file with users:
   ```csv
   email
   admin@example.com
   user1@example.com
   ```

4. Click **"Create Job"**

5. On the job detail page, click **"Start Job"**

6. Watch the logs update in real-time!

## Verify Everything Works

### Check Redis Connection
```bash
docker exec -it kz-redis redis-cli ping
# Should return: PONG
```

### Check Celery Worker
```bash
celery -A worker.celery_app inspect active
# Should show worker is running
```

### Check Database
```bash
sqlite3 app.db "SELECT COUNT(*) FROM jobs;"
# Should show number of jobs
```

## Common Issues & Solutions

### Issue: "ModuleNotFoundError"
**Solution**: Make sure virtual environment is activated and dependencies are installed:
```bash
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Issue: "Connection refused" to Redis
**Solution**: Start Redis:
```bash
docker start kz-redis
# Or
redis-server
```

### Issue: Worker not picking up tasks
**Solution**:
1. Check Redis is running
2. Restart worker
3. Verify `REDIS_URL` in `.env` matches your Redis instance

### Issue: "AssumeRole failed"
**Solution**:
1. Verify your AWS credentials: `aws sts get-caller-identity`
2. Check role ARN is correct
3. Verify trust policy on the role allows your principal
4. Check external ID if using one

### Issue: Terraform not found
**Solution**: Install Terraform:
```bash
# macOS
brew install terraform

# Linux
wget https://releases.hashicorp.com/terraform/1.6.0/terraform_1.6.0_linux_amd64.zip
unzip terraform_1.6.0_linux_amd64.zip
sudo mv terraform /usr/local/bin/

# Windows
choco install terraform
```

### Issue: Permission denied errors
**Solution**: Check IAM permissions for your AWS role/user. Required:
- `ec2:*`
- `iam:CreateRole`, `iam:AttachRolePolicy`, etc.
- `sts:AssumeRole`

## Development Workflow

### Running Tests
```bash
pytest tests/ -v
```

### Code Formatting
```bash
pip install black isort
black app/ worker/ tests/
isort app/ worker/ tests/
```

### Clean Up
```bash
# Stop all processes (Ctrl+C in each terminal)

# Clean database and temp files
rm app.db
rm -rf jobs_workdir/
rm -rf uploads/

# Stop Redis
docker stop kz-redis
docker rm kz-redis
```

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check [ARCHITECTURE.md](ARCHITECTURE.md) for system design details
- Review [examples/](examples/) for sample configurations
- Explore the code in [app/](app/) and [worker/](worker/)

## Makefile Commands (Alternative)

If you prefer using Make:

```bash
make install      # Install dependencies
make db-init      # Initialize database
make redis        # Start Redis in Docker
make run          # Start web server
make worker       # Start Celery worker
make test         # Run tests
make clean        # Clean temporary files
```

## Getting Help

If you encounter issues:

1. Check the logs in each terminal window
2. Review the [README.md](README.md) troubleshooting section
3. Check job logs in the web UI
4. Verify AWS credentials and permissions
5. Ensure all services (Redis, FastAPI, Celery) are running

## Production Deployment

For production deployment:

1. Use PostgreSQL instead of SQLite
2. Use managed Redis (AWS ElastiCache)
3. Deploy FastAPI behind a load balancer with HTTPS
4. Run multiple Celery workers
5. Use AWS Secrets Manager for credentials
6. Enable CloudWatch logging
7. Set up monitoring and alerts

See README.md "Security Considerations" section for production hardening checklist.

---

**Ready to provision?** Access the UI at http://localhost:8000 and create your first job!
