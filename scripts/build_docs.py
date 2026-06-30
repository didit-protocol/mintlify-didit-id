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
    "Status Lists": ("status", "Status Lists"),
}
TAG_ORDER = list(TAG_DIR.keys())


def slug(method: str, path: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", path.replace("/v1/", "").lower()).strip("-")
    base = base.replace("well-known-", "")
    return f"{base}-{method}".strip("-")


def main() -> None:
    groups: dict[str, list[str]] = {t: [] for t in TAG_ORDER}
    api_dir = ROOT / "api-reference"
    for path, methods in sorted(SPEC["paths"].items()):
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (op.get("tags") or ["Other"])[0]
            if tag not in TAG_DIR:
                continue
            folder, _ = TAG_DIR[tag]
            page = slug(method, path)
            summary = op.get("summary", f"{method.upper()} {path}")
            mdx = (
                "---\n"
                f'title: "{summary}"\n'
                "seo:\n"
                f'  title: "{summary} — Didit ID API"\n'
                f'  description: "{method.upper()} {path} — {summary}. Didit ID verifiable-credentials API '
                '(OpenID4VCI / OpenID4VP, SD-JWT VC)."\n'
                f'openapi: "{method.upper()} {path}"\n'
                "---\n"
            )
            (api_dir / folder).mkdir(parents=True, exist_ok=True)
            (api_dir / folder / f"{page}.mdx").write_text(mdx)
            groups[tag].append(f"api-reference/{folder}/{page}")

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
            "primary": {"type": "button", "label": "Console", "href": "https://business.didit.me"},
        },
        "openapi": ["openapi.json"],
        "navigation": {
            "tabs": [
                {
                    "tab": "Documentation",
                    "groups": [
                        {"group": "Get Started", "pages": ["index", "quickstart"]},
                        {"group": "Concepts", "pages": [
                            "concepts/verifiable-credentials", "concepts/sd-jwt-vc",
                            "concepts/openid4vci", "concepts/openid4vp", "concepts/status-list",
                            "concepts/trust-frameworks"]},
                        {"group": "Guides", "pages": [
                            "guides/issuance", "guides/verification", "guides/holder-wallet",
                            "guides/trust-registry", "guides/key-rotation", "guides/multi-tenancy"]},
                        {"group": "Reference", "pages": ["reference/authentication", "reference/errors", "reference/sdks"]},
                    ],
                },
                {"tab": "API Reference", "groups": api_groups},
            ],
            "global": {"anchors": [
                {"anchor": "Didit Docs", "href": "https://docs.didit.me", "icon": "book-open-cover"},
                {"anchor": "Console", "href": "https://business.didit.me", "icon": "gauge"},
            ]},
        },
        "footer": {"socials": {"x": "https://x.com/getdidit", "github": "https://github.com/didit-protocol",
                               "linkedin": "https://linkedin.com/company/91001155"}},
    }
    (ROOT / "docs.json").write_text(json.dumps(docs, indent=2))
    n = sum(len(v) for v in groups.values())
    print(f"WROTE docs.json + {n} API-reference MDX across {len([g for g in api_groups])} groups")
    for t in TAG_ORDER:
        if groups[t]:
            print(f"  {t}: {len(groups[t])}")


if __name__ == "__main__":
    main()
