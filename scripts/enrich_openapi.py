#!/usr/bin/env python3
"""Enrich openapi.json with full per-field schemas so Mintlify renders complete endpoint docs.

Loads docs-schemas/*.json (authored per tag-group, possibly with slightly varying conventions)
and injects, for every operation: parameters, requestBody schema, response schemas — recursively
expanding the authored field format into JSON Schema:

  fielddef = {"type": "...", "description": "...", "example": ..., "enum": [...],
              "format": "...", "nullable": bool,
              "fields": { name: fielddef }     # when type == object
              "items":  fielddef | {"type":"object","fields":{...}}   # when type == array }

Tolerant of: params as list[dict] / dict[name->def] / list[str]; responses fields nested arbitrarily.
Run: python scripts/enrich_openapi.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "openapi.json"
SCALARS = ("string", "integer", "number", "boolean")


def _required_of(fields: dict, explicit=None) -> list:
    """OpenAPI `required` is a parent-level array of child names — collect from children
    flagged `required: true` plus any explicit list. (Never a boolean on the child.)"""
    out = list(explicit) if isinstance(explicit, list) else []
    for name, v in (fields or {}).items():
        if isinstance(v, dict) and v.get("required") is True:
            out.append(name)
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


def to_schema(fd) -> dict:
    """Recursively convert an authored field definition into a clean JSON Schema node (3.1)."""
    if not isinstance(fd, dict):
        return {"type": "string", "description": str(fd)}
    t = fd.get("type", "object" if ("fields" in fd or "properties" in fd) else ("array" if "items" in fd else "string"))
    node: dict = {"type": t}
    for k in ("description", "example", "enum", "format", "default"):
        if k not in fd:
            continue
        v = fd[k]
        if k in ("description", "format") and not isinstance(v, str):
            continue
        if k == "enum" and not isinstance(v, list):
            continue
        node[k] = v
    # nullable -> 3.1 union type; (avoid the invalid 3.0 `nullable` sibling)
    if fd.get("nullable") and isinstance(t, str):
        node["type"] = [t, "null"]
    if t == "object":
        flds = fd.get("fields") or fd.get("properties") or {}
        node["properties"] = {name: to_schema(v) for name, v in flds.items()}
        req = _required_of(flds, fd.get("required") if isinstance(fd.get("required"), list) else None)
        if req:
            node["required"] = req
    elif t == "array":
        node["items"] = to_schema(fd.get("items", {"type": "string"}))
    return node


def obj_schema(fields: dict, required=None) -> dict:
    s = {"type": "object", "properties": {name: to_schema(v) for name, v in (fields or {}).items()}}
    req = _required_of(fields, required if isinstance(required, list) else None)
    if req:
        s["required"] = req
    return s


def normalize_params(params) -> list:
    out = []
    if isinstance(params, dict):
        items = params.items()
    elif isinstance(params, list):
        items = []
        for p in params:
            if isinstance(p, dict):
                items.append((p.get("name"), p))
            else:
                items.append((p, {"in": "path"}))
    else:
        return out
    for name, p in items:
        if not name:
            continue
        p = p if isinstance(p, dict) else {}
        loc = p.get("in", "path")
        out.append({
            "name": name, "in": loc,
            "required": p.get("required", loc == "path"),
            "description": p.get("description", ""),
            "schema": {"type": p.get("type", "string"), **({"format": p["format"]} if "format" in p else {})},
        })
    return out


import re

PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def main() -> None:
    spec = json.loads(SPEC.read_text())
    spec["openapi"] = "3.1.0"  # Mintlify's native OpenAPI version
    # Prune inherited drf-spectacular cruft: inline schemas only (no $refs), one auth scheme.
    comps = spec.setdefault("components", {})
    comps["schemas"] = {}
    comps["securitySchemes"] = {"bearerAuth": {"type": "http", "scheme": "bearer", "description": "Tenant API key"}}
    merged: dict[str, dict] = {}
    for f in sorted(glob.glob(str(ROOT / "docs-schemas" / "*.json"))):
        merged.update(json.loads(Path(f).read_text()))

    injected, missing = 0, []
    for path, methods in spec["paths"].items():
        path_params = PATH_PARAM_RE.findall(path)
        for method, op in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            # normalize op-level security to the single bearer scheme (drop inherited DiditAuthentication)
            if "security" in op and op["security"]:
                op["security"] = [{"bearerAuth": []}]
            doc = merged.get(f"{method.upper()} {path}")
            if not doc:
                missing.append(f"{method.upper()} {path}")
            else:
                if doc.get("description"):
                    op["description"] = doc["description"]
            authored = {p["name"]: p for p in normalize_params((doc or {}).get("params"))}
            params = []
            # exactly the path-template params (OpenAPI requires each), with authored descriptions
            for pp in path_params:
                a = authored.get(pp, {})
                params.append({
                    "name": pp, "in": "path", "required": True,
                    "description": a.get("description", f"`{pp}` path parameter."),
                    "schema": a.get("schema", {"type": "string"}),
                })
            # keep only legit query/header params (drop spurious `in:path` params not in the path)
            for name, a in authored.items():
                if name not in path_params and a.get("in") in ("query", "header"):
                    params.append(a)
            if params:
                op["parameters"] = params
            if not doc:
                continue
            if doc.get("request") and method in ("post", "put", "patch"):
                req = doc["request"]
                fields = req.get("fields") or req.get("properties") or {}
                op["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": obj_schema(fields, req.get("required"))}},
                }
            if doc.get("responses"):
                op.setdefault("responses", {})
                for code, r in doc["responses"].items():
                    if not isinstance(r, dict):
                        continue
                    fields = r.get("fields") or r.get("properties") or {}
                    op["responses"][str(code)] = {
                        "description": r.get("description", "OK"),
                        "content": {"application/json": {"schema": obj_schema(fields, r.get("required"))}},
                    }
            injected += 1

    SPEC.write_text(json.dumps(spec, indent=2))
    print(f"Enriched {injected} operations.")
    if missing:
        print(f"MISSING ({len(missing)}):")
        for m in missing:
            print("  ", m)


if __name__ == "__main__":
    main()
