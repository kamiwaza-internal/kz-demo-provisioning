#!/bin/bash
#
# Delete Kamiwaza AMI
#
# This script deletes a Kamiwaza AMI and its associated snapshots.
# Use this when you need to remove an incorrect AMI (e.g., lite mode instead of full mode)
# so that a new correct AMI can be created.
#
# Usage:
#   ./delete_kamiwaza_ami.sh --ami-id ami-xxxxx
#   ./delete_kamiwaza_ami.sh --version v0.9.2 --region us-east-1
#

set -euo pipefail

# Default values
AMI_ID=""
VERSION=""
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
DRY_RUN="false"
FORCE="false"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $*"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $*" >&2
}

info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

print_usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Delete a Kamiwaza AMI and its associated snapshots.

OPTIONS:
    --ami-id ID             AMI ID to delete (e.g., ami-0123456789abcdef0)
    --version VERSION       Delete AMI for specific Kamiwaza version (e.g., v0.9.2)
    --region REGION         AWS region (default: $REGION)
    --force                 Skip confirmation prompt
    --dry-run              Show what would be deleted without deleting
    --help                 Show this help message

EXAMPLES:
    # Delete specific AMI by ID
    ./delete_kamiwaza_ami.sh --ami-id ami-0123456789abcdef0

    # Delete AMI by version (finds and deletes)
    ./delete_kamiwaza_ami.sh --version v0.9.2

    # Dry run to see what would be deleted
    ./delete_kamiwaza_ami.sh --version v0.9.2 --dry-run

    # Force delete without confirmation
    ./delete_kamiwaza_ami.sh --ami-id ami-xxx --force

NOTES:
    - This will delete BOTH the AMI and its associated EBS snapshots
    - After deletion, a new AMI can be automatically created on next deployment
    - Use this when you need to replace an incorrect AMI (e.g., lite mode → full mode)

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --ami-id)
            AMI_ID="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        --force)
            FORCE="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --help)
            print_usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Validate inputs
if [[ -z "$AMI_ID" && -z "$VERSION" ]]; then
    error "Either --ami-id or --version must be provided"
    print_usage
    exit 1
fi

log "=========================================="
log "Kamiwaza AMI Deletion Tool"
log "=========================================="
log "Region: $REGION"

# If version provided, find the AMI ID
if [[ -n "$VERSION" ]]; then
    log "Looking up AMI for version: $VERSION"

    # Normalize version
    if [[ "$VERSION" == "release/"* ]]; then
        VERSION="v${VERSION#release/}"
    elif [[ ! "$VERSION" == "v"* ]]; then
        VERSION="v${VERSION}"
    fi

    AMI_ID=$(aws ec2 describe-images \
        --region "$REGION" \
        --owners self \
        --filters \
            "Name=tag:KamiwazaVersion,Values=$VERSION" \
            "Name=tag:ManagedBy,Values=KamiwazaDeploymentManager" \
        --query 'Images[0].ImageId' \
        --output text 2>/dev/null || echo "")

    if [[ -z "$AMI_ID" || "$AMI_ID" == "None" ]]; then
        error "No AMI found for version $VERSION in region $REGION"
        exit 1
    fi

    log "Found AMI: $AMI_ID"
fi

# Get AMI details
log "Retrieving AMI details..."

AMI_INFO=$(aws ec2 describe-images \
    --image-ids "$AMI_ID" \
    --region "$REGION" \
    --output json 2>/dev/null || echo "")

if [[ -z "$AMI_INFO" || "$AMI_INFO" == "null" ]]; then
    error "AMI $AMI_ID not found in region $REGION"
    exit 1
fi

AMI_NAME=$(echo "$AMI_INFO" | jq -r '.Images[0].Name // "Unknown"')
AMI_DESC=$(echo "$AMI_INFO" | jq -r '.Images[0].Description // "No description"')
AMI_STATE=$(echo "$AMI_INFO" | jq -r '.Images[0].State // "unknown"')
CREATED_DATE=$(echo "$AMI_INFO" | jq -r '.Images[0].CreationDate // "Unknown"')

