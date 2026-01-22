#!/usr/bin/env python3
"""Upload Kamiwaza source zip to S3 for EC2 instance access"""

import boto3
from botocore.exceptions import ClientError
import sys
import csv
from pathlib import Path

def upload_to_s3():
    """Upload kamiwaza-main.zip to S3 bucket"""

    # Configuration
    bucket_name = "kamiwaza-provisioning-source"
    region = "us-west-2"
    source_file = Path("/Users/steffenmerten/Downloads/kamiwaza-release-0.9.2.zip")
    s3_key = "kamiwaza-release-0.9.2.zip"
    credentials_file = Path("/Users/steffenmerten/Downloads/kamiwaza-provisioner_accessKeys.csv")

    if not source_file.exists():
        print(f"Error: Source file not found: {source_file}")
        sys.exit(1)

    # Read AWS credentials from CSV (handle UTF-8 BOM)
    aws_access_key = None
    aws_secret_key = None
    if credentials_file.exists():
        with open(credentials_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                aws_access_key = row['Access key ID']
                aws_secret_key = row['Secret access key']
                break

    try:
        # Create S3 client with credentials
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )

        # Try to create bucket (will fail if exists, which is fine)
        try:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
            print(f"✓ Created S3 bucket: {bucket_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
                print(f"✓ Using existing S3 bucket: {bucket_name}")
            elif e.response['Error']['Code'] == 'BucketAlreadyExists':
                print(f"⚠ Bucket exists but owned by someone else. Using anyway: {bucket_name}")
            else:
                raise

        # Upload file
        print(f"Uploading {source_file.name} to s3://{bucket_name}/{s3_key}...")
        s3_client.upload_file(
            str(source_file),
            bucket_name,
            s3_key,
            ExtraArgs={
                'ServerSideEncryption': 'AES256'
            }
        )
        print(f"✓ Upload complete!")

        # Generate S3 URL
        s3_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
        print(f"\nS3 URL: {s3_url}")
        print(f"\nYou can now update config.py with:")
        print(f'kamiwaza_source_url: str = "{s3_url}"')

        return True

    except ClientError as e:
        print(f"Error uploading to S3: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    upload_to_s3()
