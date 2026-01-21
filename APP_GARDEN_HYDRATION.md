# App Garden & Toolshed Hydration

## Overview

The Kamiwaza provisioning system now includes automatic hydration of app garden applications and toolshed tools. This feature runs immediately after user provisioning completes, populating the Kamiwaza instance with pre-configured applications that users can deploy.

## How It Works

### Workflow

1. **User Provisioning** (existing) - Creates users and their Kaizen instances
2. **App & Tool Hydration** (NEW) - Loads applications from the app garden into Kamiwaza
   - Fetches app definitions from the app garden JSON endpoint
   - Uploads each app template to the Kamiwaza API
   - Updates existing apps if they're already present

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Deployment Manager (User Provisioning)                 │
│                                                          │
│  1. Upload CSV with users                               │
│  2. Run user provisioning script                        │
│  3. ✓ Users created in Keycloak                         │
│  4. ✓ Kaizen instances deployed                         │
│                                                          │
│  ┌────────────────────────────────────────────┐        │
│  │  NEW: App Garden Hydration                 │        │
│  │                                             │        │
│  │  1. Fetch apps from app garden JSON        │        │
│  │  2. Authenticate with Kamiwaza              │        │
│  │  3. Upload/update each app template        │        │
│  │  4. ✓ Apps available in Kamiwaza           │        │
│  └────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. KamiwazaAppHydrator (`app/kamiwaza_app_hydrator.py`)

The main service class that handles app hydration:

```python
class KamiwazaAppHydrator:
    def fetch_app_garden_data() -> Tuple[bool, List[Dict], str]
    def authenticate() -> Tuple[bool, Optional[str], str]
    def upload_app_template(token, app_data) -> Tuple[bool, str]
    def hydrate_apps_and_tools() -> Tuple[bool, str, List[str]]
```

**Key Features:**
- Fetches app definitions from configurable JSON endpoint
- Authenticates with Kamiwaza API
- Creates or updates app templates
- Provides detailed logging for troubleshooting

### 2. Worker Task Integration (`worker/tasks.py`)

The `execute_kamiwaza_provisioning` task now includes app hydration:

```python
@celery_app.task
def execute_kamiwaza_provisioning(job_id):
    # ... existing user provisioning ...

    if success:
        # NEW: Hydrate apps and tools
        hydrator = KamiwazaAppHydrator()
        hydration_success, summary, logs = hydrator.hydrate_apps_and_tools()
```

**Error Handling:**
- User provisioning success is independent of app hydration
- If app hydration fails, the job still succeeds (users were created)
- Warnings are logged for app hydration failures

### 3. Configuration (`app/config.py`)

New configuration option added:

```python
class Settings(BaseSettings):
    # App Garden & Toolshed
    app_garden_url: str = "https://dev-info.kamiwaza.ai/garden/v2/apps.json"
```

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# App Garden & Toolshed
APP_GARDEN_URL=https://dev-info.kamiwaza.ai/garden/v2/apps.json
```

### Settings UI

The app garden URL can be configured via the Settings page:
1. Navigate to `/settings`
2. Find the "App Garden & Toolshed" section
3. Update the "App Garden URL" field
4. Click "Save Configuration"

## App Garden JSON Format

The app garden endpoint should return a JSON array of app definitions:

```json
[
  {
    "name": "Hello Web",
    "version": "2.0.12",
    "source_type": "kamiwaza",
    "visibility": "public",
    "kamiwaza_version": ">=0.8.1,<1.0.0",
    "description": "Kamiwaza Hello World web application",
    "category": "app",
    "tags": ["web", "nextjs", "demo"],
    "risk_tier": 0,
    "verified": false,
    "preview_image": "/garden/v2/images/hello-web.png",
    "env_defaults": {
      "KAMIWAZA_USE_AUTH": "true"
    },
    "compose_yml": "services:\n  web:\n    image: kamiwazaai/hello-web:2.0.12-dev\n    ...",
    "docker_images": ["kamiwazaai/hello-web:2.0.12-dev"]
  },
  {
    "name": "AI Chatbot",
    "version": "2.0.14",
    ...
  }
]
```

### Required Fields

- `name` - App name
- `version` - App version
- `description` - App description
- `compose_yml` - Docker Compose configuration
- `docker_images` - List of Docker images used

### Optional Fields

- `category` - App category (e.g., "ai", "app", "productivity")
- `tags` - List of tags
- `env_defaults` - Default environment variables
- `preview_image` - URL to preview image
- `risk_tier` - Security risk level (0-5)
- `verified` - Whether app is verified

## Usage

### Automatic Hydration

App hydration runs automatically after user provisioning:

1. Navigate to Deployment Manager (`/deployment-manager`)
2. Upload CSV file with users
3. Click "Start Provisioning"
4. Monitor the logs:
   - User provisioning logs appear first
   - App hydration logs follow with prefix "KAMIWAZA APP & TOOL HYDRATION"

### Log Output Example

```
✓ User provisioning completed successfully

