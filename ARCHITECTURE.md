# Architecture Documentation

## System Overview

The AWS EC2 Provisioning Service is a full-stack web application that automates the provisioning of EC2 instances with Docker containers using Terraform. The system follows a modern, event-driven architecture with clear separation of concerns.

## Component Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         Web Browser                             │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │   HTML/CSS/JS    │  │  Live Log Poll   │                    │
│  │   (Templates)    │  │  (JavaScript)    │                    │
│  └────────┬─────────┘  └────────┬─────────┘                    │
└───────────┼─────────────────────┼──────────────────────────────┘
            │                     │
            │ HTTP (Basic Auth)   │ AJAX Polling
            │ CSRF Protected      │
            ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                          │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Routes (app/main.py)                                   │    │
│  │  - Dashboard, Job CRUD, API endpoints                   │    │
│  └──┬──────────────────────────────────────────────────┬──┘    │
│     │                                                    │       │
│  ┌──▼─────────┐  ┌──────────┐  ┌──────────┐  ┌────────▼────┐  │
│  │   Auth     │  │  Schemas │  │  Config  │  │   Models    │  │
│  │ (Basic +   │  │(Pydantic)│  │(Settings)│  │ (SQLAlchemy)│  │
│  │   CSRF)    │  └──────────┘  └──────────┘  └─────────────┘  │
│  └────────────┘                                                 │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Business Logic                                         │    │
│  │  - CSV Handler      - AWS Handler (STS)                │    │
│  │  - Email Service    - Terraform Runner                 │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────┬────────────────────┬────────────────────┘
                       │                    │
                       │ Enqueue Task       │ Read/Write
                       │                    │
                       ▼                    ▼
         ┌──────────────────────┐   ┌─────────────┐
         │  Redis (Broker)      │   │   SQLite    │
         │  - Task Queue        │   │  - Jobs     │
         │  - Results Backend   │   │  - Logs     │
         └──────┬───────────────┘   │  - Files    │
                │                   └─────────────┘
                │ Consume Task
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Celery Worker                              │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  worker/tasks.py                                        │    │
│  │  - execute_provisioning_job()                           │    │
│  │  - generate_user_data_script()                          │    │
│  │  - send_completion_email()                              │    │
│  └────┬───────────────────────────────────────────┬───────┘    │
│       │                                            │            │
│       ▼                                            ▼            │
│  ┌──────────────────┐                   ┌──────────────────┐   │
│  │  AWS Handler     │                   │ Email Service    │   │
│  │  - AssumeRole    │                   │ - SES / SMTP     │   │
│  │  - Get Identity  │                   └──────────────────┘   │
│  └────┬─────────────┘                                           │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────────────────────────────────────────────────┐     │
│  │  Terraform Runner                                     │     │
│  │  - Isolated workspace per job                        │     │
│  │  - Init -> Validate -> Plan -> Apply                 │     │
│  │  - Stream logs to database                           │     │
│  └────┬─────────────────────────────────────────────────┘     │
└───────┼──────────────────────────────────────────────────────-─┘
        │
        │ AWS API Calls (via assumed credentials)
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                           AWS Cloud                             │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Terraform Managed Resources                           │    │
│  │                                                         │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │    │
│  │  │  EC2        │  │ Security     │  │ IAM Role +   │  │    │
│  │  │  Instance   │──│ Group        │  │ Instance     │  │    │
│  │  │             │  │              │  │ Profile      │  │    │
│  │  └─────┬───────┘  └──────────────┘  └──────────────┘  │    │
│  │        │                                                │    │
│  │        │ User Data Script                              │    │
│  │        │                                                │    │
│  │        ▼                                                │    │
│  │  ┌──────────────────────────────────────────────┐     │    │
│  │  │  Docker Engine                                │     │    │
│  │  │  - docker-compose.yml                        │     │    │
│  │  │  - Multiple containers from DockerHub        │     │    │
│  │  │  - /opt/app/users.csv                        │     │    │
│  │  │  - APP_USERS_B64 env var                     │     │    │
│  │  └──────────────────────────────────────────────┘     │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Job Creation Flow

