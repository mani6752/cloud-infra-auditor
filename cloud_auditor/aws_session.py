"""
AWS session and credential handling.

Supports:
  - Named AWS profiles (from ~/.aws/credentials or ~/.aws/config)
  - Explicit region override
  - Assumed IAM roles (via --role-arn)
  - Falls back to the default credential chain (env vars, instance profile, etc.)
    if no profile is given.
"""

import boto3
import click


def get_session(profile=None, region="us-east-1", role_arn=None):
    """
    Build a boto3 Session using the given profile/region, optionally
    assuming an IAM role on top of the base credentials.
    """
    base_session = boto3.Session(profile_name=profile, region_name=region)

    if role_arn:
        sts_client = base_session.client("sts")
        try:
            assumed = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="cloud-auditor-session",
            )
        except Exception as e:
            raise click.ClickException(f"Failed to assume role {role_arn}: {e}")

        creds = assumed["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

    return base_session


def get_client(service_name, profile=None, region="us-east-1", role_arn=None):
    """Convenience wrapper: get a boto3 client for a given AWS service."""
    session = get_session(profile=profile, region=region, role_arn=role_arn)
    try:
        return session.client(service_name)
    except Exception as e:
        raise click.ClickException(f"Failed to create {service_name} client: {e}")
