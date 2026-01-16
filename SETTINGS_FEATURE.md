# Settings Feature - Documentation

## Overview

Added a comprehensive Settings page to the Deployment Manager that allows users to configure all environment variables through the web UI.

## Features

### 1. Configuration Management
- **Read from .env**: Automatically loads existing values from `.env` file
- **Edit in UI**: All settings editable through web form
- **Save to .env**: Persists changes back to `.env` file
- **Live Updates**: Environment variables updated in current process

### 2. Settings Categories

#### Kamiwaza Connection
- **URL**: Base URL of Kamiwaza instance
- **Username**: Admin username for API access
- **Password**: Admin password (masked by default)
- **Database Path**: Path to SQLite database for template registration
- **Test Connection**: Button to verify credentials work

#### Script Paths
- **Provisioning Script**: Path to `provision_users.py` in Kamiwaza repo
- **Kaizen Source**: Path to kaizen-v3 source directory

#### User Credentials
- **Default Password**: Password assigned to newly created users

#### API Keys
- **Anthropic**: For Claude models in Demo Agents
- **N2YO**: Satellite tracking API key (optional)
- **Datalastic**: Vessel tracking API key (optional)
- **FlightRadar24**: Aircraft tracking API key (optional)

### 3. UI Features

#### Security
- Passwords masked by default
- "Show/Hide Passwords" toggle button
- CSRF protection on form submission
- Confirmation before leaving with unsaved changes

#### Validation
- Required fields marked with asterisk
- Helper text for each field
- Links to API key registration pages
- Test connection before saving

#### User Experience
- Clean, organized layout
- Grid layout for related fields
- Success/error messages
- Color-coded alerts (warning for optional sections)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/settings` | Display settings page |
| POST | `/settings` | Save configuration to .env |
| POST | `/api/test-kamiwaza-connection` | Test Kamiwaza credentials |

## How to Use

### 1. Access Settings
Navigate to: http://localhost:8000/settings

Or click "Settings" in the navigation menu.

### 2. Edit Configuration
1. Fill in or update any fields
2. Use "Test Connection" to verify Kamiwaza credentials
3. Click "Show Passwords" if you need to see what's entered
4. Click "Save Configuration"

### 3. Test Connection
Before saving:
1. Fill in Kamiwaza URL, Username, and Password
2. Click "Test Connection"
3. Wait for result:
   - ✓ Connected! Account: username
   - ✗ Failed: error message

### 4. Save Changes
1. Click "Save Configuration"
2. See success message: "Configuration saved successfully..."
3. Changes take effect for new provisioning jobs
4. Existing jobs use their original settings

## File Structure

### Created Files
- `app/templates/settings.html` - Settings page UI
- `SETTINGS_FEATURE.md` - This documentation

### Modified Files
- `app/main.py` - Added 3 new routes for settings
- `app/templates/base.html` - Added Settings navigation link

## Technical Details

### Environment Variable Flow

```
1. User loads /settings
   ↓
2. Server reads os.environ
   ↓
3. Displays current values in form
   ↓
4. User edits and saves
   ↓
5. Server writes to .env file
   ↓
6. Server updates os.environ
   ↓
7. New jobs use updated values
```

### .env File Format

The saved `.env` file contains:
```bash
# Kamiwaza Deployment Manager Configuration
# Generated: 2026-01-16T17:30:00

# Kamiwaza Connection
KAMIWAZA_URL=https://localhost
KAMIWAZA_USERNAME=admin
KAMIWAZA_PASSWORD=kamiwaza
KAMIWAZA_DB_PATH=/opt/kamiwaza/db-lite/kamiwaza.db

# Script Paths
KAMIWAZA_PROVISION_SCRIPT=/path/to/provision_users.py
KAIZEN_SOURCE=/path/to/kaizen-v3/apps/kaizenv3

# User Credentials
DEFAULT_USER_PASSWORD=kamiwaza

# API Keys
ANTHROPIC_API_KEY=sk-ant-...
N2YO_API_KEY=...
DATALASTIC_API_KEY=...
FLIGHTRADAR24_API_KEY=...

# Database
DATABASE_URL=sqlite:///./app.db

