# Deployment Manager - Implementation Summary

## What Was Built

A complete web-based "Deployment Manager" application that allows administrators to provision Kamiwaza users and deploy Kaizen instances by uploading a CSV file.

## Features Implemented

### 1. Web UI with CSV Upload
- **Location**: http://localhost:8000/deployment-manager
- Clean, modern interface built on existing FastAPI app
- Client-side CSV validation with real-time feedback
- CSV preview before submission
- Validates email and role columns

### 2. CSV Validation
- **Client-side**: JavaScript validation in browser (instant feedback)
- **Server-side**: Python validation in `kamiwaza_provisioner.py`
- Required columns: `email`, `role`
- Valid roles: `operator`, `analyst`
- Helpful error messages for validation failures

### 3. Background Processing
- Uses existing Celery infrastructure
- New task: `execute_kamiwaza_provisioning` in `worker/tasks.py`
- Integrates with `provision_users.py` from Kamiwaza repo
- Streams logs in real-time to database

### 4. Real-time Log Display
- Live polling of provisioning logs
- Auto-scrolling terminal output
- Color-coded log levels (info, warning, error)
- Shows progress of user creation and Kaizen deployment

### 5. Kaizen Template Management
- Automatically checks if Kaizen template exists in App Garden
- Creates shared "Kaizen" template on first run
- Uses template for all user deployments
- Idempotent operations (safe to re-run)

### 6. App Garden Container Ready
- **Dockerfile**: Multi-stage build with Python 3.11
- **docker-compose.appgarden.yml**: Full stack with web, worker, and Redis
- **kamiwaza.json**: Metadata for App Garden integration
- Mounts Docker socket for container operations
- Configurable via environment variables

## Files Created/Modified

### New Files
1. **app/kamiwaza_provisioner.py** - Core provisioning logic
2. **app/templates/deployment_manager.html** - CSV upload UI
3. **app/templates/deployment_progress.html** - Progress monitoring UI
4. **Dockerfile** - Container image definition
5. **docker-compose.appgarden.yml** - App Garden deployment config
6. **kamiwaza.json** - App Garden metadata
7. **DEPLOYMENT_MANAGER_README.md** - Full documentation
8. **DEPLOYMENT_MANAGER_SUMMARY.md** - This file

### Modified Files
1. **app/main.py** - Added 6 new routes for Deployment Manager
2. **app/templates/base.html** - Added navigation link
3. **worker/tasks.py** - Added `execute_kamiwaza_provisioning` task

## Architecture

```
User Browser
    │
    ├─→ Upload CSV → /deployment-manager
    │                      │
    │                      ▼
    │               FastAPI validates CSV
    │                      │
    │                      ▼
    │               Creates Job in SQLite
    │                      │
    │                      ▼
    │               Redirects to /deployment-manager/{job_id}
    │
    └─→ Monitor Progress ← Polls /api/deployment-manager/{job_id}/logs
                                  │
                                  ▼
                           Job logs in real-time

Background:
    Celery Worker
        │
        ├─→ Reads CSV from uploads/
        │
        ├─→ Calls provision_users.py script
        │       │
        │       ├─→ Authenticates to Kamiwaza
        │       ├─→ Creates Kaizen template (if needed)
        │       ├─→ Creates operators (Kamiwaza + Keycloak)
        │       ├─→ Creates analysts (Keycloak only)
        │       ├─→ Deploys Kaizen instances
        │       └─→ Configures Demo Agents
        │
        └─→ Logs output to database in real-time
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/deployment-manager` | CSV upload form |
| POST | `/deployment-manager/provision` | Create provisioning job |
| GET | `/deployment-manager/{job_id}` | View job progress |
| POST | `/deployment-manager/{job_id}/run` | Start job execution |
| GET | `/api/deployment-manager/{job_id}/logs` | Get job logs (JSON) |

## How to Use

### 1. Access the UI
```bash
# Open in browser
http://localhost:8000/deployment-manager
```

### 2. Prepare CSV
```csv
email,role
admin@kamiwaza.ai,operator
analyst1@kamiwaza.ai,analyst
analyst2@kamiwaza.ai,analyst
```

### 3. Upload and Provision
1. Click "Choose File" and select CSV
2. Review validation status
3. Click "Start Provisioning"
4. Monitor real-time logs
5. Wait for completion

### 4. Access Kaizen Instances
Users can access their Kaizen instances at:
- https://localhost/runtime/apps/{deployment-id}
- Login with email prefix as username (e.g., `admin` for `admin@kamiwaza.ai`)
- Default password: `kamiwaza`

