Cloud Infrastructure Auditor \& Cost Optimizer



A command-line tool that scans AWS infrastructure for wasteful or orphaned resources (unattached EBS volumes, unassociated Elastic IPs, idle EC2 instances), reports on them, and can clean them up.



1\. How the project is put together

cloud-infra-auditor/

├── cloud\_auditor/

│   ├── cli.py            # Entry point — all CLI commands live here

│   ├── aws\_session.py    # Builds boto3 sessions/clients (profile, region, role assumption)

│   └── storage.py        # Local JSON cache of the most recent scan results

├── tests/

│   └── test\_aws\_session.py   # moto-based tests for the session/client layer

├── requirements.txt

└── .gitignore



Design principle: each scan command talks to AWS via a shared get\_client() helper, saves its findings to a small local cache file, and report export / cleanup run both read from that same cache. This means the CLI always acts on the most recent scan, and different commands don't need to re-scan AWS to know what was found.



2\. aws\_session.py — building boto3 clients



This module is the single place that knows how to build a boto3 client. It accepts an optional AWS named profile, a region, and an optional role\_arn to assume. Every other module (cli.py) calls get\_client(service\_name, profile=..., region=..., role\_arn=...) instead of calling boto3.client() directly — that way credential logic only exists in one place, and it's the one thing that gets unit-tested directly with moto (tests/test\_aws\_session.py), independent of the CLI.



3\. storage.py — the local scan cache



Scan results are written to a JSON file at:



\~/.cloud\_auditor\_cache.json



Structure:



json

{

&#x20; "ebs": {

&#x20;   "region": "us-east-1",

&#x20;   "scanned\_at": "2026-09-08T19:56:07Z",

&#x20;   "items": \[ { "volume\_id": "...", "size\_gib": 8, "volume\_type": "gp2" } ]

&#x20; },

&#x20; "eip": { "...": "..." },

&#x20; "ec2": { "...": "..." }

}



Each scan type (ebs, eip, ec2) overwrites its own section on every new scan, so the cache always reflects the latest scan of each type — you don't need to re-run all three scans if you only care about volumes, for example.



save\_scan\_results() writes to it, load\_all\_results() reads it back. This is intentionally simple (a flat JSON file, no database) since the tool is a single-user CLI, not a server.



4\. The CLI commands



All commands are grouped under one cli entry point with global options:



python -m cloud\_auditor.cli --profile <name> --region <region> --role-arn <arn> <group> <command>

\--profile — AWS named profile (from \~/.aws/credentials). Defaults to none (falls back to default credential chain).

\--region — AWS region to operate in. Defaults to us-east-1.

\--role-arn — optional IAM role to assume before making calls.



These three values flow into every command via Click's context object (ctx.obj), so you only set them once per invocation, not per sub-command.



4.1 scan ebs

python -m cloud\_auditor.cli scan ebs



Calls describe\_volumes(), filters for volumes with no Attachments (i.e. not attached to any instance), prints them, and saves the findings to the cache under "ebs".



4.2 scan eip

python -m cloud\_auditor.cli scan eip



Calls describe\_addresses(), filters for addresses with no AssociationId (i.e. allocated but not attached to any running instance or network interface), prints them, and saves to the cache under "eip".



4.3 scan ec2

python -m cloud\_auditor.cli scan ec2 --days 14 --threshold 5.0

Lists all running instances via describe\_instances().

For each instance, pulls average CPU utilization from CloudWatch (get\_metric\_statistics) over the last --days days (default 14).

Flags any instance whose average CPU is below --threshold percent (default 5.0%) as idle.

Saves the flagged instances to the cache under "ec2".



Note: instances with no CloudWatch datapoints at all are treated as 0% average CPU (this is what you'll see against a mock like moto, which doesn't generate synthetic metrics — against real AWS, a genuinely idle instance will actually have real near-zero datapoints).



4.4 report export

python -m cloud\_auditor.cli report export --format json --output my\_report

python -m cloud\_auditor.cli report export --format csv  --output my\_report



Reads the entire local cache (all scan types at once, whatever was last run) and writes it out:



JSON — the cache structure, written as-is.

CSV — flattened into one row per finding, with a scan\_type, region, and scanned\_at column plus whatever fields that finding type has (e.g. volume\_id/size\_gib for EBS, public\_ip/allocation\_id for EIP). Since different scan types have different fields, the CSV has a union of all columns — cells that don't apply to a given row are left blank. This is expected, not a bug.



If no scans have been run yet, it tells you to run one first instead of producing an empty/misleading file.