Starting app and tool hydration...
============================================================
KAMIWAZA APP & TOOL HYDRATION
============================================================

Step 1: Checking Kamiwaza health...
✓ Kamiwaza is healthy

Step 2: Authenticating with Kamiwaza...
✓ Authentication successful

Step 3: Fetching app garden data...
✓ Found 3 apps in app garden

Step 4: Uploading apps to Kamiwaza...
  • Uploading app: Hello Web v2.0.12
    ✓ Created app: Hello Web
  • Uploading app: AI Chatbot v2.0.14
    ✓ Created app: AI Chatbot
  • Uploading app: Kaizen v1.3.0
    ✓ Updated app: Kaizen

============================================================
HYDRATION COMPLETE
============================================================
✓ Successfully uploaded/updated: 3 apps

✓ App and tool hydration completed successfully
```

## API Endpoints

The hydrator uses the following Kamiwaza API endpoints:

### List App Templates
```
GET /api/apps/app_templates
Authorization: Bearer <token>
```

### Create App Template
```
POST /api/apps/app_templates
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "App Name",
  "version": "1.0.0",
  ...
}
```

### Update App Template
```
PUT /api/apps/app_templates/{id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "App Name",
  "version": "1.0.1",
  ...
}
```

## Troubleshooting

### App Hydration Failed

**Symptom:** Log shows "App hydration failed" message

**Possible Causes:**
1. Kamiwaza is not accessible
2. Authentication failed (check credentials)
3. App garden URL is unreachable
4. Invalid app data format

**Solutions:**
1. Check Kamiwaza health: `curl -k https://localhost/health`
2. Verify credentials in Settings page
3. Test app garden URL: `curl https://dev-info.kamiwaza.ai/garden/v2/apps.json`
4. Review app garden JSON format

### Apps Not Appearing in Kamiwaza

**Symptom:** Hydration succeeds but apps don't appear

**Solutions:**
1. Check Kamiwaza API logs: `sudo journalctl -u kamiwaza -f`
2. Verify API endpoint is correct: `/api/apps/app_templates`
3. Check user permissions (must be admin)

### App Already Exists Error

**Symptom:** Error message "App already exists"

**Behavior:** The hydrator automatically updates existing apps instead of failing

**If Issue Persists:**
1. Check if multiple hydration jobs are running simultaneously
2. Verify app name uniqueness in app garden JSON

## Advanced Configuration

### Custom App Garden Endpoint

To use a custom app garden endpoint:

```bash
# In .env file
APP_GARDEN_URL=https://your-custom-endpoint.com/apps.json
```

### Selective App Hydration

Currently, all apps from the garden are hydrated. To implement selective hydration:

1. Modify `KamiwazaAppHydrator.hydrate_apps_and_tools()`
2. Add filtering logic based on app properties (category, tags, etc.)
3. Example:
   ```python
   # Only hydrate apps with category "ai"
   filtered_apps = [app for app in apps_data if app.get("category") == "ai"]
   ```

### Retry Logic

The hydrator doesn't automatically retry failed uploads. To add retry logic:

```python
from tenacity import retry, stop_after_attempt, wait_fixed

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def upload_app_template_with_retry(self, token, app_data):
    return self.upload_app_template(token, app_data)
```

## Future Enhancements

Potential improvements for future versions:

1. **Toolshed Tools Support** - Add hydration for toolshed tools (not just apps)
2. **Selective Hydration** - UI to select which apps to hydrate
3. **Scheduled Updates** - Periodic checks for app updates
4. **Version Management** - Track and rollback app versions
5. **Custom Repositories** - Support multiple app garden sources
6. **Validation** - Pre-validate app definitions before upload
7. **Caching** - Cache app garden data to reduce fetches

## Related Documentation

- [Deployment Manager README](DEPLOYMENT_MANAGER_README.md) - User provisioning overview
- [Settings Feature](SETTINGS_FEATURE.md) - Configuration management
- [Architecture](ARCHITECTURE.md) - Overall system architecture
