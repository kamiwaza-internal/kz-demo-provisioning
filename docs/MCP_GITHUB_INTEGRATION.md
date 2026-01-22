# MCP GitHub Integration

## Overview

The Kamiwaza Deployment Manager now supports importing custom MCP (Model Context Protocol) tools directly from GitHub repositories. This feature allows you to:

1. **Validate** MCP tool repositories from GitHub URLs
2. **Import** validated tools to Kamiwaza's toolshed
3. **Deploy** imported tools automatically during provisioning

## Features

### 1. GitHub URL Validation

The system validates MCP tool repositories before import:
- Parses GitHub URLs (supports `/tree/branch/path` format)
- Fetches and validates `tool.json` configuration file
- Verifies required fields and structure
- Provides detailed validation logs

### 2. Automatic Import During Provisioning

Custom MCP tools can be automatically imported during Kamiwaza deployment:
1. User adds GitHub URLs during job creation
2. URLs are validated client-side
3. During provisioning, after Kamiwaza is ready:
   - Each GitHub URL is validated
   - Tool is imported to Kamiwaza's toolshed via API
   - Import status is logged

### 3. Post-Deployment Import

Tools can also be imported to existing Kamiwaza instances via API endpoints.

## Supported GitHub URL Formats

The importer supports various GitHub URL formats:

```
# Repository root
https://github.com/owner/repo

# Specific branch
https://github.com/owner/repo/tree/main

# Tool in subdirectory
https://github.com/owner/repo/tree/master/path/to/tool

# With .git suffix
https://github.com/owner/repo.git
```

## MCP Tool Structure

A valid MCP tool repository must contain at minimum:

### Required Files

**`tool.json`** - Tool configuration file with required fields:
```json
{
  "name": "my-custom-tool",
  "version": "1.0.0",
  "description": "Description of what the tool does",
  "author": "Author Name",
  "requires_config": false,
  "env_vars": []
}
```

### Example Repository Structure

```
my-mcp-tool/
├── tool.json          # Required: Tool metadata
├── main.py            # Tool entry point
├── requirements.txt   # Python dependencies
└── README.md          # Documentation
```

## Configuration

No additional configuration required. The feature uses existing Kamiwaza connection settings:

```bash
KAMIWAZA_USERNAME=admin
KAMIWAZA_PASSWORD=kamiwaza
TOOLSHED_STAGE=DEV
```

## Database Schema

A new field has been added to the `jobs` table:

```sql
ALTER TABLE jobs ADD COLUMN custom_mcp_github_urls JSON;
```

This stores an array of GitHub URLs:

```json
[
  "https://github.com/kamiwaza-ai/custom-tool-1",
  "https://github.com/kamiwaza-ai/custom-tool-2/tree/main/tools/tool-name"
]
```

## API Endpoints

### POST /api/mcp/validate-github

Validate an MCP tool repository structure.

**Request:**
```json
{
  "csrf_token": "...",
  "github_url": "https://github.com/owner/repo/tree/main/path/to/tool",
  "github_token": "optional_github_personal_access_token"
}
```

**Response (Success):**
```json
{
  "success": true,
  "tool_config": {
    "name": "tool-name",
    "version": "1.0.0",
    "description": "Tool description",
    "github_url": "https://github.com/owner/repo/tree/main/path/to/tool",
    "github_owner": "owner",
    "github_repo": "repo",
    "github_branch": "main",
    "github_path": "path/to/tool"
  },
  "validation_logs": [
    "============================================================",
    "MCP TOOL VALIDATION",
    "============================================================",
    "GitHub URL: https://github.com/owner/repo/tree/main/path/to/tool",
    "",
    "Step 1: Parsing GitHub URL...",
    "✓ Repository: owner/repo",
    "✓ Branch: main",
    "✓ Path: path/to/tool",
    "",
    "Step 2: Fetching tool.json...",
    "✓ Found tool.json (245 bytes)",
    "",
    "Step 3: Validating tool.json...",
    "✓ Tool name: tool-name",
    "✓ Version: 1.0.0",
    "✓ Description: Tool description",
    "",
    "============================================================",
    "VALIDATION COMPLETE",
    "============================================================",
    "✓ Tool 'tool-name' is valid and ready to import"
  ]
}
```

