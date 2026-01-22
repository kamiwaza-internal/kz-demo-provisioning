# App Garden Integration

## Overview

The Kamiwaza Deployment Manager now supports pre-selecting applications from the App Garden to be automatically installed during Kamiwaza provisioning. This feature allows you to specify which apps should be available on your Kamiwaza instance from the moment it's deployed.

## Features

### 1. App Selection During Job Creation

When creating a new Kamiwaza deployment job, you can now:
- Browse available apps from the App Garden
- Search and filter apps by name, description, or tags
- Select multiple apps to pre-install
- View app metadata including:
  - Version information
  - Verification status
  - Risk tier
  - Description and tags

### 2. Automatic App Deployment

Selected apps are automatically deployed during the provisioning pipeline:
1. EC2 instance is created and Kamiwaza is installed
2. After Kamiwaza becomes ready, user provisioning runs (if configured)
3. Selected apps are fetched from the App Garden
4. Apps are uploaded to the Kamiwaza instance via its API
5. Apps become immediately available in the Kamiwaza UI

### 3. App Garden Publishing

The deployment manager can publish apps to the App Garden registry (when configured):
- Push custom apps managed by the deployment manager
- Update existing apps with new versions
- Centralize app distribution across multiple Kamiwaza instances

## Configuration

### App Garden URL

The App Garden URL is configured in Settings or via environment variable:

```bash
APP_GARDEN_URL=https://dev-info.kamiwaza.ai/garden/v2/apps.json
```

This is the read-only JSON endpoint that lists available apps.

### App Garden API (Optional)

To enable publishing apps to the App Garden, configure:

```bash
# API endpoint for publishing/updating apps
APP_GARDEN_API_URL=https://app-garden.kamiwaza.ai/api

# API key for authentication (if required)
APP_GARDEN_API_KEY=your-api-key-here
```

## Database Schema

A new field has been added to the `jobs` table:

```sql
ALTER TABLE jobs ADD COLUMN selected_apps JSON;
```

This stores an array of app names to be pre-installed:

```json
["App Name 1", "App Name 2", "App Name 3"]
```

## API Endpoints

### GET /api/available-apps

Fetch available apps from the App Garden for job creation.

**Response:**
```json
{
  "success": true,
  "apps": [
    {
      "name": "App Name",
      "version": "1.0.0",
      "description": "App description",
      "category": "ai",
      "tags": ["tag1", "tag2"],
      "preview_image": "https://...",
      "verified": true,
      "risk_tier": 0
    }
  ],
  "count": 3
}
```

### POST /api/app-garden/publish

Publish an app to the App Garden registry.

**Request:**
```json
{
  "csrf_token": "...",
  "app_data": {
    "name": "My Custom App",
    "version": "1.0.0",
    "docker_images": ["myregistry/myapp:1.0.0"],
    "compose_yml": "...",
    "description": "App description",
    "category": "custom",
    "tags": ["custom"],
    "risk_tier": 0,
    "verified": false
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully published app 'My Custom App' to App Garden"
}
```

## Usage

### Selecting Apps During Job Creation

1. Go to "Create New Job"
2. Select "Kamiwaza Full Stack" as deployment type
3. Scroll to the "App Garden - Pre-Install Applications" section
4. Browse available apps or use the search bar
5. Click on apps to select/deselect them
6. Selected apps appear in the "Selected Apps" section
7. Submit the job

### Publishing Apps to App Garden

Use the `/api/app-garden/publish` endpoint with your app definition:

```bash
curl -X POST https://your-deployment-manager/api/app-garden/publish \
  -H "Content-Type: application/json" \
  -d '{
    "csrf_token": "...",
    "app_data": {
      "name": "My Custom App",
      "version": "1.0.0",
      "docker_images": ["myregistry/myapp:1.0.0"],
      "compose_yml": "version: '\''3.8'\''\nservices:\n  app:\n    image: myregistry/myapp:1.0.0",
      "description": "My custom application",
      "category": "custom",
      "tags": ["productivity"],
      "risk_tier": 0
    }
  }'
```

## Migration

To add the new database field to existing installations:

```bash
python3 scripts/migrate_database_app_selection.py
```

This script safely adds the `selected_apps` column if it doesn't exist.

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────┐
│  Job Creation UI                                        │
│  1. Fetch apps from /api/available-apps                │
│  2. User selects apps                                   │
│  3. Submit job with selected_apps array                 │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Backend (main.py)                                      │
│  1. Parse selected_apps from form                       │
│  2. Store in Job.selected_apps (JSON)                   │
│  3. Queue provisioning task                             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Provisioning Worker (tasks.py)                         │
│  1. Provision EC2 + Install Kamiwaza                    │
│  2. Wait for Kamiwaza readiness                         │
│  3. Run user provisioning (if configured)               │
│  4. Call KamiwazaAppHydrator with selected_apps         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  KamiwazaAppHydrator                                    │
│  1. Fetch apps from App Garden JSON                     │
│  2. Filter to selected_apps (if provided)               │
│  3. Authenticate with Kamiwaza API                      │
│  4. Upload each app template                            │
│  5. Report success/failure                              │
└─────────────────────────────────────────────────────────┘
```

### App Garden Integration Points

The system integrates with the App Garden at multiple levels:

1. **Read-Only (Current)**: Fetches app definitions from static JSON endpoint
2. **Write (Optional)**: Publishes apps to App Garden API (requires configuration)

## Troubleshooting

### Apps Not Showing in UI

- Check that `APP_GARDEN_URL` is configured correctly
- Verify the App Garden endpoint is accessible
- Check browser console for JavaScript errors
- Ensure the App Garden JSON follows the expected format

### Apps Not Deploying

- Verify Kamiwaza is in "full" mode (lite mode doesn't support app deployment)
- Check job logs for hydration errors
- Ensure Kamiwaza API is accessible from the deployment manager
- Verify authentication credentials are correct

### Publishing Fails

- Ensure `APP_GARDEN_API_URL` is configured
- Verify `APP_GARDEN_API_KEY` is set (if required by your App Garden)
- Check that the app data includes all required fields
- Review API endpoint documentation for your App Garden instance

## Future Enhancements

Potential future improvements:

1. **Version Pinning**: Allow selecting specific app versions
2. **Dependency Resolution**: Automatically include app dependencies
3. **App Collections**: Pre-defined sets of apps for common use cases
4. **Image Pre-pulling**: Download Docker images during AMI creation for faster deployment
5. **App Health Checks**: Verify apps are running after deployment
6. **Rollback Support**: Revert to previous app versions if deployment fails

## Related Files

- `/app/models.py` - Database model for Job with selected_apps field
- `/app/schemas.py` - Pydantic schemas for API validation
- `/app/main.py` - API endpoints for app fetching and publishing
- `/app/kamiwaza_app_hydrator.py` - App deployment logic
- `/worker/tasks.py` - Celery task for provisioning with app selection
- `/app/templates/job_new.html` - UI for app selection
- `/scripts/migrate_database_app_selection.py` - Database migration script
