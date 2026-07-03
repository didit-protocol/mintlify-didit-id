#!/usr/bin/env python3
"""Validate that the DOCUMENTED response schema of every safe/idempotent endpoint still matches
what the LIVE API returns — using a freshly bootstrapped tenant so nothing depends on prior state.

For each checked call it:
  1. re-issues the request against a fresh tenant key,
  2. reads the documented 2xx schema out of openapi.json,
  3. best-effort asserts the shapes agree: same top-level JSON type (object vs bare array), and
     every key present in the LIVE body is DOCUMENTED (no undocumented fields leaking), and at
     least the documented keys that aren't nullable/optional are present.

Prints a pass/fail table and exits non-zero on any failure.

Usage: python scripts/validate_examples.py [--base http://localhost:8011] [--spec openapi.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_examples import Client, bootstrap_tenant  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Documented keys that are legitimately absent from some instances (nullable / conditional).
OPTIONAL_KEYS = {
    "email_skipped_reason", "supersedes", "expires_at", "source_session_id", "purpose",
    "trusted_iss", "jwks_uri", "did", "framework", "error", "state", "email_send_count",
    "claim_url", "recipient_email", "validation", "versions", "next_url", "previous_url",
}


def documented_schema(spec, method, path):
    op = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    for code in ("200", "201"):
        content = op.get("responses", {}).get(code, {}).get("content", {}).get("application/json", {})
        if content.get("schema"):
            return code, content["schema"]
    return None, None


def expected_keys(schema):
    """(top_type, key->nullable) for the object (or the array element)."""
    t = schema.get("type")
    if t == "array":
        el = schema.get("items", {})
        return "array", {k: _nullable(v) for k, v in el.get("properties", {}).items()}
    return "object", {k: _nullable(v) for k, v in schema.get("properties", {}).items()}


def _nullable(node):
    t = node.get("type")
    return (isinstance(t, list) and "null" in t)


def live_keys(body):
    if isinstance(body, list):
        return "array", (set(body[0].keys()) if body and isinstance(body[0], dict) else set())
    if isinstance(body, dict):
        return "object", set(body.keys())
    return type(body).__name__, set()


def check(name, spec, method, path, status, body):
    code, schema = documented_schema(spec, method, path)
    if schema is None:
        return "SKIP", "no documented 2xx schema"
    exp_type, exp = expected_keys(schema)
    live_type, live = live_keys(body)
    if status not in (200, 201):
        return "FAIL", f"live status {status}"
    if exp_type != live_type:
        return "FAIL", f"type mismatch: doc={exp_type} live={live_type}"
    undocumented = live - set(exp)
    missing_required = {k for k, nul in exp.items()
                        if k not in live and not nul and k not in OPTIONAL_KEYS}
    if undocumented:
        return "FAIL", f"undocumented live keys: {sorted(undocumented)}"
    if missing_required and live:  # empty array/obj -> can't assert presence
        return "FAIL", f"documented keys missing from live: {sorted(missing_required)}"
    detail = f"{len(live & set(exp))}/{len(exp)} keys matched"
    if not live:
        detail += " (empty result)"
    return "PASS", detail


def run(base, spec_path):
    spec = json.loads(Path(spec_path).read_text())
    cli = Client(base)
    print("Bootstrapping a fresh tenant …")
    key, slug, _ = bootstrap_tenant(cli)

    def A(method, path, **kw):
        return cli.call(method, path, token=key, **kw)

    # Build a minimal set of live resources so parameterized GETs have something to read.
    _, schema = A("POST", "/v1/credential-schemas",
                  body={"name": "Val Schema", "vct": "ValVCT",
                        "attributes": [{"name": "tier", "sd": True}]})
    schema_id = schema.get("uuid")
    _, tpl = A("POST", "/v1/credential-templates",
               body={"schema": schema_id, "name": "v", "validity_seconds": 3600})
    tpl_id = tpl.get("uuid")
    _, offer = A("POST", "/v1/credential-offers", body={"template_id": tpl_id, "claims": {"tier": "gold"}})
    offer_id = offer.get("offer_id")
    _, pr = A("POST", "/v1/presentations/request",
              body={"requested_vct": "ValVCT", "requested_claims": ["tier"], "aud": "rp"})
    pr_uuid = pr.get("uuid")
    _, fw = A("POST", "/v1/trust-frameworks", body={"name": "Val FW", "formats": ["sd_jwt_vc"]})
    fw_slug = fw.get("slug")

    # (name, method, path_template, actual_path, needs_auth)
    checks = [
        ("credential-schemas list", "GET", "/v1/credential-schemas", "/v1/credential-schemas", True),
        ("credential-schema detail", "GET", "/v1/credential-schemas/{uuid}", f"/v1/credential-schemas/{schema_id}", True),
        ("credential-templates list", "GET", "/v1/credential-templates", "/v1/credential-templates", True),
        ("credentials list", "GET", "/v1/credentials", "/v1/credentials", True),
        ("credential-offers list", "GET", "/v1/credential-offers", "/v1/credential-offers", True),
        ("credential-offer detail", "GET", "/v1/credential-offers/{uuid}", f"/v1/credential-offers/{offer_id}", False),
        ("credential-offer reference", "GET", "/v1/credential-offers/{uuid}/offer", f"/v1/credential-offers/{offer_id}/offer", False),
        ("presentation requests list", "GET", "/v1/presentations/requests", "/v1/presentations/requests", True),
        ("presentation request params", "GET", "/v1/presentations/{uuid}/request", f"/v1/presentations/{pr_uuid}/request", False),
        ("presentation public detail", "GET", "/v1/presentations/{uuid}", f"/v1/presentations/{pr_uuid}", False),
        ("verifications list", "GET", "/v1/verifications", "/v1/verifications", True),
        ("trust-frameworks list", "GET", "/v1/trust-frameworks", "/v1/trust-frameworks", True),
        ("trust-framework detail", "GET", "/v1/trust-frameworks/{slug}", f"/v1/trust-frameworks/{fw_slug}", True),
        ("trusted-issuers list", "GET", "/v1/trusted-issuers", "/v1/trusted-issuers", True),
        ("relying-parties list", "GET", "/v1/relying-parties", "/v1/relying-parties", True),
        ("keys list", "GET", "/v1/keys", "/v1/keys", True),
        ("keys impact", "GET", "/v1/keys/impact", "/v1/keys/impact", True),
        ("members list", "GET", "/v1/members", "/v1/members", True),
        # idempotent POSTs
        ("issuer metadata", "GET", "/v1/issuers/{slug}/.well-known/openid-credential-issuer",
         f"/v1/issuers/{slug}/.well-known/openid-credential-issuer", False),
        ("issuer jwks", "GET", "/v1/issuers/{slug}/.well-known/jwt-vc-issuer",
         f"/v1/issuers/{slug}/.well-known/jwt-vc-issuer", False),
        ("nonce", "POST", "/v1/nonce", "/v1/nonce", False),
    ]

    rows, failures = [], 0
    for name, method, tmpl, actual, needs_auth in checks:
        status, body = cli.call(method, actual, token=(key if needs_auth else None),
                                 body=({} if method == "POST" else None))
        verdict, detail = check(name, spec, method, tmpl, status, body)
        rows.append((verdict, name, method, tmpl, detail))
        if verdict == "FAIL":
            failures += 1

    print()
    for verdict, name, method, tmpl, detail in rows:
        print(f"  [{verdict:>4}] {method:6} {tmpl:52} {name:28} {detail}")
    print(f"\n{len(rows)} checked · {sum(1 for r in rows if r[0]=='PASS')} pass · "
          f"{failures} fail · {sum(1 for r in rows if r[0]=='SKIP')} skip")
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8011")
    ap.add_argument("--spec", default=str(ROOT / "openapi.json"))
    args = ap.parse_args()
    raise SystemExit(run(args.base, args.spec))


if __name__ == "__main__":
    main()
