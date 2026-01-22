#!/bin/bash
#
# Create Kamiwaza Golden AMI from Running Instance
#
# This script creates a reusable AMI from a successfully deployed Kamiwaza instance.
# The AMI can then be used for faster deployments (5 minutes vs 30+ minutes).
#
# Usage:
#   ./create_kamiwaza_ami.sh --instance-id i-xxxxx [options]
#   ./create_kamiwaza_ami.sh --stack-name kamiwaza-job-17 [options]
#

set -euo pipefail

# Default values
INSTANCE_ID=""
STACK_NAME=""
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
NO_REBOOT="false"
KAMIWAZA_VERSION="v0.9.2"
AMI_NAME_PREFIX="kamiwaza-golden"
DRY_RUN="false"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

Create a golden AMI from a running Kamiwaza instance for faster future deployments.

OPTIONS:
    --instance-id ID        EC2 Instance ID (e.g., i-0123456789abcdef0)
    --stack-name NAME       CloudFormation stack name (e.g., kamiwaza-job-17)
    --region REGION         AWS region (default: $REGION)
    --no-reboot            Create AMI without rebooting (faster but less consistent)
    --version VERSION       Kamiwaza version tag (default: $KAMIWAZA_VERSION)
    --name-prefix PREFIX    AMI name prefix (default: $AMI_NAME_PREFIX)
    --dry-run              Show what would be done without creating AMI
    --help                 Show this help message

EXAMPLES:
    # Create AMI from instance ID
    ./create_kamiwaza_ami.sh --instance-id i-0123456789abcdef0

    # Create AMI from CloudFormation stack
    ./create_kamiwaza_ami.sh --stack-name kamiwaza-job-17

    # Create AMI without rebooting (faster, but potentially inconsistent)
    ./create_kamiwaza_ami.sh --instance-id i-xxx --no-reboot

    # Dry run to see what would be done
    ./create_kamiwaza_ami.sh --instance-id i-xxx --dry-run

WORKFLOW:
    1. Deploy Kamiwaza once using standard method (20-30 minutes)
    2. Wait for full installation and verify it's working
    3. Run this script to create a golden AMI (~10 minutes)
    4. Use the AMI ID in future deployments for 5-minute deploys

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --instance-id)
            INSTANCE_ID="$2"
            shift 2
            ;;
        --stack-name)
            STACK_NAME="$2"
            shift 2
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        --no-reboot)
            NO_REBOOT="true"
            shift
            ;;
        --version)
            KAMIWAZA_VERSION="$2"
            shift 2
            ;;
        --name-prefix)
            AMI_NAME_PREFIX="$2"
            shift 2
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
if [[ -z "$INSTANCE_ID" && -z "$STACK_NAME" ]]; then
    error "Either --instance-id or --stack-name must be provided"
    print_usage
    exit 1
fi

log "=========================================="
log "Kamiwaza Golden AMI Creator"
log "=========================================="
log "Region: $REGION"
log "Version: $KAMIWAZA_VERSION"

# If stack name provided, get instance ID from stack
if [[ -n "$STACK_NAME" ]]; then
    log "Looking up instance ID from stack: $STACK_NAME"

    INSTANCE_ID=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
        --output text 2>/dev/null || echo "")

    if [[ -z "$INSTANCE_ID" ]]; then
        error "Could not find InstanceId output in stack: $STACK_NAME"
        exit 1
    fi

    log "Found instance ID: $INSTANCE_ID"
fi

# Verify instance exists and is running
log "Verifying instance $INSTANCE_ID..."

INSTANCE_STATE=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text 2>/dev/null || echo "not-found")

if [[ "$INSTANCE_STATE" == "not-found" ]]; then
    error "Instance $INSTANCE_ID not found in region $REGION"
    exit 1
fi

log "Instance state: $INSTANCE_STATE"

