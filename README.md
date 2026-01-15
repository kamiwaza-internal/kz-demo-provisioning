# AWS EC2 Provisioning Service

A web application that provisions EC2 instances into specified AWS accounts using Terraform, deploys Docker containers from DockerHub, configures application users from an uploaded CSV, and sends email notifications upon completion.

## Features

- **Web UI** for creating and managing provisioning jobs
- **AWS Authentication** via AssumeRole (preferred) or Access Keys
- **Terraform Integration** for safe, isolated EC2 provisioning
- **Docker Deployment** via docker-compose on EC2
- **User Management** via CSV upload with validation
- **Email Notifications** via AWS SES or SMTP
- **Background Processing** with Celery for long-running jobs
- **Real-time Logs** with live updates in the UI
- **Security Features**: CSRF protection, basic auth, credential isolation

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Web UI     │────▶│  FastAPI     │────▶│   SQLite    │
│  (Browser)  │     │  (Backend)   │     │  (Database) │
└─────────────┘     └──────────────┘     └─────────────┘
                            │
                            ▼
                    ┌──────────────┐     ┌─────────────┐
                    │    Celery    │────▶│   Redis     │
                    │   (Worker)   │     │  (Broker)   │
                    └──────────────┘     └─────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  Terraform   │
                    │  (Executor)  │
                    └──────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   AWS EC2    │
                    │  + Docker    │
                    └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.9+
- Terraform 1.0+
- Redis (for Celery)
- AWS credentials with appropriate permissions

### Installation

1. **Clone the repository**
   ```bash
   cd kz-demo-provisioning
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   make install
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Initialize database**
   ```bash
   make db-init
   ```

6. **Start Redis** (if not already running)
   ```bash
   make redis
   ```

### Running the Application

Open **three terminal windows**:

**Terminal 1 - Web Server:**
```bash
make run
```
Access UI at http://localhost:8000

**Terminal 2 - Background Worker:**
```bash
make worker
```

**Terminal 3 - Redis (if not using Docker):**
```bash
redis-server
```

Default credentials: `admin` / `changeme123`

## Configuration

### Environment Variables

Edit `.env` file:

```bash
# App Authentication
APP_ADMIN_USER=admin
APP_ADMIN_PASS=changeme123
SECRET_KEY=your-secret-key-here

# Database
DATABASE_URL=sqlite:///./app.db

# Redis
REDIS_URL=redis://localhost:6379/0

# Email Configuration
EMAIL_PROVIDER=ses  # or smtp
SES_REGION=us-east-1
SES_FROM_EMAIL=noreply@example.com

# Security
ALLOWED_REGIONS=us-east-1,us-west-2,eu-west-1
ALLOWED_INSTANCE_TYPES=t3.micro,t3.small,t3.medium
ALLOW_ACCESS_KEY_AUTH=false

# Terraform
TERRAFORM_BINARY=terraform
JOBS_WORKDIR=./jobs_workdir
```

### AWS Permissions

The IAM role or credentials used must have permissions for:

- `sts:AssumeRole` (if using AssumeRole)
- `ec2:*` (for provisioning instances)
- `iam:CreateRole`, `iam:AttachRolePolicy`, etc. (for creating instance profiles)
- `sts:GetCallerIdentity` (for verification)

The **target role** being assumed must have:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:*",
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:CreateInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:PassRole"
      ],
      "Resource": "*"
    }
  ]
}
```

## Usage

### Creating a Job

1. Navigate to http://localhost:8000
2. Click **"Create New Job"**
3. Fill in the form:
   - **Basic Info**: Job name, requester email
   - **AWS Config**: Region, auth method, role ARN
   - **Network**: VPC, subnet, security groups (optional)
   - **EC2**: Instance type, volume size, AMI
   - **Docker**: Container configurations (JSON)
   - **Users**: CSV file (optional)
4. Submit the form
5. On the job detail page, click **"Start Job"**

### CSV Format

Upload a CSV with user data for your containerized applications:

```csv
username,email,role,display_name
admin,admin@example.com,admin,Administrator
user1,user1@example.com,user,User One
user2,user2@example.com,user,User Two
```

**Required columns**: `username`, `email`
**Optional columns**: `role`, `display_name`

The CSV will be:
- Saved to `/opt/app/users.csv` on the EC2 instance
- Provided as `APP_USERS_B64` environment variable (base64 encoded)

### Docker Configuration

Container configuration format:

```json
[
  {
    "name": "webapp",
    "image": "nginx:latest",
    "ports": ["80:80", "443:443"],
    "environment": {
      "ENV_VAR": "value"
    },
    "volumes": ["/opt/app:/usr/share/nginx/html"],
    "restart": "unless-stopped"
  }
]
```

