# mintlify-didit-id

Documentation for **Didit ID** — the verifiable-credentials API (OpenID4VCI / OpenID4VP, SD-JWT VC).

Built with [Mintlify](https://mintlify.com). The API reference is generated from
[`openapi.json`](./openapi.json) (the `service-didit-id-v0` `/v1/` surface, 32 paths / 36 operations).

## Structure
- `docs.json` — site config + navigation (Documentation tab + API Reference tab).
- `index.mdx`, `quickstart.mdx` — landing + 5-minute quickstart.
- `concepts/` — verifiable credentials, SD-JWT VC, OpenID4VCI, OpenID4VP, Token Status List, trust frameworks.
- `guides/` — issuance, verification, holder wallet, trust registry, key rotation, multi-tenancy.
- `reference/` — authentication, errors, SDKs.
- `api-reference/` — one page per operation (grouped by spec tag), driven by `openapi.json` frontmatter.

## Regenerate the API reference + nav
```bash
# after updating openapi.json from the backend:
cp ../didit-credentials-service/openapi-credentials.json openapi.json
python3 scripts/build_docs.py        # regenerates api-reference/*.mdx + docs.json
```

## Preview
```bash
npm i -g mint        # or: npx mint dev
mint dev             # http://localhost:3000
mint broken-links    # link check
```
