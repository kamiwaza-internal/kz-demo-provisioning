# Kamiwaza Full Mode Deployment

## Overview

Kamiwaza can be deployed in two modes:
- **Lite Mode** (minimal services)
- **Full Mode** (complete platform with all services)

## Environment Variable

The deployment mode is controlled by the `KAMIWAZA_LITE` environment variable:

```bash
# Full mode (default if not set)
export KAMIWAZA_LITE=false
kamiwaza start

# Lite mode (minimal services)
export KAMIWAZA_LITE=true
kamiwaza start
```

## Deployment Script Changes

### Location
`scripts/deploy_kamiwaza_full.sh` (line 114)

### Implementation
```bash
# Run kamiwaza start in FULL mode
su - $KAMIWAZA_USER -c "export KAMIWAZA_LITE=false && kamiwaza start"
```

## Differences Between Modes

### Lite Mode
- Minimal service set
- Faster startup (~5-10 minutes)
- Lower resource requirements
- Basic functionality only

### Full Mode
- Complete service stack including:
  - Authentication (Keycloak)
  - Vector database (Milvus)
  - Observability tools (optional: OTEL, Loki)
  - All backend services
- Longer startup time (~10-20 minutes)
- Higher resource requirements (recommended: t3.xlarge or larger)
- Full production feature set

## Testing

### Test Deployment (job-10)
- Deployed in **Lite Mode** (default behavior before fix)
- Successfully started but with minimal services

### Test Deployment (job-11)
- Will deploy in **Full Mode** with `KAMIWAZA_LITE=false`
- Expected to include all services

## Verification

To verify which mode is running, check the startup log:

```bash
sudo tail -f /var/log/kamiwaza-startup.log
```

Look for:
- **Lite mode**: "🔧 Environment: Lite mode"
- **Full mode**: Should show additional service initialization

Or check Docker containers:

```bash
sudo docker ps | grep kamiwaza
```

Full mode will have many more containers running (Keycloak, Milvus, etcd, etc.)

## Related Files

- `scripts/deploy_kamiwaza_full.sh` - Deployment script (sets KAMIWAZA_LITE=false)
- `/opt/kamiwaza/kamiwaza/startup/kamiwazad.sh` - Kamiwaza startup script (reads KAMIWAZA_LITE)
- `/var/log/kamiwaza-startup.log` - Startup logs showing mode

## Future Enhancements

Consider making this configurable via the provisioning UI:
- Add toggle in job configuration: "Deployment Mode: Lite / Full"
- Pass as environment variable through CDK user data
- Update documentation to explain the differences to end users
