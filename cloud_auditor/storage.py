"""
Simple local cache for storing scan results between CLI invocations.
"""

import json
import os
from datetime import datetime, timezone

CACHE_PATH = os.path.join(os.path.expanduser("~"), ".cloud_auditor_cache.json")


def save_scan_results(scan_type, region, items):
    """Save the results of a scan (list of dicts) under scan_type, overwriting any previous results for that type."""
    cache = load_all_results()
    cache[scan_type] = {
        "region": region,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def load_all_results():
    """Load all cached scan results. Returns {} if no cache file exists yet."""
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
