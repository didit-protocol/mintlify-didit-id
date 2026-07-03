#!/usr/bin/env python3
"""Merge scripts/captured-examples.json into openapi.json so the Mintlify playground renders
REAL request/response bodies (not `<string>` placeholders) for every endpoint.

Pipeline position (run AFTER enrich, BEFORE build):

    python scripts/enrich_openapi.py      # authored field schemas + prose from docs-schemas/*
    python scripts/inject_examples.py     # <-- this: real examples + example-inferred schemas
    python scripts/build_docs.py          # MDX pages + docs.json navigation

For every captured operation this:
  1. ensures the operation exists in openapi.json (creates the 6 newer schema/framework/issuer
     endpoints if the base spec predates them), tagged + path-param'd so build_docs renders it;
  2. sets `content.application/json.example` on the request body and on EACH response code;
  3. replaces STUB or STRUCTURALLY-WRONG response schemas (empty object, `{items:[string]}`,
     bare `[string]`, or an object-schema where the real body is a bare array) with a schema
     INFERRED from the real example — carrying authored field descriptions across from
     docs-schemas/* where the field names match, so prose is preserved;
  4. adds the documented error responses (401/403/404/409/422 as captured) with example bodies.

Good, structurally-correct authored schemas are kept — only the example is added to them.

Run: python scripts/inject_examples.py [--spec openapi.json] [--examples scripts/captured-examples.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Longest-prefix → tag, for endpoints missing from the base spec.
TAG_PREFIXES = [
    ("/v1/credential-offers", "OpenID4VCI Protocol"),
    ("/v1/credential-schemas", "Credentials"),
    ("/v1/credential-templates", "Credentials"),
    ("/v1/credentials", "Credentials"),
    ("/v1/credential", "OpenID4VCI Protocol"),
    ("/v1/presentations", "OpenID4VP Verification"),
    ("/v1/verifications", "OpenID4VP Verification"),
    ("/v1/trust-frameworks", "Trust Registry"),
    ("/v1/trusted-issuers", "Trust Registry"),
    ("/v1/relying-parties", "Trust Registry"),
    ("/v1/keys", "Issuer Keys"),
    ("/v1/status-lists", "Status Lists"),
    ("/v1/oauth", "OpenID4VCI Protocol"),
    ("/v1/nonce", "OpenID4VCI Protocol"),
    ("/v1/issuers", "OpenID4VCI Protocol"),
    ("/v1/members", "Other"),
    ("/v1/tenant", "Other"),
]

ERROR_DESCRIPTIONS = {
    "400": "Bad request — the request body or parameters failed validation.",
    "401": "Unauthorized — a valid tenant API key (Bearer) was not supplied.",
    "403": "Forbidden — the caller lacks the required privilege, or the resource is immutable.",
    "404": "Not found — no such resource for this tenant (cross-tenant reads return 404, not 403).",
    "409": "Conflict — the requested lifecycle transition is not allowed from the current state.",
    "422": "Unprocessable — the credential presentation could not be verified.",
    "429": "Too many requests — a per-resource rate limit was hit.",
}

PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


# ──────────────────────────────────────────────────────────────────────────────
# schema inference + authored-description merge
# ──────────────────────────────────────────────────────────────────────────────
def infer(example, descmap=None):
    """Infer a JSON-Schema (3.1) node from a real example value, recursively."""
    if isinstance(example, dict):
        node = {"type": "object", "properties": {}}
        for k, v in example.items():
            child = infer(v, descmap)
            meta = (descmap or {}).get(k)
            if meta:
                for mk in ("description", "format", "enum"):
                    if mk in meta and mk not in child:
                        child[mk] = meta[mk]
            node["properties"][k] = child
        return node
    if isinstance(example, list):
        if example:
            return {"type": "array", "items": infer(example[0], descmap)}
        return {"type": "array", "items": {"type": "object", "properties": {}}}
    if isinstance(example, bool):
        return {"type": "boolean", "example": example}
    if isinstance(example, int):
        return {"type": "integer", "example": example}
    if isinstance(example, float):
        return {"type": "number", "example": example}
    if example is None:
        return {"type": ["string", "null"], "example": None}
    return {"type": "string", "example": example}


def collect_descriptions(authored_op) -> dict:
    """Flatten every named field's {description, format, enum} out of an authored docs-schema op
    (tolerant of the malformed `items: {name: def}` envelope). First non-empty wins per name."""
    out: dict[str, dict] = {}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict) and isinstance(v.get("description"), str) and k not in out:
                    meta = {"description": v["description"]}
                    if isinstance(v.get("format"), str):
                        meta["format"] = v["format"]
                    if isinstance(v.get("enum"), list):
                        meta["enum"] = v["enum"]
                    out[k] = meta
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(authored_op or {})
    return out


def augment(schema, example, descmap):
    """Fill an otherwise-good authored schema with any REAL field present in the example but
    absent from the schema (recursively). Preserves authored prose; only adds what's missing."""
    if not isinstance(schema, dict):
        return
    t = schema.get("type")
    if t == "object" and isinstance(example, dict):
        props = schema.setdefault("properties", {})
        for k, v in example.items():
            if k not in props:
                child = infer(v, descmap)
                meta = (descmap or {}).get(k)
                if meta:
                    for mk in ("description", "format", "enum"):
                        if mk in meta and mk not in child:
                            child[mk] = meta[mk]
                props[k] = child
            else:
                augment(props[k], v, descmap)
    elif t == "array" and isinstance(example, list) and example:
        augment(schema.get("items", {}), example[0], descmap)


