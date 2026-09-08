"""
Cloud Infrastructure Auditor & Cost Optimizer CLI.

Entry point and command routing structure (built on Typer).
"""

import csv
import datetime
import json

import typer
from rich.console import Console
from rich.table import Table

console = Console()

from cloud_auditor.aws_session import get_client
from cloud_auditor.storage import save_scan_results, load_all_results
from cloud_auditor.aws_utils import is_valid_region, with_backoff

app = typer.Typer(help="Cloud Infrastructure Auditor & Cost Optimizer.")
scan_app = typer.Typer(help="Scan cloud infrastructure for wasteful or misconfigured resources.")
report_app = typer.Typer(help="Generate or export audit reports.")
cleanup_app = typer.Typer(help="Clean up flagged resources (requires confirmation).")

app.add_typer(scan_app, name="scan")
app.add_typer(report_app, name="report")
app.add_typer(cleanup_app, name="cleanup")


def version_callback(value: bool):
    if value:
        typer.echo("0.1.0")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    profile: str = typer.Option(None, help="AWS named profile to use."),
    region: str = typer.Option("us-east-1", help="AWS region to operate in."),
    role_arn: str = typer.Option(None, help="Optional IAM role ARN to assume."),
    version: bool = typer.Option(False, "--version", callback=version_callback, is_eager=True, help="Show the version and exit."),
):
    """
    Scans AWS/GCP infrastructure for orphaned, underutilized, or
    misconfigured resources and generates cost-saving reports.
    """
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["region"] = region
    ctx.obj["role_arn"] = role_arn

    if not is_valid_region(region):
        typer.echo(f"'{region}' is not a recognized AWS region. Run with a valid region, e.g. us-east-1, eu-west-1, ap-southeast-2.")
        raise typer.Exit(code=1)


@scan_app.command("ebs")
def scan_ebs(ctx: typer.Context):
    """Scan for unattached EBS volumes."""
    client = get_client(
        "ec2",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )
    @with_backoff()
    def _describe_volumes():
        return client.describe_volumes()["Volumes"]
    volumes = _describe_volumes()
    unattached = [v for v in volumes if not v.get("Attachments")]
    console.print(f"Found [bold]{len(volumes)}[/bold] volume(s) total, [bold red]{len(unattached)}[/bold red] unattached, in region={ctx.obj['region']}")
    if unattached:
        table = Table(title="Unattached EBS Volumes")
        table.add_column("Volume ID", style="cyan")
        table.add_column("Size (GiB)", justify="right")
        table.add_column("Type")
        for v in unattached:
            table.add_row(v["VolumeId"], str(v["Size"]), v["VolumeType"])
        console.print(table)

    save_scan_results("ebs", ctx.obj["region"], [
        {"volume_id": v["VolumeId"], "size_gib": v["Size"], "volume_type": v["VolumeType"]}
        for v in unattached
    ])


@scan_app.command("eip")
def scan_eip(ctx: typer.Context):
    """Scan for unassociated Elastic IPs."""
    client = get_client(
        "ec2",
        profile=ctx.obj["profile"],
        region=ctx.obj["region"],
        role_arn=ctx.obj["role_arn"],
    )
    @with_backoff()
    def _describe_addresses():
        return client.describe_addresses()["Addresses"]
    addresses = _describe_addresses()
    unassociated = [a for a in addresses if not a.get("AssociationId")]
    console.print(f"Found [bold]{len(addresses)}[/bold] Elastic IP(s) total, [bold red]{len(unassociated)}[/bold red] unassociated, in region={ctx.obj['region']}")
    if unassociated:
        table = Table(title="Unassociated Elastic IPs")
        table.add_column("Public IP", style="cyan")
        table.add_column("Allocation ID")
        for a in unassociated:
            table.add_row(str(a.get("PublicIp")), str(a.get("AllocationId", "n/a")))
        console.print(table)

    save_scan_results("eip", ctx.obj["region"], [
        {"public_ip": a.get("PublicIp"), "allocation_id": a.get("AllocationId")}
        for a in unassociated
    ])


