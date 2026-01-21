# AMI Manager UI Guide

## Overview

The AMI Manager provides a web interface to view and delete Kamiwaza AMIs without using command-line tools.

## Access

Navigate to: **http://localhost:8000/ami-manager**

Or click "**AMI Manager**" in the top navigation bar.

## Features

### 1. View All AMIs

- Lists all Kamiwaza AMIs in a selected region
- Shows AMI details:
  - Kamiwaza version (v0.9.2, etc.)
  - AMI ID
  - Creation date
  - Size in GB
  - State (available, pending, etc.)
  - Source instance and job
  - Associated EBS snapshots

### 2. Filter by Region

Use the region dropdown to view AMIs in different AWS regions:
- us-east-1 (N. Virginia) - Default
- us-west-2 (Oregon)
- eu-west-1 (Ireland)
- And more...

### 3. Delete AMIs

Click the **🗑️ Delete** button to remove an AMI:
- Confirmation dialog shows AMI details
- Deletes both AMI and associated snapshots
- Displays success message
- Auto-refreshes the list

### 4. Auto-Created Badge

AMIs with the "AUTO" badge were created automatically by the system after successful deployments.

## How to Use

### View AMIs

1. Go to **AMI Manager** page
2. Select a region (default: us-east-1)
3. Click **🔄 Refresh** to reload
4. Browse the list of AMIs

### Delete an Incorrect AMI

**Example: Delete a lite mode AMI to create a full mode one**

1. Find the AMI for version v0.9.2
2. Click **🗑️ Delete** button
3. Review confirmation dialog:
   ```
   Version: v0.9.2
   Name: kamiwaza-golden-v0.9.2-20260121-180000
   AMI ID: ami-0123456789abcdef0
   ```
4. Click **OK** to confirm
5. Success message shows:
   ```
   ✓ AMI deleted successfully!
   AMI: kamiwaza-golden-v0.9.2-20260121-180000
   Deleted 1 snapshot(s)
   ```
6. Deploy Kamiwaza again in **full mode**
7. System automatically creates new AMI

### Check AMI Details

Each AMI card shows:
- **Version badge** - Kamiwaza version
- **AUTO badge** - Auto-created by system
- **State badge** - Available, pending, etc.
- **Name** - AMI name
- **Description** - Details about the AMI
- **AMI ID** - For use in deployments
- **Size** - Total disk space
- **Created** - Timestamp
- **From Instance** - Source EC2 instance ID
- **From Job** - Link to the job that created it
- **Snapshots** - Associated EBS snapshot IDs

## Screenshots

### Empty State
```
┌─────────────────────────────────────────┐
│ AMI Manager                             │
│ Manage cached Kamiwaza AMIs            │
├─────────────────────────────────────────┤
│ Region: [us-east-1 ▼]  [🔄 Refresh]    │
│                                         │
│ ℹ️ No AMIs found in us-east-1          │
│ AMIs will be automatically created     │
│ after successful Kamiwaza deployments. │
└─────────────────────────────────────────┘
```

### With AMIs
```
┌─────────────────────────────────────────┐
│ 2 AMI(s) found in us-east-1            │
├─────────────────────────────────────────┤
│ [v0.9.2] [AUTO] [AVAILABLE]            │
│ kamiwaza-golden-v0.9.2-20260121        │
│ Kamiwaza v0.9.2 pre-installed...      │
│ AMI ID: ami-0123456789abcdef0          │
│ Size: 10 GB                            │
│ Created: 1/21/2026, 6:00 PM           │
│ From Job: #18                          │
│                          [🗑️ Delete]   │
├─────────────────────────────────────────┤
│ [v0.9.3] [AUTO] [AVAILABLE]            │
│ kamiwaza-golden-v0.9.3-20260120        │
│ ...                                     │
└─────────────────────────────────────────┘
```

## Troubleshooting

### "AWS Credentials Not Available"

**Problem**: Red error message at the top of the page.

**Solution**:
1. Go to **Settings** page
2. Configure AWS authentication:
   - For IAM Role: Set AWS_ASSUME_ROLE_ARN
   - For Access Keys: Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
3. Click **Save Settings**
4. Return to AMI Manager

### "Error loading AMIs"

**Common causes**:
1. **Wrong region** - Check if AMIs exist in the selected region
2. **Permissions issue** - Ensure IAM role has `ec2:DescribeImages` permission
3. **Network issue** - Check AWS connectivity

**Solution**:
```bash
# Test AWS access
aws ec2 describe-images --region us-east-1 --owners self --max-items 1

# Check IAM permissions
aws iam get-user
aws sts get-caller-identity
```

### Delete Failed

