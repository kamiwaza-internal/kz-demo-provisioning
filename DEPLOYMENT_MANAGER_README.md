# Deployment Manager

A web application for provisioning Kamiwaza users and deploying Kaizen instances through CSV upload.

## Features

- **CSV Upload UI**: Simple web interface for uploading user lists
- **Client-side Validation**: Real-time CSV validation with helpful error messages
- **Real-time Logging**: Live terminal output showing provisioning progress
- **Automatic Kaizen Deployment**: Checks and deploys Kaizen template if needed for analyst users
- **Background Processing**: Uses Celery for long-running provisioning jobs
- **App Garden Ready**: Packaged as a Kamiwaza App Garden container

## How It Works

1. User uploads a CSV file with `email` and `role` columns
2. Frontend validates the CSV format and displays preview
3. Backend creates a provisioning job and validates CSV server-side
4. Job is queued for execution in Celery worker
5. Worker calls the `provision_users.py` script from Kamiwaza
6. Real-time logs are streamed to the web UI
7. Users are created in Kamiwaza/Keycloak and Kaizen instances are deployed

## CSV Format

The CSV must have two columns:

```csv
email,role
admin@kamiwaza.ai,operator
steffen@kamiwaza.ai,analyst
john@kamiwaza.ai,analyst
```

### Valid Roles

- **operator**: Gets full Kamiwaza platform admin access (all roles) + personal Kaizen instance
- **analyst**: Gets Keycloak SSO access with viewer/user roles + personal Kaizen instance

## Usage

### Accessing the UI

Navigate to: `http://localhost:8000/deployment-manager`

### Steps

1. Click "Choose File" and select your CSV
2. Review the CSV preview and validation status
3. Click "Start Provisioning"
4. Monitor the real-time logs as users are provisioned
5. Once complete, users can access their Kaizen instances at the URLs shown

### What Gets Created

For each user in the CSV:

- **Operator**:
  - Created in Kamiwaza local store + Keycloak
  - Assigned roles: `admin`, `developer`, `analyst`, `viewer`, `user`
  - Personal Kaizen instance deployed (e.g., "admin kaizen")
  - Demo Agent pre-configured with Anthropic API key

- **Analyst**:
  - Created in Keycloak only (SSO)
  - Assigned roles: `viewer`, `user`
  - Personal Kaizen instance deployed (e.g., "steffen kaizen")
  - Demo Agent pre-configured with Anthropic API key

### Kaizen Template

The provisioning script automatically creates a shared "Kaizen" template in the App Garden on first run. This template is used for all user deployments.

## API Endpoints

### Web UI Routes

- `GET /deployment-manager` - CSV upload form
- `POST /deployment-manager/provision` - Create provisioning job
- `GET /deployment-manager/{job_id}` - View provisioning progress
- `POST /deployment-manager/{job_id}/run` - Start provisioning execution

### API Routes

- `GET /api/deployment-manager/{job_id}/logs` - Get job logs (for live polling)

## Configuration

### Environment Variables

Set these in `.env` or pass to Docker:

```bash
# Kamiwaza Connection
KAMIWAZA_URL=https://localhost
KAMIWAZA_USERNAME=admin
KAMIWAZA_PASSWORD=kamiwaza
KAMIWAZA_DB_PATH=/opt/kamiwaza/db-lite/kamiwaza.db

# Provisioning Script Paths
KAMIWAZA_PROVISION_SCRIPT=/Users/steffenmerten/Code/kamiwaza/scripts/provision_users.py
KAIZEN_SOURCE=/Users/steffenmerten/Code/kaizen-v3/apps/kaizenv3

# User Credentials
DEFAULT_USER_PASSWORD=kamiwaza

# API Keys
ANTHROPIC_API_KEY=sk-ant-...
N2YO_API_KEY=...
DATALASTIC_API_KEY=...
FLIGHTRADAR24_API_KEY=...

# Database
DATABASE_URL=sqlite:///./app.db

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0
```

## Running Locally

### Prerequisites

1. Kamiwaza running at https://localhost
2. Keycloak container running
3. Redis running
4. Python 3.9+

### Start Services

```bash
# Terminal 1 - Redis
redis-server

# Terminal 2 - Web Server
make run

# Terminal 3 - Celery Worker
make worker
```

### Access

- Web UI: http://localhost:8000
- Deployment Manager: http://localhost:8000/deployment-manager

## Running as App Garden Container

### Build Image

```bash
docker build -t kamiwazaai/deployment-manager:latest .
```

### Deploy to App Garden

1. Ensure `kamiwaza.json` and `docker-compose.appgarden.yml` are present
2. Deploy via App Garden UI or CLI
3. Configure environment variables in App Garden
4. Access at the deployed URL

### Docker Compose

```bash
docker-compose -f docker-compose.appgarden.yml up -d
```

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
                    │provision_users│
                    │   .py script  │
                    └──────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  Kamiwaza    │
                    │  + Keycloak  │
                    │  + Kaizen    │
                    └──────────────┘
```

## Security Considerations

- CSV files are validated before processing
- CSRF protection on all state-changing operations
- Credentials passed via environment variables (not stored in DB)
- Background job isolation via Celery
- Access controlled through existing authentication

## Troubleshooting

### CSV Validation Errors

- Ensure CSV has `email` and `role` columns (case-insensitive)
- Valid roles are `operator` or `analyst` only
- Check for empty rows or malformed email addresses

### Provisioning Fails

- Check Kamiwaza is accessible: `curl -k https://localhost/health`
- Verify Keycloak container is running: `docker ps | grep keycloak`
- Check Celery worker logs: `tail -f celery_worker.log`
- Review provisioning logs in the UI

### Cannot Access Deployed Kaizen

- Wait 2-3 minutes for container to fully start
- Check deployment status in App Garden
- Verify user can authenticate with Keycloak
- Check Kamiwaza logs for errors

## Development

### Adding Features

1. Routes: Add to `app/main.py`
2. Templates: Add to `app/templates/`
3. Provisioner logic: Modify `app/kamiwaza_provisioner.py`
4. Worker tasks: Modify `worker/tasks.py`

### Testing

```bash
# Run tests
make test

# Lint code
make lint
```

## License

Proprietary - Internal Use Only

## Support

For issues and questions, contact: devops@kamiwaza.ai