### Monitoring Jobs

- **Dashboard**: View all jobs and their status
- **Job Detail**: View logs, outputs, and configuration
- **Live Logs**: Auto-refresh while job is running
- **Email**: Receive notification on completion

## Security Considerations

### Implemented

- ✅ **CSRF Protection** on all state-changing operations
- ✅ **HTTP Basic Auth** for UI access
- ✅ **AssumeRole** preferred over access keys
- ✅ **No credential storage** in database
- ✅ **Isolated Terraform workspaces** per job
- ✅ **Input validation** on all user inputs
- ✅ **Region/instance type allowlists**
- ✅ **IMDSv2** enforced on EC2 instances
- ✅ **Encrypted EBS volumes**

### Recommendations for Production

1. **Replace Basic Auth** with OIDC/SAML (e.g., Auth0, Okta)
2. **Use Secrets Manager** for sensitive configuration
3. **Enable CloudTrail** for audit logging
4. **Implement rate limiting** on API endpoints
5. **Add TLS/HTTPS** with valid certificates
6. **Restrict SSH** in security groups to specific CIDRs
7. **Use AWS PrivateLink** for VPC isolation
8. **Enable GuardDuty** for threat detection
9. **Implement job timeouts** and resource limits
10. **Add webhook callbacks** instead of polling

## Development

### Running Tests

```bash
make test
```

### Code Formatting

```bash
make format
```

### Linting

```bash
make lint
```

### Cleanup

```bash
make clean
```

## Project Structure

```
kz-demo-provisioning/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── models.py            # Database models
│   ├── schemas.py           # Pydantic schemas
│   ├── database.py          # Database setup
│   ├── config.py            # Settings
│   ├── auth.py              # Authentication
│   ├── aws_handler.py       # AWS/STS operations
│   ├── terraform_runner.py  # Terraform execution
│   ├── csv_handler.py       # CSV parsing
│   ├── email_service.py     # Email notifications
│   └── templates/           # HTML templates
│       ├── base.html
│       ├── dashboard.html
│       ├── job_new.html
│       └── job_detail.html
├── worker/
│   ├── __init__.py
│   ├── celery_app.py        # Celery configuration
│   └── tasks.py             # Background tasks
├── terraform/
│   ├── main.tf              # Main infrastructure
│   ├── variables.tf         # Input variables
│   └── outputs.tf           # Output values
├── tests/
│   ├── test_csv_handler.py
│   └── test_validators.py
├── requirements.txt
├── Makefile
├── .env.example
└── README.md
```

## API Endpoints

- `GET /` - Dashboard
- `GET /jobs/new` - New job form
- `POST /jobs` - Create job
- `GET /jobs/{id}` - Job details
- `POST /jobs/{id}/run` - Start job
- `GET /api/jobs/{id}` - Job data (JSON)
- `GET /api/jobs/{id}/logs` - Job logs (JSON, for polling)
- `GET /health` - Health check

## Troubleshooting

### Redis Connection Error

```bash
# Start Redis
make redis

# Or if using system Redis
redis-server
```

### Terraform Not Found

```bash
# Install Terraform
brew install terraform  # macOS
# or download from https://www.terraform.io/downloads
```

### Database Locked

```bash
# Stop all processes and reinitialize
make clean
make db-init
```

### AssumeRole Failed

Check:
1. Role ARN is correct
2. External ID matches (if required)
3. Trust policy allows your principal
4. Permissions boundary allows required actions

## Next Improvements

### Security
- Integrate with AWS Secrets Manager for credential management
- Add OIDC/SAML authentication (Auth0, Okta, AWS SSO)
- Implement per-tenant resource isolation
- Add comprehensive audit logging with CloudTrail integration
- Enable mTLS for service-to-service communication

### Features
- Multi-cloud support (Azure, GCP)
- Job scheduling and cron triggers
- Resource cost estimation before provisioning
- Instance snapshots and backups
- Auto-scaling group support
- Blue/green deployments
- Rollback capabilities

### Operations
- Grafana dashboards for monitoring
- Prometheus metrics export
- Distributed tracing with OpenTelemetry
- Health checks for provisioned services
- Automated cleanup of old resources
- Terraform state management (S3 backend)

### User Experience
- React/Vue.js SPA frontend
- WebSocket for real-time updates
- Job templates library
- Bulk operations support
- Advanced filtering and search

## License

Proprietary - Internal Use Only

## Support

For issues and questions, contact: devops@example.com
