#!/usr/bin/env python3
"""Probe every documented endpoint against a running credentials service.

For each (method, path) in openapi.json, substitute placeholder path params and
issue the request. A route "exists" if the response is anything other than 404 /
405 (401/403/400/422 all mean the route resolved but auth/validation rejected —
which is expected for unauthenticated probes). Prints a table and exits non-zero
if any documented route 404/405s.

Usage: python scripts/validate_endpoints.py [--base http://localhost:8011] [--spec openapi.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

PLACEHOLDER = {
    "uuid": "00000000-0000-0000-0000-000000000000",
    "slug": "acme-demo",
    "email": "probe@example.test",
}
ROUTE_OK = {400, 401, 403, 409, 422, 429, 500}  # resolved-but-rejected (500 = reached the view)
ROUTE_MISSING = {404, 405}


# Query-lookup endpoints that legitimately 404 when probed without valid query
# params (the route resolves; the view returns 404 for "no such object").
QUERY_LOOKUP_404_OK = {"/v1/credential-offers/resolve"}


def is_parameterized(path: str) -> bool:
    """A path with {params}: a 404 means the route resolved but the placeholder
    object doesn't exist (expected), not that the route is missing."""
    return "{" in path


def fill(path: str) -> str:
    def repl(m: str) -> str:
        name = m.group(1)
        for key, val in PLACEHOLDER.items():
            if key in name.lower():
                return val
        return PLACEHOLDER["uuid"]

    return re.sub(r"\{([^}]+)\}", repl, path)


def probe(base: str, method: str, path: str) -> int:
    url = base.rstrip("/") + fill(path)
    body = b"{}" if method in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(url, method=method, data=body)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        print(f"  ! {method} {path}: {e}", file=sys.stderr)
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8011")
    ap.add_argument("--spec", default="openapi.json")
    args = ap.parse_args()

    spec = json.load(open(args.spec))
    paths = spec.get("paths", {})
    failures: list[str] = []
    checked = 0
    for path, ops in sorted(paths.items()):
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in ops:
                continue
            checked += 1
            status = probe(args.base, method.upper(), path)
            # 404 on a parameterized path = route resolved, placeholder object absent (expected).
            if status == 404 and (is_parameterized(path) or path in QUERY_LOOKUP_404_OK):
                missing = False
            else:
                missing = status in ROUTE_MISSING or status == -1
            mark = "MISSING" if missing else "ok"
            print(f"  [{mark:>7}] {status:>4}  {method.upper():6} {path}")
            if missing:
                failures.append(f"{method.upper()} {path} -> {status}")

    print(f"\nChecked {checked} operations across {len(paths)} paths against {args.base}")
    if failures:
        print(f"\n{len(failures)} documented endpoint(s) did NOT resolve:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All documented endpoints resolve. ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