# Get associated snapshots
SNAPSHOTS=$(echo "$AMI_INFO" | jq -r '.Images[0].BlockDeviceMappings[].Ebs.SnapshotId // empty')
SNAPSHOT_COUNT=$(echo "$SNAPSHOTS" | grep -c "snap-" || echo "0")

# Display AMI information
log ""
log "AMI Details:"
info "  AMI ID:       $AMI_ID"
info "  Name:         $AMI_NAME"
info "  Description:  $AMI_DESC"
info "  State:        $AMI_STATE"
info "  Created:      $CREATED_DATE"
info "  Snapshots:    $SNAPSHOT_COUNT"

# Get tags
TAGS=$(echo "$AMI_INFO" | jq -r '.Images[0].Tags[]? | "\(.Key)=\(.Value)"' || echo "")
if [[ -n "$TAGS" ]]; then
    log ""
    log "Tags:"
    echo "$TAGS" | while read -r tag; do
        info "  $tag"
    done
fi

log ""

# Check if AMI is managed by us
MANAGED_BY=$(echo "$AMI_INFO" | jq -r '.Images[0].Tags[]? | select(.Key=="ManagedBy") | .Value' || echo "")
if [[ "$MANAGED_BY" != "KamiwazaDeploymentManager" ]]; then
    warn "This AMI is not tagged as managed by KamiwazaDeploymentManager"
    warn "Are you sure you want to delete it?"
fi

# Dry run mode
if [[ "$DRY_RUN" == "true" ]]; then
    info ""
    info "DRY RUN MODE - Would delete:"
    info "  AMI: $AMI_ID"
    if [[ $SNAPSHOT_COUNT -gt 0 ]]; then
        info "  Snapshots:"
        echo "$SNAPSHOTS" | while read -r snap; do
            if [[ -n "$snap" ]]; then
                info "    - $snap"
            fi
        done
    fi
    log ""
    info "No changes made (dry run)"
    exit 0
fi

# Confirmation
if [[ "$FORCE" != "true" ]]; then
    warn "This will permanently delete:"
    warn "  - AMI: $AMI_ID"
    warn "  - $SNAPSHOT_COUNT associated snapshot(s)"
    warn ""
    warn "After deletion, the system can create a new AMI on the next deployment."
    echo ""
    read -p "Are you sure you want to delete this AMI? (type 'yes' to confirm): " -r CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        log "Deletion cancelled"
        exit 0
    fi
fi

# Delete AMI
log ""
log "Deleting AMI $AMI_ID..."

aws ec2 deregister-image \
    --image-id "$AMI_ID" \
    --region "$REGION"

if [[ $? -eq 0 ]]; then
    log "✓ AMI deregistered successfully"
else
    error "Failed to deregister AMI"
    exit 1
fi

# Delete snapshots
if [[ $SNAPSHOT_COUNT -gt 0 ]]; then
    log "Deleting $SNAPSHOT_COUNT snapshot(s)..."

    echo "$SNAPSHOTS" | while read -r snap_id; do
        if [[ -n "$snap_id" && "$snap_id" != "null" ]]; then
            log "  Deleting snapshot: $snap_id"
            aws ec2 delete-snapshot \
                --snapshot-id "$snap_id" \
                --region "$REGION" 2>&1 | grep -v "InvalidSnapshot.NotFound" || true

            if [[ $? -eq 0 ]]; then
                log "  ✓ Snapshot deleted: $snap_id"
            else
                warn "  Failed to delete snapshot: $snap_id (may already be deleted)"
            fi
        fi
    done

    log "✓ Snapshots deleted"
fi

# Success
log ""
log "=========================================="
log "✓ AMI Deletion Complete"
log "=========================================="
log ""
log "Summary:"
info "  Deleted AMI:       $AMI_ID"
info "  Deleted Snapshots: $SNAPSHOT_COUNT"
log ""
log "Next Steps:"
log "  1. The next Kamiwaza deployment will automatically create a new AMI"
log "  2. Make sure the new deployment uses the correct mode (full/lite)"
log "  3. Monitor the job logs for AMI creation messages"
log ""

exit 0