if [[ "$INSTANCE_STATE" != "running" && "$INSTANCE_STATE" != "stopped" ]]; then
    error "Instance must be in 'running' or 'stopped' state, currently: $INSTANCE_STATE"
    exit 1
fi

# Get instance details
INSTANCE_INFO=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Reservations[0].Instances[0]')

PUBLIC_IP=$(echo "$INSTANCE_INFO" | jq -r '.PublicIpAddress // "N/A"')
INSTANCE_TYPE=$(echo "$INSTANCE_INFO" | jq -r '.InstanceType')
AVAILABILITY_ZONE=$(echo "$INSTANCE_INFO" | jq -r '.Placement.AvailabilityZone')

info "Instance Type: $INSTANCE_TYPE"
info "Availability Zone: $AVAILABILITY_ZONE"
info "Public IP: $PUBLIC_IP"

# Verify Kamiwaza is installed (if instance is running)
if [[ "$INSTANCE_STATE" == "running" ]]; then
    log "Verifying Kamiwaza installation via SSM..."

    # Check if SSM is available
    SSM_STATUS=$(aws ssm describe-instance-information \
        --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
        --region "$REGION" \
        --query 'InstanceInformationList[0].PingStatus' \
        --output text 2>/dev/null || echo "unavailable")

    if [[ "$SSM_STATUS" == "Online" ]]; then
        log "SSM is available, checking Kamiwaza installation..."

        # Check if kamiwaza command exists
        KAMIWAZA_CHECK=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION" \
            --document-name "AWS-RunShellScript" \
            --parameters 'commands=["command -v kamiwaza && echo INSTALLED || echo NOT_INSTALLED"]' \
            --query 'Command.CommandId' \
            --output text)

        sleep 5

        KAMIWAZA_RESULT=$(aws ssm get-command-invocation \
            --instance-id "$INSTANCE_ID" \
            --command-id "$KAMIWAZA_CHECK" \
            --region "$REGION" \
            --query 'StandardOutputContent' \
            --output text 2>/dev/null || echo "")

        if [[ "$KAMIWAZA_RESULT" == *"INSTALLED"* ]]; then
            log "✓ Kamiwaza is installed"
        else
            warn "Kamiwaza command not found - instance may not be fully configured"
            warn "Consider waiting for deployment to complete before creating AMI"
        fi

        # Check Docker containers
        DOCKER_CHECK=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --region "$REGION" \
            --document-name "AWS-RunShellScript" \
            --parameters 'commands=["docker ps --format \"{{.Names}}\" | grep -c kamiwaza || echo 0"]' \
            --query 'Command.CommandId' \
            --output text)

        sleep 5

        CONTAINER_COUNT=$(aws ssm get-command-invocation \
            --instance-id "$INSTANCE_ID" \
            --command-id "$DOCKER_CHECK" \
            --region "$REGION" \
            --query 'StandardOutputContent' \
            --output text 2>/dev/null | tr -d '\n' || echo "0")

        if [[ "$CONTAINER_COUNT" -gt 0 ]]; then
            log "✓ Found $CONTAINER_COUNT Kamiwaza Docker containers running"
        else
            warn "No Kamiwaza Docker containers found running"
            warn "This AMI may require Kamiwaza to be started on first boot"
        fi
    else
        warn "SSM not available - skipping Kamiwaza verification"
        warn "Ensure Kamiwaza is fully installed before creating AMI"
    fi
else
    warn "Instance is stopped - skipping Kamiwaza verification"
fi

# Generate AMI name with timestamp
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
AMI_NAME="${AMI_NAME_PREFIX}-${KAMIWAZA_VERSION}-${TIMESTAMP}"
AMI_DESCRIPTION="Kamiwaza ${KAMIWAZA_VERSION} pre-installed on RHEL 9 (created from ${INSTANCE_ID})"

log ""
log "AMI Configuration:"
info "Name: $AMI_NAME"
info "Description: $AMI_DESCRIPTION"
info "No Reboot: $NO_REBOOT"
log ""

