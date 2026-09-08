"""
Utility functions for AWS region handling and API rate-limit resilience.
"""

import time
import functools

import boto3
import botocore.exceptions


def list_available_regions(service_name="ec2"):
    """Return a sorted list of valid AWS region names for a given service."""
    session = boto3.Session()
    return sorted(session.get_available_regions(service_name))


def is_valid_region(region, service_name="ec2"):
    """Check whether a region string is a real AWS region for the given service."""
    return region in list_available_regions(service_name)


def with_backoff(max_attempts=5, base_delay=1.0):
    """
    Decorator that retries a function with exponential backoff when AWS
    throttles the request (ThrottlingException, RequestLimitExceeded, etc).
    Re-raises immediately for any other kind of error.
    """
    throttle_error_codes = {
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "ProvisionedThroughputExceededException",
    }

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except botocore.exceptions.ClientError as e:
                    error_code = e.response.get("Error", {}).get("Code", "")
                    attempt += 1
                    if error_code not in throttle_error_codes or attempt >= max_attempts:
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    time.sleep(delay)
        return wrapper
    return decorator