# Redis
REDIS_URL=redis://localhost:6379/0
```

### Test Connection Logic

```javascript
// Frontend JavaScript
async function testConnection() {
    // Get credentials from form
    const url = document.getElementById('kamiwaza_url').value;
    const username = document.getElementById('kamiwaza_username').value;
    const password = document.getElementById('kamiwaza_password').value;

    // Send test request
    const response = await fetch('/api/test-kamiwaza-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, username, password })
    });

    // Show result
    const result = await response.json();
    // Display success or error message
}
```

```python
# Backend Python
@app.post("/api/test-kamiwaza-connection")
async def test_kamiwaza_connection(request: Request):
    # Get credentials from request
    body = await request.json()

    # Try to authenticate
    auth_response = client.post(
        f"{url}/api/auth/token",
        data={"username": username, "password": password}
    )

    # Return success or error
    return JSONResponse({"success": True/False, "error": "..."})
```

## Security Considerations

1. **Password Storage**: Passwords stored in `.env` file (not encrypted)
   - File should be in `.gitignore`
   - Set file permissions: `chmod 600 .env`

2. **CSRF Protection**: All POST requests protected

3. **No Database Storage**: Credentials never stored in SQLite database

4. **Environment Variables**: Updated in current process only
   - Workers need restart to pick up changes
   - Or configure workers to re-read .env periodically

## Best Practices

### For Development
1. Keep `.env` in `.gitignore`
2. Use `.env.example` for templates
3. Test connection before saving
4. Use "Show Passwords" carefully

### For Production
1. Use secrets management (Vault, AWS Secrets Manager)
2. Set file permissions: `chmod 600 .env`
3. Rotate passwords regularly
4. Use different passwords per environment

### For Deployment
1. Mount `.env` as ConfigMap/Secret in Kubernetes
2. Or inject via environment variables
3. Don't include `.env` in Docker image
4. Use volume mounts for persistence

## Troubleshooting

### Settings Not Saving
- Check file permissions on `.env`
- Verify write access to current directory
- Check logs: `tail -f web_server.log`

### Test Connection Fails
- Verify Kamiwaza is running: `curl -k https://localhost/health`
- Check URL format (include https://)
- Verify username/password are correct
- Check network connectivity

### Changes Not Taking Effect
- Restart Celery worker: `pkill -f celery && make worker`
- Restart web server: `pkill -f uvicorn && make run`
- Or set `auto_reload=True` in uvicorn

### Default Values Not Showing
- Create `.env` file first
- Or set environment variables before starting
- Settings page shows defaults if .env doesn't exist

## Future Enhancements

### Validation
- [ ] Path validation (check files exist)
- [ ] URL format validation
- [ ] API key format validation
- [ ] Test all connections, not just Kamiwaza

### UI Improvements
- [ ] Import/export settings as JSON
- [ ] Reset to defaults button
- [ ] History of changes
- [ ] Diff view for changes

### Security
- [ ] Encrypt passwords in .env
- [ ] Integration with secrets managers
- [ ] Audit log of who changed what
- [ ] Role-based access control

### Advanced Features
- [ ] Environment profiles (dev, staging, prod)
- [ ] Bulk import from CSV
- [ ] Configuration validation before save
- [ ] Automatic backup before changes

## Examples

### First Time Setup
1. Navigate to http://localhost:8000/settings
2. Fill in Kamiwaza URL: `https://localhost`
3. Enter username: `admin`
4. Enter password: `kamiwaza`
5. Click "Test Connection" - should see ✓ Connected
6. Fill in script paths
7. Enter Anthropic API key (optional)
8. Click "Save Configuration"
9. See success message

### Updating API Keys
1. Go to Settings
2. Scroll to "API Keys" section
3. Click "Show Passwords" to see current values
4. Update Anthropic API key
5. Click "Save Configuration"
6. New provisioning jobs will use updated key

### Testing Connection
1. Enter credentials in Settings
2. Click "Test Connection"
3. Wait for result:
   - Success: "✓ Connected! Account: admin"
   - Failure: "✗ Failed: Authentication failed: HTTP 401"
4. Fix credentials if needed
5. Test again before saving

## Support

For issues with Settings:
1. Check logs: `tail -f web_server.log`
2. Verify .env file: `cat .env`
3. Test manually: `curl -k https://localhost/api/auth/token -d "username=admin&password=kamiwaza"`
4. Contact: devops@kamiwaza.ai
