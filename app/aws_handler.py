import boto3
from typing import Dict, Optional, Tuple
from botocore.exceptions import ClientError, BotoCoreError
import logging

logger = logging.getLogger(__name__)


class AWSAuthError(Exception):
    """Custom exception for AWS authentication errors"""
    pass


class AWSHandler:
    """Handles AWS authentication and credential management"""

    @staticmethod
    def assume_role(
        role_arn: str,
        session_name: str,
        external_id: Optional[str] = None,
        region: str = "us-east-1",
        duration_seconds: int = 3600
    ) -> Dict[str, str]:
        """
        Assume an IAM role using STS and return temporary credentials.

        Returns:
            Dict with keys: access_key, secret_key, session_token, region

        Raises:
            AWSAuthError: If role assumption fails
        """
        try:
            sts_client = boto3.client('sts', region_name=region)

            assume_role_params = {
                'RoleArn': role_arn,
                'RoleSessionName': session_name,
                'DurationSeconds': duration_seconds
            }

            if external_id:
                assume_role_params['ExternalId'] = external_id

            logger.info(f"Assuming role: {role_arn} with session: {session_name}")
            response = sts_client.assume_role(**assume_role_params)

            credentials = response['Credentials']

            return {
                'access_key': credentials['AccessKeyId'],
                'secret_key': credentials['SecretAccessKey'],
                'session_token': credentials['SessionToken'],
                'region': region
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"Failed to assume role {role_arn}: {error_code} - {error_msg}")
            raise AWSAuthError(f"AssumeRole failed: {error_code} - {error_msg}")
        except BotoCoreError as e:
            logger.error(f"Boto core error assuming role: {str(e)}")
            raise AWSAuthError(f"AWS SDK error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error assuming role: {str(e)}")
            raise AWSAuthError(f"Unexpected error: {str(e)}")

    @staticmethod
    def get_caller_identity(credentials: Dict[str, str]) -> Tuple[str, str, str]:
        """
        Get the caller identity for the given credentials.

        Returns:
            Tuple of (account_id, arn, user_id)

        Raises:
            AWSAuthError: If unable to get caller identity
        """
        try:
            session = boto3.Session(
                aws_access_key_id=credentials['access_key'],
                aws_secret_access_key=credentials['secret_key'],
                aws_session_token=credentials.get('session_token'),
                region_name=credentials.get('region', 'us-east-1')
            )

            sts_client = session.client('sts')
            response = sts_client.get_caller_identity()

            return (
                response['Account'],
                response['Arn'],
                response['UserId']
            )

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"Failed to get caller identity: {error_msg}")
            raise AWSAuthError(f"GetCallerIdentity failed: {error_msg}")
        except Exception as e:
            logger.error(f"Unexpected error getting caller identity: {str(e)}")
            raise AWSAuthError(f"Unexpected error: {str(e)}")

    @staticmethod
    def validate_credentials(
        access_key: str,
        secret_key: str,
        region: str = "us-east-1"
    ) -> Dict[str, str]:
        """
        Validate access key credentials by calling GetCallerIdentity.

        Returns:
            Dict with keys: access_key, secret_key, region

        Raises:
            AWSAuthError: If credentials are invalid
        """
        try:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )

            sts_client = session.client('sts')
            sts_client.get_caller_identity()

            return {
                'access_key': access_key,
                'secret_key': secret_key,
                'region': region
            }

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"Invalid credentials: {error_msg}")
            raise AWSAuthError(f"Invalid credentials: {error_msg}")
        except Exception as e:
            logger.error(f"Error validating credentials: {str(e)}")
            raise AWSAuthError(f"Error validating credentials: {str(e)}")

    @staticmethod
    def create_boto3_session(credentials: Dict[str, str]) -> boto3.Session:
        """Create a boto3 session from credentials dict"""
        return boto3.Session(
            aws_access_key_id=credentials['access_key'],
            aws_secret_access_key=credentials['secret_key'],
            aws_session_token=credentials.get('session_token'),
            region_name=credentials.get('region', 'us-east-1')
        )