**Problem**: "Error deleting AMI" message.

**Common causes**:
1. **Permissions** - Need `ec2:DeregisterImage` and `ec2:DeleteSnapshot`
2. **AMI in use** - Check if any instances are using the AMI
3. **Wrong region** - Ensure you're in the correct region

**Solution**:
```bash
# Check if AMI is in use
aws ec2 describe-instances \
  --filters "Name=image-id,Values=ami-xxx" \
  --query 'Reservations[*].Instances[*].[InstanceId,State.Name]'

# If no instances, try deleting via CLI
./scripts/delete_kamiwaza_ami.sh --ami-id ami-xxx
```

## Comparison: UI vs CLI

| Feature | UI | CLI Script |
|---------|----|-----------|
| View AMIs | ✅ Visual list | ❌ Text output |
| Filter by region | ✅ Dropdown | ✅ --region flag |
| AMI details | ✅ Cards with all info | ✅ Detailed output |
| Delete confirmation | ✅ Dialog box | ✅ Interactive prompt |
| Batch operations | ❌ One at a time | ✅ Loop support |
| Dry run | ❌ Not available | ✅ --dry-run flag |
| Force delete | ❌ Always confirms | ✅ --force flag |
| Search by version | ✅ Visual scan | ✅ --version flag |

**When to use UI**:
- Quick visual overview
- Casual browsing
- One-off deletions
- Non-technical users

**When to use CLI**:
- Scripting and automation
- Batch operations
- CI/CD pipelines
- Dry-run testing

## API Endpoints

The UI uses these API endpoints:

### List AMIs
```http
GET /api/amis?region=us-east-1
```

**Response**:
```json
{
  "success": true,
  "amis": [
    {
      "ami_id": "ami-xxx",
      "name": "kamiwaza-golden-v0.9.2-...",
      "version": "v0.9.2",
      "state": "available",
      "size_gb": 10,
      "creation_date": "2026-01-21T18:00:00Z",
      "created_from": "i-xxx",
      "created_from_job": "18",
      "auto_created": "true",
      "snapshots": ["snap-xxx"],
      "snapshot_count": 1
    }
  ],
  "region": "us-east-1",
  "count": 1
}
```

### Delete AMI
```http
POST /api/amis/{ami_id}/delete
Content-Type: application/json

{
  "csrf_token": "...",
  "region": "us-east-1"
}
```

**Response**:
```json
{
  "success": true,
  "message": "AMI ami-xxx deleted successfully",
  "ami_id": "ami-xxx",
  "ami_name": "kamiwaza-golden-v0.9.2-...",
  "deleted_snapshots": 1,
  "snapshots": ["snap-xxx"]
}
```

## Security

- **CSRF Protection**: All delete operations require valid CSRF token
- **Authentication**: Uses same AWS credentials as the application
- **Confirmation**: Always asks for confirmation before deletion
- **Audit Trail**: Logs all deletions via application logger

## Tips

1. **Keep one working AMI per version** - Don't delete all AMIs for a version
2. **Check "From Job" link** - Review the original deployment before deleting
3. **Note creation date** - Keep the newest AMI if multiple exist
4. **Document deletions** - If sharing AMIs with a team, communicate deletions
5. **Test after deletion** - Deploy once to ensure new AMI is created correctly

## Common Workflows

### Workflow 1: Replace Lite Mode with Full Mode

```
1. Go to AMI Manager
2. Find v0.9.2 AMI with "lite" in description
3. Click Delete
4. Go to "New Job" page
5. Create Kamiwaza deployment (full mode)
6. Wait 45 minutes (deploy + AMI creation)
7. Return to AMI Manager
8. Verify new full mode AMI exists
```

### Workflow 2: Clean Up Old Versions

```
1. Go to AMI Manager
2. Sort by creation date (newest first)
3. Keep most recent AMI per version
4. Delete older AMIs for same version
5. Delete AMIs for versions no longer used
6. Verify total storage cost reduction
```

### Workflow 3: Multi-Region Setup

```
1. Select us-east-1, note AMI ID
2. Use AWS console to copy AMI to us-west-2
3. Select us-west-2 in dropdown
4. Click Refresh
5. Verify copied AMI appears
6. Repeat for other regions as needed
```

## Related Documentation

- **Automatic AMI Creation**: `AUTOMATIC_AMI_CREATION.md`
- **CLI Deletion Script**: `scripts/delete_kamiwaza_ami.sh`
- **Quick Reference**: `AMI_DELETION_QUICK_REFERENCE.md`
- **Caching Guide**: `AMI_CACHING_GUIDE.md`

---

**Quick Start**: Go to http://localhost:8000/ami-manager to view and manage your AMIs!
