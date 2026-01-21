# Automatic AMI Creation Feature

## Overview

The system now automatically creates Amazon Machine Images (AMIs) from successfully deployed Kamiwaza instances. This eliminates the need for manual AMI creation and ensures every validated Kamiwaza version is cached for faster future deployments.

## How It Works

### 1. Deployment Flow

```
Deploy Kamiwaza → Readiness Check → AMI Creation → Cached for Future Use
    (20 min)          (5-15 min)       (10-15 min)      (5 min deploys)
```

### 2. Automatic Trigger

After a Kamiwaza deployment completes:

1. **Readiness Check Task** (`check_kamiwaza_readiness`) runs every 30 seconds
2. When Kamiwaza login page becomes accessible:
   - Marks `kamiwaza_ready = True`
   - Triggers **AMI Creation Task** (30 second delay)
3. **AMI Creation Task** (`create_ami_after_deployment`) executes automatically

### 3. Smart AMI Detection

Before creating an AMI, the system:

1. **Checks for existing AMI** with the same Kamiwaza version
2. **Queries AWS** for AMIs tagged with:
   - `KamiwazaVersion`: e.g., "v0.9.2"
   - `ManagedBy`: "KamiwazaDeploymentManager"
   - `state`: "available"
3. **Skips creation** if AMI already exists
4. **Creates new AMI** only if version is not cached

### 4. AMI Creation Process

When creating an AMI:

1. **Reboots instance** for filesystem consistency (brief downtime ~2 min)
2. **Creates snapshot** of the EC2 instance
3. **Tags AMI** with metadata:
   - `KamiwazaVersion`: e.g., "v0.9.2"
   - `CreatedFrom`: Instance ID
   - `CreatedFromJob`: Job ID
   - `ManagedBy`: "KamiwazaDeploymentManager"
   - `AutoCreated`: "true"
4. **Waits for availability** (10-15 minutes)
5. **Updates job record** with AMI ID

## Database Schema

New fields added to `jobs` table:

```python
created_ami_id          # AMI ID that was created (if any)
ami_creation_status     # pending/creating/completed/failed/skipped
ami_created_at          # Timestamp of AMI creation
ami_creation_error      # Error message if creation failed
```

## AMI Creation Status Values

| Status | Description |
|--------|-------------|
| `null` | AMI creation not started yet |
| `pending` | Scheduled, waiting to start |
| `creating` | AMI creation in progress |
| `completed` | AMI created successfully |
| `failed` | AMI creation failed |
| `skipped` | AMI already exists for this version |

## Benefits

### 1. **Zero Manual Intervention**
- No need to remember to create AMIs
- Every successful deployment is automatically cached
- Team members always have latest AMIs available

### 2. **Smart Deduplication**
- Won't create duplicate AMIs for the same version
- Reduces storage costs
- Prevents AMI clutter

### 3. **Fast Future Deployments**
- First deployment: ~30 minutes (fresh install)
- Subsequent deployments: ~5 minutes (using cached AMI)
- 6x faster for repeated deployments!

### 4. **Automatic Version Tracking**
- AMIs tagged with Kamiwaza version
- Easy to identify which AMI to use
- Supports multiple versions simultaneously

## Monitoring AMI Creation

### Via Web UI

1. Go to job detail page
2. Check the logs for AMI creation messages:
   ```
   [ami-creation] Starting automatic AMI creation...
   [ami-creation] Checking for existing AMI for Kamiwaza v0.9.2...
   [ami-creation] No existing AMI found, creating new AMI...
   [ami-creation] Creating AMI: kamiwaza-golden-v0.9.2-20260121-180000
   [ami-creation] ✓ AMI creation initiated: ami-0123456789abcdef
   [ami-creation] Waiting for AMI to become available...
   [ami-creation] ✓ AMI is now available! Size: 10 GB
   [ami-creation] ✓ AMI Created Successfully: ami-0123456789abcdef
   ```

### Via Database

```bash
sqlite3 app.db "SELECT id, job_name, ami_creation_status, created_ami_id FROM jobs WHERE deployment_type = 'kamiwaza'"
```

### Via AWS Console

1. Go to EC2 → AMIs
2. Filter by tag: `ManagedBy = KamiwazaDeploymentManager`
3. Look for `AutoCreated = true`

## Using Cached AMIs

### Automatic Use (Future Feature)

The system will automatically use cached AMIs for matching Kamiwaza versions in future deployments.

### Manual Use (Current)

To use a cached AMI when creating a new job:

1. Find the AMI ID:
   ```bash
   aws ec2 describe-images \
     --region us-east-1 \
     --filters "Name=tag:KamiwazaVersion,Values=v0.9.2" \
               "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
     --query 'Images[0].ImageId' \
     --output text
   ```

2. Use the AMI ID when creating a new job via the web UI or API

## Troubleshooting