## Configuration

### Environment Variables

Set these in your shell or `.env` file:

```bash
# Kamiwaza connection
export KAMIWAZA_URL=https://localhost
export KAMIWAZA_USERNAME=admin
export KAMIWAZA_PASSWORD=kamiwaza
export KAMIWAZA_DB_PATH=/opt/kamiwaza/db-lite/kamiwaza.db

# Script paths
export KAMIWAZA_PROVISION_SCRIPT=/Users/steffenmerten/Code/kamiwaza/scripts/provision_users.py
export KAIZEN_SOURCE=/Users/steffenmerten/Code/kaizen-v3/apps/kaizenv3

# API keys
export ANTHROPIC_API_KEY=sk-ant-...
export N2YO_API_KEY=...
export DATALASTIC_API_KEY=...
export FLIGHTRADAR24_API_KEY=...

# User password
export DEFAULT_USER_PASSWORD=kamiwaza
```

## Running Locally

### Prerequisites
1. Kamiwaza running at https://localhost
2. Keycloak container running
3. Redis running
4. Python 3.9+ with venv activated

### Start Services

```bash
# Terminal 1 - Redis
redis-server

# Terminal 2 - Web Server
make run
# Or: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 3 - Celery Worker
make worker
# Or: celery -A worker.celery_app worker --loglevel=info
```

## Deploying to App Garden

### Option 1: Build and Deploy
```bash
# Build Docker image
docker build -t kamiwazaai/deployment-manager:latest .

# Push to registry (if needed)
docker push kamiwazaai/deployment-manager:latest

# Deploy via App Garden UI
# - Upload kamiwaza.json
# - Configure environment variables
# - Deploy
```

### Option 2: Docker Compose
```bash
# Local testing
docker-compose -f docker-compose.appgarden.yml up -d

# Access at
http://localhost:8000/deployment-manager
```

## Testing

### Manual Test
1. Create a test CSV:
   ```bash
   echo "email,role" > test_users.csv
   echo "test@example.com,analyst" >> test_users.csv
   ```

2. Upload via UI at http://localhost:8000/deployment-manager

3. Click "Start Provisioning"

4. Monitor logs in real-time

5. Verify user created in Kamiwaza/Keycloak

6. Access Kaizen instance

### Validation Test
Upload an invalid CSV to test validation:
```csv
email,role
no-at-sign,operator
valid@example.com,invalid_role
,analyst
```

Should show validation errors before allowing submission.

## Security Features

1. **CSRF Protection**: All POST endpoints protected
2. **CSV Validation**: Both client and server-side
3. **No Credential Storage**: Passwords passed via env vars only
4. **Job Isolation**: Each job runs in separate Celery task
5. **Docker Socket**: Properly scoped for container operations

## Troubleshooting

### Server won't start
```bash
# Check if port 8000 is in use
lsof -i:8000

# Check logs
tail -f web_server.log

# Restart
pkill -f uvicorn
make run
```

### CSV validation fails
- Ensure CSV has `email` and `role` columns
- Check for empty rows
- Verify roles are `operator` or `analyst` only
- Check email format (must contain @)

### Provisioning fails
```bash
# Check Kamiwaza is accessible
curl -k https://localhost/health

# Check Keycloak container
docker ps | grep keycloak

# Check worker logs
tail -f celery_worker.log

# Check job logs in UI
http://localhost:8000/deployment-manager/{job_id}
```

### Cannot access Kaizen instance
- Wait 2-3 minutes for container to start
- Check App Garden deployments
- Verify user can authenticate with Keycloak
- Check Kamiwaza logs

## Next Steps

### Enhancements
1. **Bulk Operations**: Support for hundreds of users
2. **Email Notifications**: Send completion emails
3. **Audit Trail**: Track who provisioned what
4. **User Management**: View/edit existing users
5. **Template Selection**: Allow choosing different Kaizen versions
6. **Rollback**: Ability to undo provisioning

### Production Readiness
1. **TLS**: Add HTTPS support
2. **Authentication**: Integrate with Kamiwaza auth
3. **Rate Limiting**: Prevent abuse
4. **Monitoring**: Add Prometheus metrics
5. **Backup**: Database backup strategy
6. **Secrets Management**: Use Vault or AWS Secrets Manager

## Support

For issues:
1. Check logs: `tail -f web_server.log celery_worker.log`
2. Review job logs in UI
3. Check DEPLOYMENT_MANAGER_README.md for details
4. Contact: devops@kamiwaza.ai

## License

Proprietary - Internal Use Only
