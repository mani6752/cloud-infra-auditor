"""
Tests for aws_session.py, using moto to mock AWS so no real
credentials or API calls are needed.
"""

import os
import pytest
from moto import mock_aws

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from cloud_auditor.aws_session import get_client


@mock_aws
def test_get_client_can_call_ec2_describe_regions():
    """A client built via get_client() should be able to make a real (mocked) API call."""
    client = get_client("ec2", region="us-east-1")
    response = client.describe_regions()
    assert "Regions" in response
    assert len(response["Regions"]) > 0


@mock_aws
def test_get_client_creates_volume_and_lists_it():
    """Sanity check: we can create a fake EBS volume and see it via the client."""
    client = get_client("ec2", region="us-east-1")
    created = client.create_volume(AvailabilityZone="us-east-1a", Size=8)
    volume_id = created["VolumeId"]

    volumes = client.describe_volumes()["Volumes"]
    volume_ids = [v["VolumeId"] for v in volumes]

    assert volume_id in volume_ids