### AMI Creation Failed

**Check logs:**
```bash
sqlite3 app.db "SELECT ami_creation_error FROM jobs WHERE id = <job_id>"
```

**Common causes:**
- Insufficient IAM permissions (needs `ec2:CreateImage`, `ec2:CreateTags`)
- Instance in unhealthy state
- Storage quota exceeded

**Solution:**
```bash
# Manually create AMI using the script
./scripts/create_kamiwaza_ami.sh --instance-id i-xxxxx
```

### AMI Creation Stuck

**Check status:**
```bash
aws ec2 describe-images --image-ids ami-xxxxx --query 'Images[0].State'
```

**If stuck in "pending" state:**
- Wait up to 20 minutes
- Check AWS Service Health Dashboard
- Contact AWS support if issue persists

### No AMI Created for Job

**Check if skipped:**
```bash
sqlite3 app.db "SELECT ami_creation_status FROM jobs WHERE id = <job_id>"
```

**Reasons for skipped:**
- Not a Kamiwaza deployment (`deployment_type != 'kamiwaza'`)
- AMI already exists for this version
- Readiness check never completed

### Using Wrong AMI Version

**List all available AMIs:**
```bash
aws ec2 describe-images \
  --region us-east-1 \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'Images[*].[ImageId,Name,Tags[?Key==`KamiwazaVersion`].Value|[0],CreationDate]' \
  --output table
```

## Configuration

### Environment Variables

The following settings control AMI creation behavior:

```bash
# AWS Authentication (required)
AWS_AUTH_METHOD=assume_role
AWS_ASSUME_ROLE_ARN=arn:aws:iam::123456789012:role/KamiwazaProvisionerRole
AWS_EXTERNAL_ID=your-external-id
AWS_SESSION_NAME=kamiwaza-provisioner

# Or use access keys
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

### IAM Permissions Required

The IAM role/user must have:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:CreateImage",
        "ec2:CreateTags",
        "ec2:DescribeImages",
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    }
  ]
}
```

## Cost Implications

### Storage Costs

- AMI storage: ~$0.05 per GB-month (us-east-1)
- Typical Kamiwaza AMI: ~10 GB = $0.50/month
- Multiple versions: $0.50/version/month

### Savings

- **Time savings**: 25 minutes per deployment × team size
- **EC2 cost savings**: Less time running instances
- **Example**: 10 deployments/month = 250 minutes saved = ~$2-3 in EC2 costs

**Net benefit**: Pays for itself immediately with multiple deployments

## Deleting Incorrect AMIs

If an AMI was created with the wrong configuration (e.g., lite mode instead of full mode), you can delete it so a new correct one can be created:

### Using the Deletion Script (Recommended)

```bash
# Delete by AMI ID
./scripts/delete_kamiwaza_ami.sh --ami-id ami-0123456789abcdef0

# Delete by version (finds and deletes)
./scripts/delete_kamiwaza_ami.sh --version v0.9.2

# Dry run (see what would be deleted)
./scripts/delete_kamiwaza_ami.sh --version v0.9.2 --dry-run

# Force delete (no confirmation)
./scripts/delete_kamiwaza_ami.sh --ami-id ami-xxx --force
```

The script will:
1. Find the AMI (by ID or version)
2. Show AMI details and tags
3. Ask for confirmation
4. Delete the AMI
5. Delete all associated EBS snapshots
6. Display summary

### Manual Deletion

If you prefer to use AWS CLI directly:

```bash
# Find the AMI ID for a version
AMI_ID=$(aws ec2 describe-images \
  --region us-east-1 \
  --filters "Name=tag:KamiwazaVersion,Values=v0.9.2" \
            "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'Images[0].ImageId' \
  --output text)

# Get associated snapshot IDs
SNAPSHOTS=$(aws ec2 describe-images \
  --image-ids $AMI_ID \
  --query 'Images[0].BlockDeviceMappings[].Ebs.SnapshotId' \
  --output text)

# Delete the AMI
aws ec2 deregister-image --image-id $AMI_ID

# Delete the snapshots
for snap in $SNAPSHOTS; do
  aws ec2 delete-snapshot --snapshot-id $snap
done
```

### After Deletion

Once an AMI is deleted:
1. The next deployment of that version will create a new AMI
2. Make sure to deploy with the **correct configuration** (full/lite mode)
3. Check job logs to confirm new AMI creation

### Example Scenario: Replace Lite Mode AMI

```bash
# Current situation: Accidentally created lite mode AMI for v0.9.2
# Goal: Replace with full mode AMI

# Step 1: Delete the incorrect AMI
./scripts/delete_kamiwaza_ami.sh --version v0.9.2

# Step 2: Deploy Kamiwaza in FULL mode
# (via web UI or API, ensure kamiwaza_deployment_mode = "full")

# Step 3: Wait for automatic AMI creation
# Check job logs for:
# [ami-creation] Creating AMI: kamiwaza-golden-v0.9.2-...
# [ami-creation] ✓ AMI Created Successfully

# Step 4: Verify new AMI
aws ec2 describe-images \
  --filters "Name=tag:KamiwazaVersion,Values=v0.9.2" \
  --query 'Images[*].[ImageId,CreationDate,Description]' \
  --output table
```

