"""
Cloud Infrastructure Auditor & Cost Optimizer CLI.

Entry point and command routing structure.
"""

import click

from cloud_auditor.aws_session import get_client


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


@scan.command("ec2")
@click.option("--days", default=14, help="Lookback window in days for CPU utilization.")
@click.pass_context
def scan_ec2(ctx, days):
    """Scan for underutilized EC2 instances (low CPU over N days)."""
    click.echo(f"[stub] region={ctx.obj['region']} profile={ctx.obj['profile']} - scanning EC2 idle over {days} days...")


@cli.group()
def report():
    """Generate or export audit reports."""
    pass


@report.command("export")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="json", help="Export format.")
@click.option("--output", default="report", help="Output file name (without extension).")
def report_export(fmt, output):
    """Export the most recent scan results as CSV or JSON."""
    click.echo(f"[stub] Exporting report as {fmt} to {output}.{fmt}...")


@cli.group()
def cleanup():
    """Clean up flagged resources (requires confirmation)."""
    pass


@cleanup.command("run")
@click.option("--dry-run/--execute", default=True, help="Dry-run (default) or actually execute cleanup.")
def cleanup_run(dry_run):
    """Run cleanup on flagged resources."""
    mode = "DRY RUN" if dry_run else "EXECUTE"
    click.echo(f"[stub] Cleanup mode: {mode}")
    if not dry_run:
        click.confirm("This will delete real resources. Are you sure?", abort=True)
        click.echo("[stub] Executing cleanup...")


if __name__ == "__main__":
    cli()
