#!/usr/bin/env python3
"""Generate the Didit ID docs scaffold from openapi.json:
- one MDX page per API operation (grouped by spec tag) under api-reference/<group>/
- docs.json (Didit-branded theme + navigation: Documentation tab + API Reference tab)

Conceptual MDX (index, quickstart, concepts/*, guides/*, reference/*) are authored separately.
Re-runnable: python scripts/build_docs.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "openapi.json").read_text())

TAG_DIR = {
    "OpenID4VCI Protocol": ("openid4vci", "OpenID4VCI Protocol"),
    "Credentials": ("credentials", "Credentials"),
    "OpenID4VP Verification": ("verification", "OpenID4VP Verification"),
    "Trust Registry": ("trust", "Trust Registry"),
    "Issuer Keys": ("keys", "Issuer Keys"),
    "Webhooks": ("webhooks", "Webhooks"),
    "API Keys": ("api-keys", "API Keys"),
    "Status Lists": ("status", "Status Lists"),
}
TAG_ORDER = list(TAG_DIR.keys())


def slug(method: str, path: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", path.replace("/v1/", "").lower()).strip("-")
    base = base.replace("well-known-", "")
    return f"{base}-{method}".strip("-")


# Short, verb-led sidebar labels keyed by "METHOD /path". The verbose, precise text
# stays as the page title/H1 + description; only the nav gets these.
SIDEBAR_LABELS: dict[str, str] = {
    "POST /v1/credential": "Credential endpoint",
    "GET /v1/credential-offers": "List offers",
    "POST /v1/credential-offers": "Create offer",
    "GET /v1/credential-offers/resolve": "Resolve offer",
    "GET /v1/credential-offers/{uuid}": "Get offer",
    "GET /v1/credential-offers/{uuid}/offer": "Offer document",
    "POST /v1/credential-offers/{uuid}/resend-email": "Resend offer email",
    "GET /v1/credential-schemas": "List schemas",
    "POST /v1/credential-schemas": "Create schema",
    "GET /v1/credential-schemas/{uuid}": "Get schema + versions",
    "PATCH /v1/credential-schemas/{uuid}": "Set schema status",
    "POST /v1/credential-schemas/{uuid}/revoke-credentials": "Revoke schema credentials",
    "POST /v1/credential-schemas/{uuid}/versions": "New schema version",
    "GET /v1/credential-templates": "List templates",
    "POST /v1/credential-templates": "Create template",
    "GET /v1/credentials": "List credentials",
    "POST /v1/credentials/issue": "Issue credential",
    "GET /v1/credentials/{uuid}": "Get credential",
    "POST /v1/credentials/{uuid}/reactivate": "Reactivate credential",
    "POST /v1/credentials/{uuid}/revoke": "Revoke credential",
    "POST /v1/credentials/{uuid}/suspend": "Suspend credential",
    "GET /v1/issuers/{slug}/.well-known/jwt-vc-issuer": "Issuer JWKS",
    "GET /v1/issuers/{slug}/.well-known/openid-credential-issuer": "Issuer metadata",
    "GET /v1/keys": "List signing keys",
    "GET /v1/keys/impact": "Rotation impact",
    "POST /v1/keys/rotate": "Rotate key",
    "POST /v1/nonce": "Issue c_nonce",
    "POST /v1/oauth/token": "Token endpoint",
    "GET /v1/presentations/request": "List requests",
    "POST /v1/presentations/request": "Create request",
    "GET /v1/presentations/{uuid}": "Poll request",
    "GET /v1/presentations/{uuid}/request": "Request parameters",
    "POST /v1/presentations/{uuid}/response": "Submit vp_token",
    "GET /v1/relying-parties": "List relying parties",
    "POST /v1/relying-parties": "Register relying party",
    "PATCH /v1/relying-parties/{uuid}": "Update relying party",
    "DELETE /v1/relying-parties/{uuid}": "Remove relying party",
    "GET /v1/status-lists/{slug}/{uuid}": "Get status list",
    "POST /v1/tenant/bootstrap": "Bootstrap tenant",
    "GET /v1/trust-frameworks": "List frameworks",
    "POST /v1/trust-frameworks": "Create framework",
    "GET /v1/trust-frameworks/{slug}": "Get framework",
    "PATCH /v1/trust-frameworks/{slug}": "Edit framework",
    "DELETE /v1/trust-frameworks/{slug}": "Delete framework",
    "GET /v1/trust-frameworks/{slug}/trust": "Framework trust status",
    "PUT /v1/trust-frameworks/{slug}/trust": "Set framework trust",
    "POST /v1/trust-frameworks/{slug}/issuer-overrides": "Block / unblock issuer",
    "GET /v1/trusted-issuers": "List trusted issuers",
    "POST /v1/trusted-issuers": "Add trusted issuer",
    "PATCH /v1/trusted-issuers/{uuid}": "Enable / disable issuer",
    "DELETE /v1/trusted-issuers/{uuid}": "Remove trusted issuer",
    "POST /v1/trusted-issuers/{uuid}/validate": "Validate issuer",
    "GET /v1/verifications": "List verifications",
    "GET /v1/verifications/{uuid}": "Get verification",
    "GET /v1/webhooks": "List endpoints",
    "POST /v1/webhooks": "Create endpoint",
    "PATCH /v1/webhooks/{uuid}": "Update endpoint",
    "DELETE /v1/webhooks/{uuid}": "Delete endpoint",
    "POST /v1/webhooks/{uuid}/test": "Test endpoint",
    "GET /v1/webhooks/deliveries": "List deliveries",
    "GET /v1/webhook-events": "Event types",
    "GET /v1/api-keys": "List API keys",
    "POST /v1/api-keys": "Create API key",
    "POST /v1/api-keys/{uuid}/rotate": "Rotate API key",
    "DELETE /v1/api-keys/{uuid}": "Delete API key",
}

# Operations in openapi.json that must never get a reference page (kept out of the nav even
# if they reappear in the spec): dev-only helpers, console-only surfaces, route aliases.
EXCLUDE: set[str] = {
    "POST /v1/credential-offers/{uuid}/accept",
    "POST /v1/presentations/{uuid}/demo-present",
    "GET /v1/presentations/requests",
    "POST /v1/presentations/requests",
    "GET /v1/members",
    "POST /v1/members",
    "PATCH /v1/members/{email}",
    "DELETE /v1/members/{email}",
}

# Explicit page order inside a group (listed operations come first, in this order; anything
# else follows sorted by path).
PAGE_ORDER: dict[str, list[str]] = {
    "Trust Registry": [
        "GET /v1/trust-frameworks",
        "POST /v1/trust-frameworks",
        "GET /v1/trust-frameworks/{slug}",
        "PATCH /v1/trust-frameworks/{slug}",
        "DELETE /v1/trust-frameworks/{slug}",
        "GET /v1/trust-frameworks/{slug}/trust",
        "PUT /v1/trust-frameworks/{slug}/trust",
        "POST /v1/trust-frameworks/{slug}/issuer-overrides",
    ],
    "Webhooks": [
        "GET /v1/webhooks",
        "POST /v1/webhooks",
        "PATCH /v1/webhooks/{uuid}",
        "DELETE /v1/webhooks/{uuid}",
        "POST /v1/webhooks/{uuid}/test",
        "GET /v1/webhooks/deliveries",
        "GET /v1/webhook-events",
    ],
    "API Keys": [
        "POST /v1/tenant/bootstrap",
        "GET /v1/api-keys",
        "POST /v1/api-keys",
        "POST /v1/api-keys/{uuid}/rotate",
        "DELETE /v1/api-keys/{uuid}",
    ],
}

CONSOLE_URL = "https://console-idv0.staging.didit.me/"



def short_label(method: str, path: str, summary: str) -> str:
    """Concise nav label. Prefer the explicit map; else derive from the summary by dropping
    any parenthetical / trailing clause and truncating."""
    key = f"{method.upper()} {path}"
    if key in SIDEBAR_LABELS:
        return SIDEBAR_LABELS[key]
    label = re.split(r"\s*[(—:]", summary, maxsplit=1)[0].rstrip(". ").strip()
    return label if len(label) <= 28 else label[:27].rstrip() + "…"


def main() -> None:
    groups: dict[str, list[str]] = {t: [] for t in TAG_ORDER}
    api_dir = ROOT / "api-reference"
    for path, methods in sorted(SPEC["paths"].items()):
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if f"{method.upper()} {path}" in EXCLUDE:
                continue
            tag = (op.get("tags") or ["Other"])[0]
            if tag not in TAG_DIR:
                continue
            folder, _ = TAG_DIR[tag]
            page = slug(method, path)
            summary = op.get("summary", f"{method.upper()} {path}")
            # Short, verb-led nav label (the full summary stays as the page H1/title).
            sidebar_title = short_label(method, path, summary)
            mdx = (
                "---\n"
                f'title: "{summary}"\n'
                f'sidebarTitle: "{sidebar_title}"\n'
                "seo:\n"
                f'  title: "{summary} — Didit ID API"\n'
                f'  description: "{method.upper()} {path} — {summary}. Didit ID verifiable-credentials API '
                '(OpenID4VCI / OpenID4VP, SD-JWT VC)."\n'
                f'openapi: "{method.upper()} {path}"\n'
                "---\n"
            )
            (api_dir / folder).mkdir(parents=True, exist_ok=True)
            target = api_dir / folder / f"{page}.mdx"
            # Keep hand-written body content (anything after the frontmatter) across rebuilds.
            if target.exists():
                existing = target.read_text()
                parts = existing.split("---\n", 2)
                if len(parts) == 3 and parts[2].strip():
                    mdx += parts[2] if parts[2].startswith("\n") else "\n" + parts[2]
            target.write_text(mdx)
            groups[tag].append(f"api-reference/{folder}/{page}")

    for tag, order in PAGE_ORDER.items():
        wanted = [f"api-reference/{TAG_DIR[tag][0]}/{slug(k.split(' ', 1)[0].lower(), k.split(' ', 1)[1])}" for k in order]
        groups[tag] = [p for p in wanted if p in groups[tag]] + [p for p in groups[tag] if p not in wanted]

    # ── docs.json ────────────────────────────────────────────────────────────
    api_groups = [{"group": TAG_DIR[t][1], "pages": groups[t]} for t in TAG_ORDER if groups[t]]
    docs = {
        "$schema": "https://mintlify.com/docs.json",
        "theme": "mint",
        "name": "Didit ID",
        "description": "Issue and verify verifiable credentials — OpenID4VCI / OpenID4VP, SD-JWT VC.",
        "colors": {"primary": "#2567FF", "light": "#90B1FF", "dark": "#1B4FE0"},
        "fonts": {"heading": {"family": "Inter", "weight": 500}, "body": {"family": "Inter", "weight": 400}},
        "favicon": "/favicon.ico",
        "logo": {"light": "/logo/didit.svg", "dark": "/logo/didit-white.svg", "href": "https://didit.me"},
        "navbar": {
            "links": [{"label": "Support", "href": "https://wa.me/+19544659728", "icon": "comment-dots"}],
            "primary": {"type": "button", "label": "Console", "href": CONSOLE_URL},
        },
        "openapi": ["openapi.json"],
        "contextual": {"options": ["copy", "view", "chatgpt", "claude", "perplexity", "mcp", "cursor", "vscode"]},
        "navigation": {
            "tabs": [
                {
                    "tab": "Documentation",
                    "groups": [
                        {"group": "Learn the basics", "pages": [
                            "learn/index", "learn/what-is-a-verifiable-credential",
                            "learn/issuer-holder-verifier", "learn/wallets-and-presenting",
                            "learn/trust-and-trusted-issuers", "learn/what-didit-id-does",
                            "learn/what-you-can-build", "learn/glossary"]},
                        {"group": "Get Started", "pages": ["index", "quickstart", "demo", "integration-prompt"]},
                        {"group": "Concepts", "pages": [
                            "concepts/verifiable-credentials", "concepts/sd-jwt-vc",
                            "concepts/openid4vci", "concepts/openid4vp", "concepts/status-list",
                            "concepts/trust-frameworks"]},
                        {"group": "Guides", "pages": [
                            "guides/programmatic-access", "guides/integrate",
                            "guides/issuance", "guides/issue-via-email",
                            "guides/verification", "guides/relying-party", "guides/holder-wallet",
                            "guides/trust-registry", "guides/key-rotation", "guides/multi-tenancy"]},
                        {"group": "Wallet", "pages": [
                            "wallet/index", "wallet/quickstart", "wallet/architecture", "wallet/security"]},
                        {"group": "Reference", "pages": ["reference/authentication", "reference/errors", "reference/sdks"]},
                    ],
                },
                {"tab": "API Reference", "groups": api_groups},
            ],
            "global": {"anchors": [
                {"anchor": "Didit Docs", "href": "https://docs.didit.me", "icon": "book-open-cover"},
                {"anchor": "Console", "href": CONSOLE_URL, "icon": "gauge"},
            ]},
        },
        "footer": {"socials": {"x": "https://x.com/getdidit", "linkedin": "https://linkedin.com/company/91001155"}},
    }
    (ROOT / "docs.json").write_text(json.dumps(docs, indent=2) + "\n")
    n = sum(len(v) for v in groups.values())
    print(f"WROTE docs.json + {n} API-reference MDX across {len([g for g in api_groups])} groups")
    for t in TAG_ORDER:
        if groups[t]:
            print(f"  {t}: {len(groups[t])}")


if __name__ == "__main__":
    main()
