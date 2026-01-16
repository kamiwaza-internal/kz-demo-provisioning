#!/usr/bin/env python3
"""Deploy IAM Role for Kamiwaza via CloudFormation"""

import boto3
import os
import time
import sys
from dotenv import load_dotenv

def deploy_iam_role():
    """Deploy the CloudFormation stack for IAM role"""

    # Load environment variables
    load_dotenv('.env')

    # Get AWS credentials from environment
    aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')

    if not aws_access_key_id or not aws_secret_access_key:
        print("✗ AWS credentials not found in .env file!")
        print("Please configure AWS credentials in Settings first.")
        return False

    print(f"Using credentials: {aws_access_key_id[:10]}...")

    # Read the template
    with open('aws-iam-setup/kamiwaza-iam-assume-role.yaml', 'r') as f:
        template_body = f.read()

    # Initialize CloudFormation client with credentials
    cf_client = boto3.client(
        'cloudformation',
        region_name='us-west-2',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )

    stack_name = 'kamiwaza-iam-role'

    print("Creating CloudFormation stack...")
    print(f"Stack name: {stack_name}")
    print(f"Region: us-west-2")

    try:
        # Create stack
        response = cf_client.create_stack(
            StackName=stack_name,
            TemplateBody=template_body,
            Parameters=[
                {
                    'ParameterKey': 'TrustedPrincipalArn',
                    'ParameterValue': 'arn:aws:iam::916994818137:user/kamiwaza-provisioner'
                },
                {
                    'ParameterKey': 'ExternalId',
                    'ParameterValue': ''
                }
            ],
            Capabilities=['CAPABILITY_NAMED_IAM'],
            Tags=[
                {
                    'Key': 'ManagedBy',
                    'Value': 'KamiwazaDeploymentManager'
                }
            ]
        )

        stack_id = response['StackId']
        print(f"✓ Stack creation initiated: {stack_id}")
        print("\nWaiting for stack creation to complete (this may take 2-3 minutes)...")

        # Wait for stack creation
        waiter = cf_client.get_waiter('stack_create_complete')
        waiter.wait(
            StackName=stack_name,
            WaiterConfig={
                'Delay': 10,
                'MaxAttempts': 30
            }
        )

        print("✓ Stack created successfully!")

        # Get stack outputs
        response = cf_client.describe_stacks(StackName=stack_name)
        stack = response['Stacks'][0]

        print("\n" + "="*60)
        print("STACK OUTPUTS")
        print("="*60)

        for output in stack.get('Outputs', []):
            key = output['OutputKey']
            value = output['OutputValue']
            description = output.get('Description', '')
            print(f"\n{key}:")
            print(f"  {value}")
            if description:
                print(f"  ({description})")

        print("\n" + "="*60)
        print("\n✓ IAM Role is ready!")
        print("\nThe Role ARN has been configured in your .env file.")
        print("You can now create and run EC2 provisioning jobs!")

        return True

    except cf_client.exceptions.AlreadyExistsException:
        print(f"✗ Stack '{stack_name}' already exists!")
        print("\nTo view existing stack:")
        print(f"  Stack name: {stack_name}")

        # Try to get outputs anyway
        try:
            response = cf_client.describe_stacks(StackName=stack_name)
            stack = response['Stacks'][0]

            print(f"  Status: {stack['StackStatus']}")

            if stack.get('Outputs'):
                print("\nExisting outputs:")
                for output in stack['Outputs']:
                    print(f"  {output['OutputKey']}: {output['OutputValue']}")
        except Exception as e:
            print(f"  (Could not retrieve details: {e})")

        return False

    except Exception as e:
        print(f"✗ Error creating stack: {e}")
        return False

if __name__ == '__main__':
    success = deploy_iam_role()
    sys.exit(0 if success else 1)