**Response (Failure):**
```json
{
  "success": false,
  "error": "Validation failed",
  "validation_logs": [
    "============================================================",
    "MCP TOOL VALIDATION",
    "============================================================",
    "GitHub URL: https://github.com/owner/repo",
    "",
    "Step 1: Parsing GitHub URL...",
    "✓ Repository: owner/repo",
    "✓ Branch: main",
    "",
    "Step 2: Fetching tool.json...",
    "✗ File not found: tool.json",
    "",
    "Note: Make sure your repository contains a tool.json file",
    "Example structure:",
    "  ├── tool.json       (required)",
    "  ├── main.py or index.js",
    "  ├── requirements.txt or package.json",
    "  └── README.md"
  ]
}
```

### POST /api/mcp/import-to-kamiwaza

Import a validated MCP tool to a Kamiwaza instance.

**Request:**
```json
{
  "csrf_token": "...",
  "github_url": "https://github.com/owner/repo/tree/main/path/to/tool",
  "github_token": "optional_github_personal_access_token",
  "job_id": 123  // Optional: import to specific job's Kamiwaza instance
}
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Successfully imported tool 'tool-name' to Kamiwaza",
  "tool_name": "tool-name",
  "validation_logs": [...]
}
```

**Response (Failure):**
```json
{
  "success": false,
  "error": "Tool validation failed",
  "validation_logs": [...]
}
```

## Usage

### During Job Creation

1. Go to "Create New Job"
2. Select "Kamiwaza Full Stack" as deployment type
3. Scroll to the "🔧 Toolshed - Pre-Install MCP Tools" section
4. Find the "📦 Import Custom MCP Tools from GitHub" subsection
5. Enter a GitHub URL for your MCP tool
6. Click "Validate & Add"
7. If validation succeeds, the tool is added to the custom MCP list
8. Submit the job

The custom MCP tools will be automatically imported during provisioning after Kamiwaza becomes ready.

### Post-Deployment Import

Use the `/api/mcp/import-to-kamiwaza` endpoint to import tools to running instances:

```bash
curl -X POST https://your-deployment-manager/api/mcp/import-to-kamiwaza \
  -H "Content-Type: application/json" \
  -d '{
    "csrf_token": "...",
    "github_url": "https://github.com/kamiwaza-ai/custom-tool",
    "job_id": 123
  }'
```

## Migration

To add the new database field to existing installations:

```bash
python3 scripts/migrate_database_mcp_github.py
```

This script safely adds the `custom_mcp_github_urls` column if it doesn't exist.

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────┐
│  Job Creation UI                                        │
│  1. User enters GitHub URL                              │
│  2. Frontend validates via /api/mcp/validate-github     │
│  3. Validated URLs stored in array                      │
│  4. Submit job with custom_mcp_github_urls              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Backend (main.py)                                      │
│  1. Parse custom_mcp_github_urls from form              │
│  2. Store in Job.custom_mcp_github_urls (JSON)          │
│  3. Queue provisioning task                             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Provisioning Worker (tasks.py)                         │
│  1. Provision EC2 + Install Kamiwaza                    │
│  2. Wait for Kamiwaza readiness                         │
│  3. Deploy apps and standard tools                      │
│  4. Import custom MCP tools from GitHub URLs            │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  MCPGitHubImporter                                      │
│  1. Parse GitHub URL                                    │
│  2. Fetch tool.json from raw.githubusercontent.com      │
│  3. Validate tool.json structure                        │
│  4. Call Kamiwaza API to import tool                    │
│  5. Report success/failure                              │
└─────────────────────────────────────────────────────────┘
```

### Component Responsibilities

1. **MCPGitHubImporter (`mcp_github_importer.py`)**
   - Parses GitHub URLs
   - Fetches files from GitHub
   - Validates tool.json structure
   - Imports to Kamiwaza via API

2. **API Endpoints (`main.py`)**
   - `/api/mcp/validate-github` - Validates MCP repos
   - `/api/mcp/import-to-kamiwaza` - Imports validated tools

3. **Provisioning Pipeline (`worker/tasks.py`)**
   - Triggers automatic import during provisioning
   - Logs import progress and errors

4. **UI (`job_new.html`)**
   - GitHub URL input and validation
   - Real-time validation feedback
   - Custom MCP tools list management

## Kamiwaza API Integration

The importer expects Kamiwaza to provide this endpoint:

```
POST /api/tool/import-from-github
Authorization: Bearer {token}
Content-Type: application/json