```
User → Web UI → FastAPI → CSV Validation → Database (Job Created)
                                ↓
                          File Upload → Store CSV → Parse Users
```

### 2. Job Execution Flow

```
User Clicks "Run" → FastAPI → Celery Task Enqueued → Redis
                                          ↓
                              Celery Worker Picks Up Task
                                          ↓
                              ┌───────────┴────────────┐
                              ▼                        ▼
                    AWS STS AssumeRole      Log to Database
                              ↓
                    Prepare Terraform Workspace
                              ↓
                    Generate User Data Script
                    (includes docker-compose.yml + users.csv)
                              ↓
                    Run Terraform: init → validate → apply
                    (Stream logs to database in real-time)
                              ↓
                    Extract Terraform Outputs
                    (instance_id, public_ip, private_ip)
                              ↓
                    Update Job Status → Success/Failed
                              ↓
                    Send Email Notification
```

### 3. Log Streaming Flow

```
Web Browser → Poll /api/jobs/{id}/logs?after={last_id} every 2s
                              ↓
                    FastAPI queries new logs from DB
                              ↓
                    Return JSON with new logs + job status
                              ↓
                    JavaScript appends logs to viewer
                              ↓
            If job completed → Reload page to show final state
```

## Security Architecture

### Authentication & Authorization

```
┌──────────────┐
│   Browser    │
└──────┬───────┘
       │
       │ HTTP Basic Auth (username:password)
       │
       ▼
┌──────────────────────┐
│  FastAPI Middleware  │
│  verify_credentials  │
└──────┬───────────────┘
       │
       │ All authenticated
       │
       ▼
┌──────────────────────┐
│   Route Handlers     │
│  (Protected Routes)  │
└──────────────────────┘
```

### CSRF Protection

```
GET /jobs/new
    ↓
Generate CSRF Token (signed)
    ↓
Include in form as hidden field
    ↓
POST /jobs (with csrf_token)
    ↓
Verify token signature + age
    ↓
Process request if valid
```

### AWS Credential Flow

```
Job Config (assume_role_arn) → Worker Task
                                    ↓
                        STS AssumeRole API Call
                                    ↓
                    Temporary Credentials (1 hour)
                    - Access Key
                    - Secret Key
                    - Session Token
                                    ↓
                    Set as ENV for Terraform process
                                    ↓
                    Terraform runs with assumed credentials
                                    ↓
                    Credentials expire (NOT stored in DB)
```

### Isolation & Sandboxing

- **Terraform Isolation**: Each job gets isolated workspace in `jobs_workdir/{job_id}/`
- **No Arbitrary Modules**: Only checked-in Terraform code is used
- **Variable Whitelisting**: Only predefined tfvars.json variables accepted
- **Command Injection Prevention**: All inputs validated with Pydantic schemas
- **Volume Restrictions**: Host volumes limited to `/opt/app/*` only

## Database Schema

```
┌─────────────────────┐
│        jobs         │
├─────────────────────┤
│ id (PK)             │
│ job_name            │
│ status              │
│ aws_region          │
│ aws_auth_method     │
│ assume_role_arn     │
│ instance_type       │
│ dockerhub_images    │◄──────┐ JSON Array
│ users_data          │◄──────┤ JSON Array
│ instance_id         │       │
│ public_ip           │       │
│ terraform_outputs   │◄──────┘ JSON Object
│ requester_email     │
│ created_at          │
│ ...                 │
└────┬────────────────┘
     │
     │ 1:N
     │
┌────▼────────────────┐
│     job_logs        │
├─────────────────────┤
│ id (PK)             │
│ job_id (FK)         │
│ timestamp           │
│ level               │
│ message             │
│ source              │
└─────────────────────┘

┌─────────────────────┐
│     job_files       │
├─────────────────────┤
│ id (PK)             │
│ job_id (FK)         │
│ filename            │
│ file_path           │
│ file_size           │
│ uploaded_at         │
└─────────────────────┘
```

## Deployment Architecture

### Development

```
localhost:8000  →  FastAPI (uvicorn)
localhost:6379  →  Redis (Docker)
Background      →  Celery Worker
Local FS        →  SQLite database
```

### Production (Recommended)