@scan_app.command("ec2")
def scan_ec2(
    ctx: typer.Context,
    days: int = typer.Option(14, help="Lookback window in days for CPU utilization."),
    threshold: float = typer.Option(5.0, help="Average CPU%% below which an instance is flagged idle."),
):
    """Scan for underutilized EC2 instances (low CPU over N days)."""
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

    @with_backoff()
    def _describe_instances():
        return ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )["Reservations"]
    reservations = _describe_instances()
    instances = [i for r in reservations for i in r["Instances"]]

    end = datetime.datetime.now(datetime.UTC)
    start = end - datetime.timedelta(days=days)

    typer.echo(f"Checking {len(instances)} running instance(s) over the last {days} day(s), region={ctx.obj['region']}")

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
        avg_cpu = (sum(d["Average"] for d in datapoints) / len(datapoints)) if datapoints else 0.0

        if avg_cpu < threshold:
            idle.append((instance_id, avg_cpu))

    console.print(f"Found [bold red]{len(idle)}[/bold red] idle instance(s) (avg CPU below {threshold}%):")
    if idle:
        table = Table(title="Idle EC2 Instances")
        table.add_column("Instance ID", style="cyan")
        table.add_column("Avg CPU %", justify="right")
        for instance_id, avg_cpu in idle:
            table.add_row(instance_id, f"{avg_cpu:.2f}")
        console.print(table)

    save_scan_results("ec2", ctx.obj["region"], [
        {"instance_id": instance_id, "avg_cpu_percent": round(avg_cpu, 2)}
        for instance_id, avg_cpu in idle
    ])


@report_app.command("export")
def report_export(
    fmt: str = typer.Option("json", "--format", help="Export format: csv or json."),
    output: str = typer.Option("report", help="Output file name (without extension)."),
):
    """Export the most recent scan results as CSV or JSON."""
    if fmt not in ("csv", "json"):
        typer.echo("--format must be 'csv' or 'json'")
        raise typer.Exit(code=1)

    cache = load_all_results()
    if not cache:
        typer.echo("No scan results found. Run a scan command first (e.g. 'scan ebs').")
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
            typer.echo("No scan results to export.")
            return

        fieldnames = sorted({key for row in rows for key in row.keys()})
        with open(filename, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    typer.echo(f"Exported {sum(len(d['items']) for d in cache.values())} finding(s) across {len(cache)} scan type(s) to {filename}")


@cleanup_app.command("run")
def cleanup_run(
    ctx: typer.Context,
    execute: bool = typer.Option(False, "--execute/--dry-run", help="Actually execute cleanup (default: dry-run)."),
):
    """Run cleanup on flagged resources from the most recent scans."""
    dry_run = not execute
    cache = load_all_results()
    if not cache:
        typer.echo("No scan results found. Run scan commands first (e.g. 'scan ebs').")
        return

    mode = "DRY RUN" if dry_run else "EXECUTE"
    typer.echo(f"Cleanup mode: {mode}")

    total_items = sum(len(data["items"]) for data in cache.values())
    if total_items == 0:
        typer.echo("No flagged resources to clean up.")
        return

    typer.echo(f"Found {total_items} flagged resource(s) across {len(cache)} scan type(s):")
    for scan_type, data in cache.items():
        for item in data["items"]:
            typer.echo(f"  - [{scan_type}] {item}")

    if dry_run:
        typer.echo("Dry run complete. No resources were deleted. Re-run with --execute to actually delete them.")
        return

    typer.confirm(f"This will permanently delete {total_items} real resource(s). Are you sure?", abort=True)

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
            typer.echo(f"  Deleted volume {item['volume_id']}")
            deleted += 1
        except Exception as e:
            errors.append(f"volume {item['volume_id']}: {e}")

    for item in cache.get("eip", {}).get("items", []):
        try:
            client.release_address(AllocationId=item["allocation_id"])
            typer.echo(f"  Released Elastic IP {item['public_ip']}")
            deleted += 1
        except Exception as e:
            errors.append(f"EIP {item['public_ip']}: {e}")

    ec2_ids = [item["instance_id"] for item in cache.get("ec2", {}).get("items", [])]
    if ec2_ids:
        try:
            client.terminate_instances(InstanceIds=ec2_ids)
            for iid in ec2_ids:
                typer.echo(f"  Terminated instance {iid}")
            deleted += len(ec2_ids)
        except Exception as e:
            errors.append(f"instances {ec2_ids}: {e}")

    typer.echo(f"Cleanup complete: {deleted} resource(s) deleted.")
    if errors:
        typer.echo(f"{len(errors)} error(s) occurred:")
        for err in errors:
            typer.echo(f"  - {err}")


if __name__ == "__main__":
    app()