4.5 cleanup run

python -m cloud\_auditor.cli cleanup run              # dry run (default, safe)

python -m cloud\_auditor.cli cleanup run --execute     # actually deletes, asks to confirm



Reads the same cache used by report export and, for every flagged resource across all three scan types:



Dry run (default): lists every resource that would be deleted. Nothing is touched.

Execute: prompts for a yes/no confirmation showing the total count of resources about to be deleted, then, if confirmed:

delete\_volume() for each cached EBS volume

release\_address() for each cached Elastic IP

terminate\_instances() for all cached idle EC2 instances (all IDs passed together in one call)

Any individual failure (e.g. a resource already deleted elsewhere) is caught and reported at the end without stopping the rest of the cleanup.



Design decision: EC2 instance termination is included by default alongside EBS/EIP cleanup (not gated behind a separate flag) — meaning cleanup run --execute will terminate every instance the last scan ec2 flagged as idle. Since "idle" is a CPU-based heuristic and not a certainty, always review the dry-run output carefully before running --execute.



5\. How this was tested during development (moto)



moto is a library that mocks AWS APIs either in-process (@mock\_aws decorator, used in tests/test\_aws\_session.py) or as a standalone local server that mimics real AWS endpoints over HTTP — which is what was used to test the full CLI end-to-end without touching real AWS or needing real credentials.



Setup used throughout development



Terminal 1 — run the mock AWS server:



powershell

venv\\Scripts\\Activate.ps1

python -m moto.server -p 5001



Leave this running. It logs every fake API call it receives.



Terminal 2 — point the CLI at it:



powershell

venv\\Scripts\\Activate.ps1

$env:AWS\_ACCESS\_KEY\_ID="testing"

$env:AWS\_SECRET\_ACCESS\_KEY="testing"

$env:AWS\_DEFAULT\_REGION="us-east-1"

$env:AWS\_ENDPOINT\_URL="http://localhost:5001"



AWS\_ENDPOINT\_URL is a real boto3-recognized environment variable (boto3 ≥ 1.28) that redirects every client to that URL instead of real AWS — no code changes needed in aws\_session.py to support it.



Seeding fake resources (since moto starts empty)

powershell

\# Fake unattached volume

python -c "import boto3; c = boto3.client('ec2', region\_name='us-east-1', endpoint\_url='http://localhost:5001'); print(c.create\_volume(AvailabilityZone='us-east-1a', Size=8))"



\# Fake unassociated Elastic IP

python -c "import boto3; c = boto3.client('ec2', region\_name='us-east-1', endpoint\_url='http://localhost:5001'); print(c.allocate\_address(Domain='vpc'))"



\# Fake running instance

python -c "import boto3; c = boto3.client('ec2', region\_name='us-east-1', endpoint\_url='http://localhost:5001'); print(c.run\_instances(ImageId='ami-12345678', MinCount=1, MaxCount=1, InstanceType='t2.micro'))"

The verification loop used for every feature

Seed a fake resource on moto.

Run the relevant scan command — confirm it finds the seeded resource.

Run report export — confirm the finding shows up in JSON/CSV.

Run cleanup run (dry run, then --execute) — confirm deletion.

Re-run the scan command — confirm the resource is now gone (0 found), proving the delete call genuinely worked against the (mock) API and wasn't just a local cache change.



This loop is what confirmed every command does what it claims against a real AWS-shaped API surface, not just against hardcoded/stubbed output.



6\. Running it against real AWS



Everything above uses AWS\_ENDPOINT\_URL to redirect to the local mock server. To run against real AWS instead:



Remove/unset AWS\_ENDPOINT\_URL.

Set up real credentials — either a named profile in \~/.aws/credentials (used via --profile), environment variables, or an IAM role (--role-arn) if running from an EC2 instance or CI system with an existing role to assume.

Run the same commands as above. aws\_session.get\_client() uses the exact same code path either way — the only thing that changes is which endpoint boto3 actually talks to.



Caution: cleanup run --execute against real AWS will genuinely delete real resources. Always run scan + review the dry-run output first.



7\. Current state / what's not built yet

✅ AWS: EBS, EIP, EC2 idle scanning, JSON/CSV export, cleanup with dry-run

🔲 GCP support (mentioned in the original CLI docstring, not implemented)

🔲 Automated tests for report export and cleanup run specifically (only aws\_session.py has a dedicated test file so far)

🔲 No CI pipeline configured yet (e.g. GitHub Actions to run pytest on every push)



