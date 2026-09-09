from setuptools import setup, find_packages

setup(
    name="cloud-auditor",
    version="0.1.0",
    description="Cloud Infrastructure Auditor & Cost Optimizer CLI",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=[
        "typer",
        "rich",
        "boto3",
        "pyyaml",
    ],
    entry_points={
        "console_scripts": [
            "cloud-auditor=cloud_auditor.cli:app",
        ],
    },
    python_requires=">=3.9",
)
