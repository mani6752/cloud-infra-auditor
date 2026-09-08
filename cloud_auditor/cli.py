"""
Cloud Infrastructure Auditor & Cost Optimizer CLI.

Entry point and command routing structure.
"""

import click
import json

from cloud_auditor.aws_session import get_client
from cloud_auditor.storage import save_scan_results, load_all_results


@click.group()
@click.version_option(version="0.1.0")
@click.option("--profile", default=None, help="AWS named profile to use.")
@click.option("--region", default="us-east-1", help="AWS region to operate in.")
@click.option("--role-arn", default=None, help="Optional IAM role ARN to assume.")
@click.pass_context
def cli(ctx, profile, region, role_arn):
    """
    Cloud Infrastructure Auditor & Cost Optimizer.

    Scans AWS/GCP infrastructure for orphaned, underutilized, or
    misconfigured resources and generates cost-saving reports.
    """
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["region"] = region
    ctx.obj["role_arn"] = role_arn


@cli.group()
def scan():
    """Scan cloud infrastructure for wasteful or misconfigured resources."""
    pass


@scan.command("ebs")
@click.pass_context
def scan_ebs(ctx):
    """Scan for unattached EBS volumes."""
    client = get_client(
        "ec2",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )
    volumes = client.describe_volumes()["Volumes"]
    unattached = [v for v in volumes if not v.get("Attachments")]
    click.echo(f"Found {len(volumes)} volume(s) total, {len(unattached)} unattached, in region={ctx.obj['region']}")
    for v in unattached:
        click.echo(f"  - {v['VolumeId']} ({v['Size']} GiB, {v['VolumeType']})")

    save_scan_results("ebs", ctx.obj["region"], [
        {"volume_id": v["VolumeId"], "size_gib": v["Size"], "volume_type": v["VolumeType"]}
        for v in unattached
    ])


@scan.command("eip")
@click.pass_context
def scan_eip(ctx):
    """Scan for unassociated Elastic IPs."""
    client = get_client(
        "ec2",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )
    addresses = client.describe_addresses()["Addresses"]
    unassociated = [a for a in addresses if not a.get("AssociationId")]
    click.echo(f"Found {len(addresses)} Elastic IP(s) total, {len(unassociated)} unassociated, in region={ctx.obj['region']}")
    for a in unassociated:
        click.echo(f"  - {a.get('PublicIp')} (allocation: {a.get('AllocationId', 'n/a')})")

    save_scan_results("eip", ctx.obj["region"], [
        {"public_ip": a.get("PublicIp"), "allocation_id": a.get("AllocationId")}
        for a in unassociated
    ])


@scan.command("ec2")
@click.option("--days", default=14, help="Lookback window in days for CPU utilization.")
@click.option("--threshold", default=5.0, help="Average CPU%% below which an instance is flagged idle.")
@click.pass_context
def scan_ec2(ctx, days, threshold):
    """Scan for underutilized EC2 instances (low CPU over N days)."""
    import datetime

    ec2 = get_client(
        "ec2",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )
    cw = get_client(
        "cloudwatch",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )

    reservations = ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )["Reservations"]
    instances = [i for r in reservations for i in r["Instances"]]

    end = datetime.datetime.now(datetime.UTC)
    start = end - datetime.timedelta(days=days)

    click.echo(f"Checking {len(instances)} running instance(s) over the last {days} day(s), region={ctx.obj['region']}")

    idle = []
    for inst in instances:
        instance_id = inst["InstanceId"]
        stats = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Average"],
        )
        datapoints = stats.get("Datapoints", [])
        if not datapoints:
            avg_cpu = 0.0
        else:
            avg_cpu = sum(d["Average"] for d in datapoints) / len(datapoints)

        if avg_cpu < threshold:
            idle.append((instance_id, avg_cpu))

    click.echo(f"Found {len(idle)} idle instance(s) (avg CPU below {threshold}%):")
    for instance_id, avg_cpu in idle:
        click.echo(f"  - {instance_id} (avg CPU: {avg_cpu:.2f}%)")

    save_scan_results("ec2", ctx.obj["region"], [
        {"instance_id": instance_id, "avg_cpu_percent": round(avg_cpu, 2)}
        for instance_id, avg_cpu in idle
    ])