def is_stub_or_mismatched(schema, example) -> bool:
    """True when the schema is a placeholder OR its top-level shape contradicts the real body."""
    if not isinstance(schema, dict) or not schema:
        return True
    t = schema.get("type")
    # top-level type must agree with the example's JSON type
    if isinstance(example, list) and t != "array":
        return True
    if isinstance(example, dict) and t not in ("object", None):
        return True
    # empty object
    if t == "object" and not schema.get("properties"):
        return True
    # {items:[string]} wrapper stub
    props = schema.get("properties", {})
    if set(props) == {"items"}:
        it = props["items"]
        if it.get("type") == "array" and it.get("items", {}).get("type") == "string" \
                and "properties" not in it.get("items", {}):
            return True
    # bare [string]
    if t == "array" and schema.get("items", {}).get("type") == "string" \
            and "properties" not in schema.get("items", {}):
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# path helpers
# ──────────────────────────────────────────────────────────────────────────────
def split_key(key: str):
    method, path = key.split(" ", 1)
    return method.lower(), path


def tag_for(path: str, spec) -> str:
    best, best_len = None, -1
    for p, ops in spec["paths"].items():
        if path.startswith(p.rstrip("{}/")) and len(p) > best_len:
            tags = None
            for m, op in ops.items():
                if isinstance(op, dict) and op.get("tags"):
                    tags = op["tags"][0]
            if tags:
                best, best_len = tags, len(p)
    if best:
        return best
    for prefix, t in TAG_PREFIXES:
        if path.startswith(prefix):
            return t
    return "Other"


