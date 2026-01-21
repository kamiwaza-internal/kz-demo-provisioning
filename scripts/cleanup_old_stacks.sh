#!/bin/bash
# Cleanup script for old CloudFormation stacks
# This frees up VPC and Internet Gateway limits

set -e

REGION="us-east-1"

echo "=================================================="
echo "CloudFormation Stack Cleanup"
echo "=================================================="
echo ""

# Function to assume role
assume_role() {
    local ROLE_ARN="arn:aws:iam::916994818137:role/KamiwazaProvisionerRole"
    local SESSION_NAME="cleanup-session"

    echo "Assuming role: $ROLE_ARN"

    # Get temporary credentials
    CREDS=$(aws sts assume-role \
        --role-arn "$ROLE_ARN" \
        --role-session-name "$SESSION_NAME" \
        --duration-seconds 3600 \
        --output json)

    export AWS_ACCESS_KEY_ID=$(echo $CREDS | jq -r '.Credentials.AccessKeyId')
    export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | jq -r '.Credentials.SecretAccessKey')
    export AWS_SESSION_TOKEN=$(echo $CREDS | jq -r '.Credentials.SessionToken')

    echo "✓ Assumed role successfully"
    echo ""
}

# Assume the role
assume_role

# List all kamiwaza-job stacks
echo "Listing all kamiwaza-job CloudFormation stacks..."
echo ""

aws cloudformation list-stacks \
    --region $REGION \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --query 'StackSummaries[?contains(StackName, `kamiwaza-job`)].{Name:StackName,Status:StackStatus,Created:CreationTime}' \
    --output table

echo ""
echo "=================================================="
echo "Select stacks to delete:"
echo "=================================================="
echo ""
echo "Recommended: Keep only the most recent deployment (test4)"
echo ""
echo "Delete kamiwaza-job-2 (test2)? [y/N]"
read -r DELETE_JOB2

echo "Delete kamiwaza-job-3 (test3)? [y/N]"
read -r DELETE_JOB3

echo ""
echo "=================================================="
echo "Deleting selected stacks..."
echo "=================================================="

# Delete job-2 if requested
if [[ "$DELETE_JOB2" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Deleting kamiwaza-job-2..."
    aws cloudformation delete-stack --region $REGION --stack-name kamiwaza-job-2
    echo "✓ Deletion initiated for kamiwaza-job-2"
fi

# Delete job-3 if requested
if [[ "$DELETE_JOB3" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Deleting kamiwaza-job-3..."
    aws cloudformation delete-stack --region $REGION --stack-name kamiwaza-job-3
    echo "✓ Deletion initiated for kamiwaza-job-3"
fi

# Wait for deletions to complete
if [[ "$DELETE_JOB2" =~ ^[Yy]$ ]] || [[ "$DELETE_JOB3" =~ ^[Yy]$ ]]; then
    echo ""
    echo "=================================================="
    echo "Waiting for stack deletions to complete..."
    echo "This may take 2-5 minutes..."
    echo "=================================================="

    if [[ "$DELETE_JOB2" =~ ^[Yy]$ ]]; then
        echo ""
        echo "Waiting for kamiwaza-job-2..."
        aws cloudformation wait stack-delete-complete --region $REGION --stack-name kamiwaza-job-2 2>/dev/null && \
            echo "✓ kamiwaza-job-2 deleted successfully" || \
            echo "⚠ kamiwaza-job-2 may already be deleted"
    fi

    if [[ "$DELETE_JOB3" =~ ^[Yy]$ ]]; then
        echo ""
        echo "Waiting for kamiwaza-job-3..."
        aws cloudformation wait stack-delete-complete --region $REGION --stack-name kamiwaza-job-3 2>/dev/null && \
            echo "✓ kamiwaza-job-3 deleted successfully" || \
            echo "⚠ kamiwaza-job-3 may already be deleted"
    fi

    echo ""
    echo "=================================================="
    echo "✓ Cleanup complete!"
    echo "=================================================="
    echo ""
    echo "VPCs and Internet Gateways have been freed."
    echo "You can now create new deployments."
else
    echo ""
    echo "No stacks selected for deletion."
fi