@cli.group()
def report():
    """Generate or export audit reports."""
    pass


@report.command("export")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="json", help="Export format.")
@click.option("--output", default="report", help="Output file name (without extension).")
def report_export(fmt, output):
    """Export the most recent scan results as CSV or JSON."""
    import csv

    cache = load_all_results()
    if not cache:
        click.echo("No scan results found. Run a scan command first (e.g. 'scan ebs').")
        return

    filename = f"{output}.{fmt}"

    if fmt == "json":
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    else:
        rows = []
        for scan_type, data in cache.items():
            for item in data["items"]:
                row = {"scan_type": scan_type, "region": data["region"], "scanned_at": data["scanned_at"]}
                row.update(item)
                rows.append(row)

        if not rows:
            click.echo("No scan results to export.")
            return

        fieldnames = sorted({key for row in rows for key in row.keys()})
        with open(filename, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    click.echo(f"Exported {sum(len(d['items']) for d in cache.values())} finding(s) across {len(cache)} scan type(s) to {filename}")


@cli.group()
def cleanup():
    """Clean up flagged resources (requires confirmation)."""
    pass


@cleanup.command("run")
@click.option("--dry-run/--execute", default=True, help="Dry-run (default) or actually execute cleanup.")
@click.pass_context
def cleanup_run(ctx, dry_run):
    """Run cleanup on flagged resources from the most recent scans."""
    cache = load_all_results()
    if not cache:
        click.echo("No scan results found. Run scan commands first (e.g. 'scan ebs').")
        return

    mode = "DRY RUN" if dry_run else "EXECUTE"
    click.echo(f"Cleanup mode: {mode}")

    total_items = sum(len(data["items"]) for data in cache.values())
    if total_items == 0:
        click.echo("No flagged resources to clean up.")
        return

    click.echo(f"Found {total_items} flagged resource(s) across {len(cache)} scan type(s):")
    for scan_type, data in cache.items():
        for item in data["items"]:
            click.echo(f"  - [{scan_type}] {item}")

    if dry_run:
        click.echo("Dry run complete. No resources were deleted. Re-run with --execute to actually delete them.")
        return

    click.confirm(f"This will permanently delete {total_items} real resource(s). Are you sure?", abort=True)

    client = get_client(
        "ec2",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )

    deleted = 0
    errors = []

    for item in cache.get("ebs", {}).get("items", []):
        try:
            client.delete_volume(VolumeId=item["volume_id"])
            click.echo(f"  Deleted volume {item['volume_id']}")
            deleted += 1
        except Exception as e:
            errors.append(f"volume {item['volume_id']}: {e}")

    for item in cache.get("eip", {}).get("items", []):
        try:
            client.release_address(AllocationId=item["allocation_id"])
            click.echo(f"  Released Elastic IP {item['public_ip']}")
            deleted += 1
        except Exception as e:
            errors.append(f"EIP {item['public_ip']}: {e}")

    ec2_ids = [item["instance_id"] for item in cache.get("ec2", {}).get("items", [])]
    if ec2_ids:
        try:
            client.terminate_instances(InstanceIds=ec2_ids)
            for iid in ec2_ids:
                click.echo(f"  Terminated instance {iid}")
            deleted += len(ec2_ids)
        except Exception as e:
            errors.append(f"instances {ec2_ids}: {e}")

    click.echo(f"Cleanup complete: {deleted} resource(s) deleted.")
    if errors:
        click.echo(f"{len(errors)} error(s) occurred:")
        for err in errors:
            click.echo(f"  - {err}")


if __name__ == "__main__":
    cli()