def op_id(method: str, path: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", " ", path.replace("/v1/", "")).title().replace(" ", "")
    return method.lower() + base


def ensure_op(spec, method, path, *, tag, summary, description, authored, params_desc):
    node = spec["paths"].setdefault(path, {})
    op = node.get(method)
    created = op is None
    if created:
        op = node[method] = {}
    op.setdefault("tags", [tag])
    op.setdefault("operationId", op_id(method, path))
    if summary and "summary" not in op:
        op["summary"] = summary.rstrip(".")
    if description:
        op["description"] = description
    op.setdefault("security", [{"bearerAuth": []}])
    op.setdefault("responses", {})
    # path params
    path_params = PATH_PARAM_RE.findall(path)
    if path_params:
        existing = {p["name"]: p for p in op.get("parameters", []) if isinstance(p, dict)}
        params = []
        for pp in path_params:
            desc = params_desc.get(pp) or f"`{pp}` path parameter."
            fmt = {"format": "uuid"} if pp == "uuid" else {}
            params.append(existing.get(pp, {
                "name": pp, "in": "path", "required": True,
                "description": desc, "schema": {"type": "string", **fmt},
            }))
        # keep any non-path (query/header) params already present
        for name, p in existing.items():
            if name not in path_params and p.get("in") in ("query", "header"):
                params.append(p)
        op["parameters"] = params
    return op, created


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=str(ROOT / "openapi.json"))
    ap.add_argument("--examples", default=str(ROOT / "scripts" / "captured-examples.json"))
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    spec["openapi"] = "3.1.0"
    examples = json.loads(Path(args.examples).read_text())

    # authored docs-schemas (for endpoint descriptions + field prose + param descriptions)
    authored = {}
    for f in sorted(glob.glob(str(ROOT / "docs-schemas" / "*.json"))):
        authored.update(json.loads(Path(f).read_text()))

    created_paths, filled_examples, fixed_schemas, error_added = [], 0, 0, 0

    for key, cap in examples.items():
        method, path = split_key(key)
        adoc = authored.get(key, {})
        descmap = collect_descriptions(adoc)
        params_desc = {p.get("name"): p.get("description", "")
                       for p in (adoc.get("params") or []) if isinstance(p, dict)}

        op, created = ensure_op(
            spec, method, path,
            tag=tag_for(path, spec),
            summary=cap.get("summary"),
            description=(adoc.get("description") or cap.get("summary")),
            authored=adoc, params_desc=params_desc,
        )
        if created:
            created_paths.append(f"{method.upper()} {path}")

        # ── request body example ──────────────────────────────────────────────
        if cap.get("request") is not None and method in ("post", "put", "patch"):
            rb = op.setdefault("requestBody", {"required": True, "content": {}})
            content = rb.setdefault("content", {}).setdefault("application/json", {})
            cur = content.get("schema")
            req_desc = collect_descriptions(adoc.get("request"))
            if is_stub_or_mismatched(cur, cap["request"]):
                content["schema"] = infer(cap["request"], req_desc or descmap)
                fixed_schemas += 1
            else:
                augment(cur, cap["request"], req_desc or descmap)
            content["example"] = cap["request"]
            filled_examples += 1

        # ── success responses ────────────────────────────────────────────────
        for code, body in cap.get("responses", {}).items():
            resp = op["responses"].setdefault(code, {})
            resp.setdefault("description",
                            (adoc.get("responses", {}).get(code, {}) or {}).get("description")
                            or "Successful response.")
            if not body and body != []:
                # 204-style empty body — no content
                resp.pop("content", None)
                continue
            content = resp.setdefault("content", {}).setdefault("application/json", {})
            cur = content.get("schema")
            resp_desc = collect_descriptions((adoc.get("responses", {}) or {}).get(code))
            if is_stub_or_mismatched(cur, body):
                content["schema"] = infer(body, resp_desc or descmap)
                fixed_schemas += 1
            else:
                augment(cur, body, resp_desc or descmap)
            content["example"] = body
            filled_examples += 1

        # ── prune stale empty 2xx (drf-spectacular seeded a bare 200 on create endpoints
        #    that really answer 201; drop any 2xx we didn't capture that has no body) ────────
        captured_codes = set(cap.get("responses", {}).keys())
        for code in list(op.get("responses", {})):
            if code in captured_codes or code == "204":
                continue
            if code.startswith("2") and not op["responses"][code].get("content"):
                del op["responses"][code]

        # ── error responses ──────────────────────────────────────────────────
        for err in cap.get("errors", []):
            code = str(err["status"])
            body = err.get("body")
            resp = op["responses"].setdefault(code, {})
            note = err.get("note")
            base_desc = ERROR_DESCRIPTIONS.get(code, "Error.")
            resp["description"] = f"{base_desc}" + (f" (Example: {note}.)" if note else "")
            if body is not None:
                content = resp.setdefault("content", {}).setdefault("application/json", {})
                if is_stub_or_mismatched(content.get("schema"), body):
                    content["schema"] = infer(body)
                content["example"] = body
                error_added += 1

    Path(args.spec).write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Injected examples into {len(examples)} operations.")
    print(f"  examples set:      {filled_examples}")
    print(f"  schemas fixed:     {fixed_schemas}")
    print(f"  error bodies added:{error_added}")
    if created_paths:
        print(f"  NEW paths created ({len(created_paths)}):")
        for p in created_paths:
            print("   +", p)


if __name__ == "__main__":
    main()
