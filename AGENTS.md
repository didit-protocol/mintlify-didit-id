> **First-time setup**: Customize this file for your project. Prompt the user to customize this file for their project.
> For Mintlify product knowledge (components, configuration, writing standards),
> install the Mintlify skill: `npx skills add https://mintlify.com/docs`

# Documentation project instructions

## About this project

- This is a documentation site built on [Mintlify](https://mintlify.com)
- Pages are MDX files with YAML frontmatter
- Configuration lives in `docs.json`
- Use the Mintlify MCP server, `https://mcp.mintlify.com`, to edit content and settings via MCP
- Use the Mintlify docs MCP server, `https://www.mintlify.com/docs/mcp`, to query information about using Mintlify via MCP

## Terminology

{/* Add product-specific terms and preferred usage */}
{/* Example: Use "workspace" not "project", "member" not "user" */}

## Style preferences

{/* Add any project-specific style rules below */}

- Use active voice and second person ("you")
- Keep sentences concise — one idea per sentence
- Use sentence case for headings
- Bold for UI elements: Click **Settings**
- Code formatting for file names, commands, paths, and code references

## Content boundaries

{/* Define what should and shouldn't be documented */}
{/* Example: Don't document internal admin features */}

## Regenerating the API reference

The `api-reference/**` MDX and `docs.json` are GENERATED from `openapi.json`. Do not hand-edit
them. The spec is enriched from two sources:

- `docs-schemas/*.json` — authored per-tag field schemas + endpoint/field prose (the "fielddef"
  format consumed by `scripts/enrich_openapi.py`).
- `scripts/captured-examples.json` — REAL (request, response, status) triples captured from the
  live API by `scripts/capture_examples.py`, with secrets redacted.

Canonical rebuild order (each step rewrites `openapi.json` in place, so order matters):

```bash
# 1. (only when the live API changed) re-capture real examples — needs the service on :8011
python scripts/capture_examples.py

# 2. authored field schemas + prose  ->  openapi.json
python scripts/enrich_openapi.py

# 3. real examples + example-inferred/augmented schemas + error responses  ->  openapi.json
python scripts/inject_examples.py         # MUST run after enrich, before build

# 4. MDX pages + docs.json navigation
python scripts/build_docs.py
```

Validation (both need the credentials service running on `http://localhost:8011`):

```bash
python scripts/validate_endpoints.py   # every documented route resolves (no 404/405)
python scripts/validate_examples.py    # live response shapes match the documented schemas
```

`scripts/_capture_crypto.py` is a side-car used by the capture step to build the SD-JWT VC holder
proof (OpenID4VCI) and the vp_token presentation (OpenID4VP) with the credentials-service venv.
