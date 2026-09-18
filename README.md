# mintlify-didit-id

Documentation for **Didit ID** — the verifiable-credentials API (OpenID4VCI / OpenID4VP, SD-JWT VC).

Built with [Mintlify](https://mintlify.com). The API reference is generated from
[`openapi.json`](./openapi.json) (the product-facing `/v1/` surface of `didit-credentials-service`: 49 paths / 65 operations; dev-only helpers, console-only team management, and route aliases are excluded on purpose, see `EXCLUDE` in `scripts/build_docs.py`).

## Structure
- `docs.json` — site config + navigation (Documentation tab + API Reference tab).
- `index.mdx`, `quickstart.mdx` — landing + 5-minute quickstart.
- `concepts/` — verifiable credentials, SD-JWT VC, OpenID4VCI, OpenID4VP, Token Status List, trust frameworks.
- `guides/` — issuance, verification, holder wallet, trust registry, key rotation, multi-tenancy.
- `reference/` — authentication, errors, SDKs.
- `api-reference/` — one page per operation (grouped by spec tag), driven by `openapi.json` frontmatter.

## Regenerate the API reference + nav
```bash
# see AGENTS.md for the full enrich -> inject -> build pipeline
python3 scripts/build_docs.py        # regenerates api-reference/*.mdx + docs.json
```

## Preview
```bash
npm i -g mint        # or: npx mint dev
mint dev             # http://localhost:3000
mint broken-links    # link check
```