## Cleanup

### Delete Old AMIs

To delete old AMIs (different versions you no longer need):

```bash
# List AMIs older than 30 days
aws ec2 describe-images \
  --owners self \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'Images[?CreationDate<`2025-12-01`].[ImageId,Name]' \
  --output table

# Delete specific AMI
aws ec2 deregister-image --image-id ami-xxxxx

# Delete associated snapshots
aws ec2 describe-snapshots \
  --owner-ids self \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  | jq -r '.Snapshots[] | select(.StartTime < "2025-12-01") | .SnapshotId' \
  | xargs -I {} aws ec2 delete-snapshot --snapshot-id {}
```

### Automated Cleanup (Future Feature)

We plan to add automated cleanup of AMIs older than 90 days.

## Migration

For existing installations, run the database migration:

```bash
python3 scripts/migrate_database_ami_fields.py
```

This adds the new AMI tracking columns to the `jobs` table.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Kamiwaza Deployment                       │
│                                                              │
│  1. deploy_ec2_instance()                                    │
│     └─> EC2 Instance Created                                │
│                                                              │
│  2. check_kamiwaza_readiness() [every 30s]                  │
│     └─> Polls https://<ip> for login page                   │
│     └─> kamiwaza_ready = True                               │
│                                                              │
│  3. create_ami_after_deployment() [triggered on ready]      │
│     ├─> Check if AMI exists for version                     │
│     ├─> If exists: Skip (ami_creation_status = "skipped")   │
│     └─> If not exists:                                       │
│         ├─> Create AMI (ec2:CreateImage)                    │
│         ├─> Tag with version metadata                        │
│         ├─> Wait for availability (10-15 min)               │
│         └─> Save AMI ID (ami_creation_status = "completed") │
│                                                              │
│  4. Future deployments use cached AMI                        │
│     └─> 5 minute deployments!                               │
└─────────────────────────────────────────────────────────────┘
```

## Code Locations

- **Database Model**: `app/models.py` (lines 56-60)
- **AMI Creation Task**: `worker/tasks.py` (`create_ami_after_deployment`)
- **AMI Check Helper**: `worker/tasks.py` (`check_ami_exists_for_version`)
- **Integration Point**: `worker/tasks.py` (`check_kamiwaza_readiness`, line ~768)
- **Migration Script**: `scripts/migrate_database_ami_fields.py`

## Examples

### Example 1: First Deployment (Creates AMI)

```
Job #19: Deploy Kamiwaza v0.9.2
├─ [17:00] EC2 instance created (i-abc123)
├─ [17:18] Kamiwaza ready (login accessible)
├─ [17:18] Checking for existing AMI...
├─ [17:18] No AMI found, creating...
├─ [17:19] AMI creation initiated: ami-xyz789
├─ [17:30] AMI available!
└─ [17:30] Status: completed, AMI: ami-xyz789
```

### Example 2: Second Deployment (Skips AMI)

```
Job #20: Deploy Kamiwaza v0.9.2
├─ [18:00] EC2 instance created (i-def456)
├─ [18:18] Kamiwaza ready (login accessible)
├─ [18:18] Checking for existing AMI...
├─ [18:18] Found existing AMI: ami-xyz789
└─ [18:18] Status: skipped (AMI already exists)
```

### Example 3: Different Version (Creates New AMI)

```
Job #21: Deploy Kamiwaza v0.9.3
├─ [19:00] EC2 instance created (i-ghi789)
├─ [19:18] Kamiwaza ready (login accessible)
├─ [19:18] Checking for existing AMI v0.9.3...
├─ [19:18] No AMI found, creating...
├─ [19:19] AMI creation initiated: ami-abc456
├─ [19:30] AMI available!
└─ [19:30] Status: completed, AMI: ami-abc456
```

## Future Enhancements

1. **Automatic AMI Selection**: When creating a job, automatically use cached AMI if available
2. **AMI Lifecycle Management**: Auto-delete AMIs older than 90 days
3. **Multi-Region AMI Copying**: Automatically copy AMIs to all configured regions
4. **AMI Validation**: Health checks before marking AMI as ready
5. **AMI Versioning**: Support for patch versions (e.g., v0.9.2-patch1)

## Support

For questions or issues:
1. Check the logs in the web UI
2. Review this documentation
3. Check AWS EC2 console for AMI status
4. Contact the platform team

---

**Last Updated**: January 21, 2026
**Version**: 1.0.0