if [[ "$DRY_RUN" == "true" ]]; then
    info "DRY RUN - Would create AMI with the following command:"
    echo ""
    echo "aws ec2 create-image \\"
    echo "  --instance-id $INSTANCE_ID \\"
    echo "  --name \"$AMI_NAME\" \\"
    echo "  --description \"$AMI_DESCRIPTION\" \\"
    if [[ "$NO_REBOOT" == "true" ]]; then
        echo "  --no-reboot \\"
    fi
    echo "  --region $REGION \\"
    echo "  --tag-specifications 'ResourceType=image,Tags=[{Key=Name,Value=$AMI_NAME},{Key=KamiwazaVersion,Value=$KAMIWAZA_VERSION},{Key=CreatedFrom,Value=$INSTANCE_ID},{Key=ManagedBy,Value=KamiwazaDeploymentManager}]'"
    echo ""
    exit 0
fi

# Confirm before creating
echo ""
warn "This will create an AMI from instance $INSTANCE_ID"
if [[ "$NO_REBOOT" == "false" ]]; then
    warn "The instance will be REBOOTED to ensure filesystem consistency"
fi
echo ""
read -p "Continue? (yes/no): " -r CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy][Ee][Ss]$ ]]; then
    log "Cancelled by user"
    exit 0
fi

# Create the AMI
log "Creating AMI (this may take 10-15 minutes)..."

NO_REBOOT_FLAG=""
if [[ "$NO_REBOOT" == "true" ]]; then
    NO_REBOOT_FLAG="--no-reboot"
fi

AMI_ID=$(aws ec2 create-image \
    --instance-id "$INSTANCE_ID" \
    --name "$AMI_NAME" \
    --description "$AMI_DESCRIPTION" \
    $NO_REBOOT_FLAG \
    --region "$REGION" \
    --tag-specifications "ResourceType=image,Tags=[{Key=Name,Value=$AMI_NAME},{Key=KamiwazaVersion,Value=$KAMIWAZA_VERSION},{Key=CreatedFrom,Value=$INSTANCE_ID},{Key=ManagedBy,Value=KamiwazaDeploymentManager},{Key=CreatedAt,Value=$TIMESTAMP}]" \
    --query 'ImageId' \
    --output text)

if [[ -z "$AMI_ID" ]]; then
    error "Failed to create AMI"
    exit 1
fi

log "✓ AMI creation initiated: $AMI_ID"
log "Waiting for AMI to become available..."

# Wait for AMI to be available
aws ec2 wait image-available \
    --image-ids "$AMI_ID" \
    --region "$REGION"

log "✓ AMI is now available!"

# Get AMI details
AMI_SIZE=$(aws ec2 describe-images \
    --image-ids "$AMI_ID" \
    --region "$REGION" \
    --query 'Images[0].BlockDeviceMappings[0].Ebs.VolumeSize' \
    --output text)

log ""
log "=========================================="
log "AMI Created Successfully!"
log "=========================================="
log ""
info "AMI ID:          $AMI_ID"
info "AMI Name:        $AMI_NAME"
info "Region:          $REGION"
info "Volume Size:     ${AMI_SIZE} GB"
info "Kamiwaza Ver:    $KAMIWAZA_VERSION"
log ""
log "Next Steps:"
log "1. Test the AMI by deploying a new instance:"
log "   python3 deploy_kamiwaza.py --name test-ami --ami-id $AMI_ID"
log ""
log "2. If successful, use this AMI for all future deployments:"
log "   - Update your deployment configuration"
log "   - Share AMI ID with your team"
log "   - Document the AMI version"
log ""
log "3. Save AMI ID to a config file:"
echo "   echo '$AMI_ID' > kamiwaza-ami-${KAMIWAZA_VERSION}.txt"
log ""
info "Deployment time with this AMI: ~5 minutes (vs 30+ minutes fresh install)"
log ""

exit 0
