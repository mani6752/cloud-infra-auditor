"""
Cloud Infrastructure Auditor & Cost Optimizer CLI.

Entry point and command routing structure.
"""

import click


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """
    Cloud Infrastructure Auditor & Cost Optimizer.

    Scans AWS/GCP infrastructure for orphaned, underutilized, or
    misconfigured resources and generates cost-saving reports.
    """
    pass


@cli.group()
def scan():
    """Scan cloud infrastructure for wasteful or misconfigured resources."""
    pass


@scan.command("ebs")
@click.option("--region", default="us-east-1", help="AWS region to scan.")
@click.option("--profile", default=None, help="AWS named profile to use.")
def scan_ebs(region, profile):
    """Scan for unattached EBS volumes."""
    click.echo(f"[stub] Scanning region={region} profile={profile} for unattached EBS volumes...")


@scan.command("eip")
@click.option("--region", default="us-east-1", help="AWS region to scan.")
@click.option("--profile", default=None, help="AWS named profile to use.")
def scan_eip(region, profile):
    """Scan for unassociated Elastic IPs."""
    click.echo(f"[stub] Scanning region={region} profile={profile} for unassociated Elastic IPs...")


@scan.command("ec2")
@click.option("--region", default="us-east-1", help="AWS region to scan.")
@click.option("--profile", default=None, help="AWS named profile to use.")
@click.option("--days", default=14, help="Lookback window in days for CPU utilization.")
def scan_ec2(region, profile, days):
    """Scan for underutilized EC2 instances (low CPU over N days)."""
    click.echo(f"[stub] Scanning region={region} profile={profile} for EC2 instances idle over {days} days...")


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
