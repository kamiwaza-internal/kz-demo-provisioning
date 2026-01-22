# Toolshed Sync Fix

## Problem

The Tools & Apps management page was showing "Authentication failed: HTTP 502" errors when trying to load MCP tools from deployed Kamiwaza instances.

## Root Causes Identified

### 1. Missing Toolshed Sync Call

The `/api/jobs/{job_id}/available-tools` endpoint was **not syncing the toolshed** before trying to fetch tool templates. This meant:
- No tools would be available even if authentication succeeded
- The endpoint behavior was inconsistent with `/api/available-tools` which DOES sync

**Fixed:** Added toolshed sync call before fetching templates (main.py:1516-1519)

### 2. Poor Error Handling for 502/503 Errors

HTTP 502/503 errors indicate the Kamiwaza instance is having issues (not started, restarting, internal errors), but the error message didn't explain this to users.

**Fixed:**
- Added check for `job.kamiwaza_ready` status before attempting connection
- Enhanced error messages to suggest the instance may still be starting
- Added specific error handling for connection and timeout issues

### 3. Generic Exception Messages

Network errors (connection refused, timeout, etc.) were showing generic "Authentication error" messages that didn't help diagnose the real issue.

**Fixed:**
- Added specific handling for `httpx.ConnectError` (cannot reach server)
- Added specific handling for `httpx.TimeoutException` (server not responding)
- Enhanced error messages to include response details when available

## Changes Made

### File: `app/main.py`

**Line 1500-1522:** Added readiness and IP validation
```python
# Check if Kamiwaza instance is ready
if not job.kamiwaza_ready:
    return JSONResponse({
        "success": False,
        "error": "Kamiwaza instance is not ready yet. Please wait for deployment to complete."
    }, status_code=400)

if not job.public_ip:
    return JSONResponse({
        "success": False,
        "error": "Kamiwaza instance has no public IP address"
    }, status_code=400)
```

**Line 1516-1519:** Added toolshed sync
```python
# Sync toolshed first (important!)
sync_success, sync_msg = provisioner.sync_toolshed(token)
if not sync_success:
    logger.warning(f"Toolshed sync failed for job {job_id}: {sync_msg}, will try to use cached templates")
```

**Line 1525-1530:** Enhanced error message for 502/503
```python
# Provide more helpful error message
if "502" in error_msg or "503" in error_msg:
    error_msg += ". The Kamiwaza instance may still be starting up or experiencing issues. Please try again in a few moments."
```

### File: `app/kamiwaza_tools_provisioner.py`

**Line 61-69:** Enhanced authentication error details
```python
if auth_response.status_code != 200:
    error_msg = f"Authentication failed: HTTP {auth_response.status_code}"
    try:
        # Try to get more details from response
        error_detail = auth_response.text
        if error_detail:
            error_msg += f" - {error_detail[:200]}"
    except:
        pass
    logger.error(error_msg)
    return (False, None, error_msg)
```

**Line 75-85:** Specific network error handling
```python
except httpx.ConnectError as e:
    error_msg = f"Connection failed: Cannot reach Kamiwaza at {self.kamiwaza_url}. Check if the instance is running."
    logger.error(f"{error_msg} - {str(e)}")
    return (False, None, error_msg)
except httpx.TimeoutException as e:
    error_msg = f"Connection timeout: Kamiwaza at {self.kamiwaza_url} is not responding"
    logger.error(f"{error_msg} - {str(e)}")
    return (False, None, error_msg)
```

## Expected Behavior After Fix

### Scenario 1: Instance Not Ready
**Before:** "Authentication failed: HTTP 502"
**After:** "Kamiwaza instance is not ready yet. Please wait for deployment to complete."

### Scenario 2: Instance Starting Up
**Before:** "Authentication failed: HTTP 502"
**After:** "Authentication failed: HTTP 502. The Kamiwaza instance may still be starting up or experiencing issues. Please try again in a few moments."

### Scenario 3: Instance Not Reachable
**Before:** "Authentication error: [technical details]"
**After:** "Connection failed: Cannot reach Kamiwaza at https://x.x.x.x. Check if the instance is running."

### Scenario 4: Instance Timeout
**Before:** "Authentication error: [technical details]"
**After:** "Connection timeout: Kamiwaza at https://x.x.x.x is not responding"

### Scenario 5: Successful Connection
**Before:** No tools appear (missing sync)
**After:** Tools appear after successful sync

## Testing

### To test the fix:

1. **Start the deployment manager**:
   ```bash
   uvicorn app.main:app --reload
   ```

2. **Navigate to Tools & Apps page**:
   ```
   http://localhost:8000/tools-and-apps
   ```

3. **Select a deployed Kamiwaza instance**

4. **Click the "MCP Tools" tab**

5. **Expected Results**:
   - If instance is ready: Tools load successfully after sync
   - If instance not ready: Clear error message about instance not being ready
   - If instance has issues: Helpful error message suggesting what to check

## Troubleshooting

### Still Getting HTTP 502 After Fix?

This means the Kamiwaza instance itself has issues:

1. **Check if Kamiwaza is running**:
   ```bash
   ssh ubuntu@<instance-ip>
   sudo docker ps | grep kamiwaza
   ```

2. **Check Kamiwaza logs**:
   ```bash
   sudo journalctl -u kamiwaza -n 100
   ```

3. **Check if authentication endpoint exists**:
   ```bash
   curl -k https://<instance-ip>/api/auth/token
   ```

4. **Verify the instance is marked as ready**:
   - Check the job detail page in deployment manager
   - Look for "✓ Kamiwaza is ready" status

### Toolshed Sync Fails But Templates Load?

This is expected behavior if:
- The toolshed remote is unreachable
- But Kamiwaza has cached templates from previous syncs
- The code now handles this gracefully with a warning

### No Tools Appear Even After Successful Sync?

Check:
1. The toolshed stage (DEV/STAGE/PROD) has tools registered
2. The Kamiwaza instance can reach the toolshed URL
3. Check `/api/tool/templates` endpoint directly:
   ```bash
   # Get token first
   TOKEN=$(curl -k -X POST https://<ip>/api/auth/token \
     -d "username=admin&password=kamiwaza" | jq -r .access_token)

   # Check templates
   curl -k https://<ip>/api/tool/templates \
     -H "Authorization: Bearer $TOKEN"
   ```

## Related Documentation

- [MCP GitHub Integration](./MCP_GITHUB_INTEGRATION.md) - For importing custom tools from GitHub
- [App Garden Integration](./APP_GARDEN_INTEGRATION.md) - For deploying applications
- [Kamiwaza Tools Provisioner](../app/kamiwaza_tools_provisioner.py) - Core toolshed logic

## Future Improvements

1. **Retry Logic**: Add automatic retries with exponential backoff for 502/503 errors
2. **Health Check**: Check `/health` endpoint before attempting authentication
3. **Cached Tools**: Store tool list locally to show even when sync fails
4. **Status Indicators**: Real-time status indicator for Kamiwaza instance health
5. **Debug Mode**: Verbose logging option to help diagnose connection issues
