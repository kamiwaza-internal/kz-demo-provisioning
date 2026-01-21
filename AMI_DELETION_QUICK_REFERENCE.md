# AMI Deletion Quick Reference

## Why Delete an AMI?

You might want to delete an AMI if it was created with incorrect settings:
- ❌ **Lite mode** instead of full mode
- ❌ Wrong Kamiwaza version/branch
- ❌ Missing configuration or API keys
- ❌ Corrupted or incomplete installation

## Quick Commands

### Option 1: Delete by Version (Easiest)
```bash
# Dry run (see what would be deleted)
./scripts/delete_kamiwaza_ami.sh --version v0.9.2 --dry-run

# Actually delete
./scripts/delete_kamiwaza_ami.sh --version v0.9.2
```

### Option 2: Delete by AMI ID
```bash
./scripts/delete_kamiwaza_ami.sh --ami-id ami-0123456789abcdef0
```

### Option 3: Force Delete (No Confirmation)
```bash
./scripts/delete_kamiwaza_ami.sh --version v0.9.2 --force
```

## Finding AMIs

### List All Kamiwaza AMIs
```bash
aws ec2 describe-images \
  --region us-east-1 \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'Images[*].[ImageId,Name,Tags[?Key==`KamiwazaVersion`].Value|[0],CreationDate]' \
  --output table
```

### Find AMI for Specific Version
```bash
aws ec2 describe-images \
  --region us-east-1 \
  --filters "Name=tag:KamiwazaVersion,Values=v0.9.2" \
  --query 'Images[*].[ImageId,Name,Description,CreationDate]' \
  --output table
```

### Check AMI Details
```bash
aws ec2 describe-images \
  --image-ids ami-0123456789abcdef0 \
  --query 'Images[0].{ID:ImageId,Name:Name,State:State,Size:BlockDeviceMappings[0].Ebs.VolumeSize,Tags:Tags}'
```

## Common Scenarios

### Scenario 1: Replace Lite Mode with Full Mode

```bash
# 1. Check current AMI
aws ec2 describe-images \
  --filters "Name=tag:KamiwazaVersion,Values=v0.9.2" \
  --query 'Images[0].[ImageId,Description]'

# 2. Delete it
./scripts/delete_kamiwaza_ami.sh --version v0.9.2

# 3. Deploy new instance with FULL mode
# (Use web UI, set kamiwaza_deployment_mode = "full")

# 4. Wait for automatic AMI creation (~15-20 min after deployment)
# Check job logs for AMI creation messages
```

### Scenario 2: Delete All AMIs and Start Fresh

```bash
# List all AMIs
aws ec2 describe-images \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'Images[*].ImageId' \
  --output text

# Delete each one
for ami in $(aws ec2 describe-images --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" --query 'Images[*].ImageId' --output text); do
  ./scripts/delete_kamiwaza_ami.sh --ami-id $ami --force
done
```

### Scenario 3: Keep Latest, Delete Older Versions

```bash
# List AMIs by creation date (newest first)
aws ec2 describe-images \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'sort_by(Images, &CreationDate)[] | reverse([*]).[ImageId,Name,CreationDate]' \
  --output table

# Delete specific old AMIs
./scripts/delete_kamiwaza_ami.sh --ami-id ami-old-version-1
./scripts/delete_kamiwaza_ami.sh --ami-id ami-old-version-2
```

## Troubleshooting

### "AMI not found"
```bash
# Check region
aws ec2 describe-images --image-ids ami-xxx --region us-east-1

# Try different region
aws ec2 describe-images --image-ids ami-xxx --region us-west-2
```

### "Snapshot in use"
If a snapshot can't be deleted:
```bash
# Check if snapshot is used by other AMIs
aws ec2 describe-images \
  --filters "Name=block-device-mapping.snapshot-id,Values=snap-xxx" \
  --query 'Images[*].[ImageId,Name]'
```

### "Access Denied"
Ensure your IAM role/user has permissions:
```json
{
  "Effect": "Allow",
  "Action": [
    "ec2:DeregisterImage",
    "ec2:DeleteSnapshot",
    "ec2:DescribeImages",
    "ec2:DescribeSnapshots"
  ],
  "Resource": "*"
}
```

## What Happens After Deletion?

1. ✅ AMI is removed from AWS
2. ✅ Associated EBS snapshots are deleted
3. ✅ Storage costs stop accruing
4. ✅ Next deployment will create a new AMI automatically
5. ✅ System detects no AMI exists and creates one

## Safety Tips

1. **Always use --dry-run first** to see what would be deleted
2. **Check AMI details** before deleting to confirm it's the right one
3. **Keep at least one working AMI** per version (don't delete all)
4. **Document deletions** if sharing AMIs with a team
5. **Test new AMI** before deleting old one (if unsure)

## Quick Checks

### Is there an AMI for this version?
```bash
./scripts/delete_kamiwaza_ami.sh --version v0.9.2 --dry-run
```

### How many AMIs do I have?
```bash
aws ec2 describe-images \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'length(Images)'
```

### Total storage cost?
```bash
aws ec2 describe-images \
  --filters "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
  --query 'sum(Images[*].BlockDeviceMappings[0].Ebs.VolumeSize)'

# Multiply GB by $0.05/GB-month to get monthly cost
```

## Related Documentation

- **Full guide**: `AUTOMATIC_AMI_CREATION.md`
- **Creation script**: `scripts/create_kamiwaza_ami.sh`
- **Deletion script**: `scripts/delete_kamiwaza_ami.sh`
- **AMI caching guide**: `AMI_CACHING_GUIDE.md`

---

**TL;DR**: To delete a wrong AMI: `./scripts/delete_kamiwaza_ami.sh --version v0.9.2`