{
  "name": "tool-name",
  "github_url": "https://github.com/owner/repo",
  "branch": "main",
  "path": "path/to/tool",
  "metadata": {
    "name": "tool-name",
    "version": "1.0.0",
    "description": "...",
    ...
  }
}
```

**Note:** If this endpoint doesn't exist in your Kamiwaza version, the import will fail with an error message. The tool validation will still work, but actual import to Kamiwaza requires this API endpoint.

## Troubleshooting

### Validation Fails - File Not Found

- **Issue**: `tool.json` not found in repository
- **Solution**: Ensure `tool.json` exists in the repository root or specified path
- **Check**: The GitHub URL points to the correct branch and path

### Validation Fails - Invalid JSON

- **Issue**: `tool.json` contains invalid JSON
- **Solution**: Validate your JSON using a JSON validator
- **Required Fields**: Ensure at least `name` field is present

### Import Fails - Authentication Error

- **Issue**: Cannot authenticate with Kamiwaza
- **Solution**: Verify `KAMIWAZA_USERNAME` and `KAMIWAZA_PASSWORD` settings
- **Check**: Kamiwaza instance is accessible at the configured URL

### Import Fails - API Error

- **Issue**: Kamiwaza API returns error
- **Solution**: Check if `/api/tool/import-from-github` endpoint exists in your Kamiwaza version
- **Workaround**: Update Kamiwaza to a version that supports GitHub tool import

### Private Repository Access

- **Issue**: Cannot access private GitHub repositories
- **Solution**: Provide a GitHub personal access token with `repo` scope
- **Usage**: Pass `github_token` parameter in API requests

## Security Considerations

1. **GitHub Token Storage**: GitHub tokens are not stored in the database, only used during validation/import
2. **URL Validation**: GitHub URLs are parsed and validated before fetching content
3. **CSRF Protection**: All API endpoints require valid CSRF tokens
4. **Kamiwaza Authentication**: Tool import requires valid Kamiwaza credentials
5. **File Access**: Only `tool.json` is fetched for validation; other files are not accessed

## Future Enhancements

Potential improvements:

1. **Webhook Integration**: Auto-import on GitHub push events
2. **Version Management**: Track and update tool versions
3. **Bulk Import**: Import multiple tools from a single repository
4. **Private Repo Support UI**: Add GitHub token input in UI
5. **Tool Testing**: Validate tool functionality before import
6. **Import Queue**: Background job system for large import operations
7. **Tool Registry**: Local cache of imported tools with metadata

## Related Files

- `/app/mcp_github_importer.py` - MCP GitHub import and validation logic
- `/app/main.py` - API endpoints (lines 1655-1831)
- `/app/models.py` - Database model with custom_mcp_github_urls field
- `/worker/tasks.py` - Provisioning integration (lines 793-849)
- `/app/templates/job_new.html` - UI for GitHub MCP import
- `/scripts/migrate_database_mcp_github.py` - Database migration script
