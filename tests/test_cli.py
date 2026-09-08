"""
End-to-end tests for the CLI commands, using moto to mock AWS and
Typer CliRunner to invoke commands in-process.
"""

import json

import pytest
from moto import mock_aws
from typer.testing import CliRunner

import cloud_auditor.storage as storage
from cloud_auditor.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "test_cache.json"
    monkeypatch.setattr(storage, "CACHE_PATH", str(cache_file))
    yield


@mock_aws
def test_scan_ebs_finds_unattached_volume():
    import boto3
    client = boto3.client("ec2", region_name="us-east-1")
    client.create_volume(AvailabilityZone="us-east-1a", Size=8)

    result = runner.invoke(app, ["--region", "us-east-1", "scan", "ebs"])

    assert result.exit_code == 0
    assert "1 unattached" in result.output


@mock_aws
def test_scan_ebs_ignores_attached_volume():
    import boto3
    client = boto3.client("ec2", region_name="us-east-1")
    volume = client.create_volume(AvailabilityZone="us-east-1a", Size=8)

    instance = client.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t2.micro"
    )["Instances"][0]
    client.attach_volume(
        VolumeId=volume["VolumeId"],
        InstanceId=instance["InstanceId"],
        Device="/dev/sdf",
    )

    result = runner.invoke(app, ["--region", "us-east-1", "scan", "ebs"])

    assert result.exit_code == 0
    assert "0 unattached" in result.output


@mock_aws
def test_scan_eip_finds_unassociated_address():
    import boto3
    client = boto3.client("ec2", region_name="us-east-1")
    client.allocate_address(Domain="vpc")

    result = runner.invoke(app, ["--region", "us-east-1", "scan", "eip"])

    assert result.exit_code == 0
    assert "1 unassociated" in result.output


@mock_aws
def test_scan_ec2_flags_idle_instance():
    import boto3
    client = boto3.client("ec2", region_name="us-east-1")
    client.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t2.micro")

    result = runner.invoke(app, ["--region", "us-east-1", "scan", "ec2"])

    assert result.exit_code == 0
    assert "1 idle instance" in result.output


def test_invalid_region_is_rejected():
    result = runner.invoke(app, ["--region", "not-a-real-region", "scan", "ebs"])

    assert result.exit_code == 1
    assert "not a recognized AWS region" in result.output


@mock_aws
def test_report_export_json_writes_cached_findings(tmp_path, monkeypatch):
    import boto3
    monkeypatch.chdir(tmp_path)

    client = boto3.client("ec2", region_name="us-east-1")
    client.create_volume(AvailabilityZone="us-east-1a", Size=8)
    runner.invoke(app, ["--region", "us-east-1", "scan", "ebs"])

    result = runner.invoke(app, ["report", "export", "--format", "json", "--output", "out"])

    assert result.exit_code == 0
    output_file = tmp_path / "out.json"
    assert output_file.exists()

    data = json.loads(output_file.read_text())
    assert "ebs" in data
    assert len(data["ebs"]["items"]) == 1


@mock_aws
def test_report_export_csv_writes_cached_findings(tmp_path, monkeypatch):
    import boto3
    monkeypatch.chdir(tmp_path)

    client = boto3.client("ec2", region_name="us-east-1")
    client.allocate_address(Domain="vpc")
    runner.invoke(app, ["--region", "us-east-1", "scan", "eip"])

    result = runner.invoke(app, ["report", "export", "--format", "csv", "--output", "out"])

    assert result.exit_code == 0
    output_file = tmp_path / "out.csv"
    assert output_file.exists()
    content = output_file.read_text()
    assert "eip" in content


def test_report_export_with_no_scans_yet():
    result = runner.invoke(app, ["report", "export"])

    assert result.exit_code == 0
    assert "No scan results found" in result.output


@mock_aws
def test_cleanup_run_dry_run_does_not_delete():
    import boto3
    client = boto3.client("ec2", region_name="us-east-1")
    volume = client.create_volume(AvailabilityZone="us-east-1a", Size=8)

    runner.invoke(app, ["--region", "us-east-1", "scan", "ebs"])
    result = runner.invoke(app, ["cleanup", "run"])

    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "No resources were deleted" in result.output

    volumes = client.describe_volumes()["Volumes"]
    assert any(v["VolumeId"] == volume["VolumeId"] for v in volumes)


@mock_aws
def test_cleanup_run_execute_deletes_flagged_resources():
    import boto3
    client = boto3.client("ec2", region_name="us-east-1")
    volume = client.create_volume(AvailabilityZone="us-east-1a", Size=8)

    runner.invoke(app, ["--region", "us-east-1", "scan", "ebs"])
    result = runner.invoke(app, ["cleanup", "run", "--execute"], input="y" + chr(10))

    assert result.exit_code == 0
    assert "Deleted volume" in result.output

    volumes = client.describe_volumes()["Volumes"]
    assert not any(v["VolumeId"] == volume["VolumeId"] for v in volumes)


def test_cleanup_run_with_no_scans_yet():
    result = runner.invoke(app, ["cleanup", "run"])

    assert result.exit_code == 0
    assert "No scan results found" in result.output