```
┌─────────────────────────────────────────────────────────┐
│                    AWS Account (Control Plane)          │
│                                                          │
│  ┌────────────┐     ┌────────────┐    ┌─────────────┐  │
│  │    ALB     │────▶│   ECS/EKS  │───▶│  RDS        │  │
│  │  (HTTPS)   │     │  FastAPI   │    │  PostgreSQL │  │
│  └────────────┘     │  Container │    └─────────────┘  │
│                     └────────────┘                      │
│                                                          │
│  ┌────────────┐     ┌────────────┐                      │
│  │ ElastiCache│────▶│   ECS/EKS  │                      │
│  │   Redis    │     │   Celery   │                      │
│  └────────────┘     │   Worker   │                      │
│                     └────────────┘                      │
│                           │                              │
│                           │ AssumeRole                   │
└───────────────────────────┼──────────────────────────────┘
                            │
                            ▼
         ┌─────────────────────────────────────────┐
         │   Target AWS Accounts (Workloads)       │
         │                                          │
         │   ┌────────────────┐                    │
         │   │  EC2 + Docker  │                    │
         │   │  (Provisioned) │                    │
         │   └────────────────┘                    │
         └─────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Why SQLite for v1?
- **Simplicity**: No separate DB server needed
- **File-based**: Easy backups and portability
- **Sufficient**: Low-moderate traffic workload
- **Migration Path**: Easy to switch to PostgreSQL later

### 2. Why Celery + Redis?
- **Proven**: Industry-standard async task queue
- **Persistence**: Tasks survive restarts
- **Monitoring**: Flower and other tools available
- **Scalability**: Can add more workers horizontally

### 3. Why Server-Side Templates vs. SPA?
- **Simplicity**: Less complexity, no build step
- **Security**: CSRF easier to implement
- **SEO**: Better for internal tools
- **Fast Development**: Quicker to iterate

### 4. Why AssumeRole over Access Keys?
- **Security**: Short-lived credentials
- **Audit**: CloudTrail shows which role was used
- **Least Privilege**: Role can have minimal permissions
- **External ID**: Additional security layer

### 5. Why Isolated Terraform Workspaces?
- **Safety**: Prevents cross-job interference
- **Cleanup**: Easy to remove per-job artifacts
- **Debugging**: Each job has independent state
- **Security**: No shared state file access

## Scalability Considerations

### Current Limitations (v1)
- SQLite limits concurrent writes
- Single-process FastAPI limits throughput
- Local file storage not HA
- No job prioritization

### Scaling Path
1. **Phase 1** (Current): Single server, SQLite, local Redis
2. **Phase 2**: PostgreSQL + managed Redis (ElastiCache)
3. **Phase 3**: Multiple FastAPI instances behind ALB
4. **Phase 4**: Multiple Celery workers, S3 for files
5. **Phase 5**: Kubernetes, auto-scaling, multi-region

## Security Hardening Checklist

- [x] CSRF protection on state-changing operations
- [x] HTTP Basic Auth (v1)
- [x] No long-lived credential storage
- [x] AssumeRole with external ID support
- [x] Input validation on all fields
- [x] Region/instance type allowlists
- [x] Volume path restrictions
- [x] Terraform workspace isolation
- [x] IMDSv2 enforced
- [x] EBS encryption enabled
- [ ] HTTPS/TLS (production requirement)
- [ ] OIDC/SAML authentication
- [ ] Rate limiting per user
- [ ] Audit logging to CloudWatch
- [ ] Secrets Manager integration
- [ ] Network policies (if K8s)
- [ ] Container image scanning
- [ ] Vulnerability scanning

## Monitoring & Observability

### Recommended Metrics
- Job success/failure rate
- Job duration (p50, p95, p99)
- Terraform execution time
- Queue depth (Redis)
- API response times
- Database query performance

### Recommended Logs
- Application logs → CloudWatch
- Terraform execution logs → DB + CloudWatch
- Access logs → ALB logs
- Audit logs → CloudTrail

### Recommended Alerts
- Job failure rate > threshold
- Queue depth > threshold
- API errors > threshold
- Worker not processing jobs
- Disk usage > 80%

## Future Enhancements

See README.md "Next Improvements" section for detailed roadmap.
