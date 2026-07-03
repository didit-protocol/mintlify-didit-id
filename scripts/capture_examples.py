#!/usr/bin/env python3
"""Drive the LIVE Didit ID (credentials) API end-to-end and record a real
(request, response, status) triple for every /v1 endpoint.

Output: scripts/captured-examples.json, keyed by "METHOD /v1/path" (the OpenAPI path template,
NOT the filled path). Each entry:

    {
      "source": "captured-live" | "authored",
      "summary": "...",                       # short human note
      "request": {...} | null,                # example request body (POST/PUT/PATCH)
      "query": {"tenant": "...", ...} | null, # example query params, when relevant
      "responses": {"200": {...body...}},     # one example body per success status
      "errors": [{"status": 401, "body": {...}, "note": "no bearer"}, ...]
    }

Secrets are REDACTED to "<redacted>" (api keys, bearer/access/refresh/id tokens,
pre-authorized codes, tx codes, c_nonce / nonce capabilities) — the shape is preserved.

The SD-JWT holder proof (OpenID4VCI) and the vp_token presentation (OpenID4VP) are produced by
scripts/_capture_crypto.py running under the credentials-service virtualenv (see that file).

Usage:
    python scripts/capture_examples.py \
        [--base http://localhost:8011] \
        [--venv <path to credentials-service .venv/bin/python>] \
        [--out scripts/captured-examples.json]
"""
from __future__ import annotations

import argparse
import json
import random
import string
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = Path.home() / "Documents/projects_v2/didit/didit-credentials-service/.venv/bin/python"
PRE_AUTH_GRANT = "urn:ietf:params:oauth:grant-type:pre-authorized_code"

# Field names whose VALUES are secrets / live capabilities — redact value, keep the key.
# NOTE: "credentials" is deliberately NOT here — `dcql.credentials` is the (non-secret) DCQL
# query, and the only real secret under that name, POST /v1/credential's
# `credentials:[{credential: <jwt>}]`, is already covered by the inner "credential" key.
REDACT_KEYS = {
    "api_key", "access_token", "refresh_token", "id_token", "token",
    "pre_authorized_code", "pre-authorized_code", "tx_code",
    "c_nonce", "nonce", "authorization", "proof", "jwt", "vp_token",
    "credential", "sd_jwt",
}
REDACTED = "<redacted>"


# ──────────────────────────────────────────────────────────────────────────────
# HTTP + redaction
# ──────────────────────────────────────────────────────────────────────────────
class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, *, body=None, token=None, query=None):
        """Return (status, parsed_body). `body` dict -> JSON; token -> Bearer header."""
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, _parse(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, _parse(e.read())
        except Exception as e:  # noqa: BLE001
            return -1, {"_transport_error": str(e)}


def _parse(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return raw.decode("utf-8", "replace")


def redact(value):
    """Recursively replace secret STRING values with '<redacted>' while keeping structure.
    Long JWT-ish blobs (credential/vp_token/proof) are also redacted — they are throwaway
    but noisy, and the shape is what documents the field. Booleans/numbers under a secret key
    (e.g. a pass/fail `checks.nonce`) are NOT secrets and are kept verbatim."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.lower() in REDACT_KEYS:
                out[k] = _redact_secret(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and len(value) > 180:
        # A long non-secret blob (e.g. the status-list bitstring) — keep it readable in docs.
        return value[:80] + "…(truncated)"
    return value


def _redact_secret(v):
    """A secret is always a string token; keep booleans/numbers/None and recurse containers."""
    if isinstance(v, str):
        return REDACTED
    if isinstance(v, dict):
        return {k: _redact_secret(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact_secret(x) for x in v]
    return v


# ──────────────────────────────────────────────────────────────────────────────
# crypto side-car
# ──────────────────────────────────────────────────────────────────────────────
class Crypto:
    def __init__(self, venv: Path):
        self.venv = str(venv)
        self.helper = str(ROOT / "scripts" / "_capture_crypto.py")

    def _run(self, job: dict) -> dict:
        p = subprocess.run(
            [self.venv, self.helper],
            input=json.dumps(job).encode(),
            capture_output=True,
            timeout=120,
        )
        if p.returncode != 0:
            raise RuntimeError(f"crypto helper failed: {p.stderr.decode()[-800:]}")
        # helper may emit warnings on stderr; the payload is the last stdout line
        line = p.stdout.decode().strip().splitlines()[-1]
        return json.loads(line)

    def keygen(self, count=1):
        return self._run({"cmd": "keygen", "count": count})["keys"]

    def proof(self, priv, audience, nonce):
        return self._run({"cmd": "proof", "priv": priv, "audience": audience, "nonce": nonce})["proof"]

    def present(self, priv, issuance, disclose, nonce, aud):
        return self._run({
            "cmd": "present", "priv": priv, "issuance": issuance,
            "disclose": disclose, "nonce": nonce, "aud": aud,
        })["vp_token"]


# ──────────────────────────────────────────────────────────────────────────────
# capture bookkeeping
# ──────────────────────────────────────────────────────────────────────────────
class Capture:
    def __init__(self):
        self.data: dict[str, dict] = {}
        self.warnings: list[str] = []

    def record(self, key, *, request=None, query=None, status=None, body=None,
               summary=None, source="captured-live"):
        entry = self.data.setdefault(key, {"source": source, "responses": {}, "errors": []})
        if summary:
            entry["summary"] = summary
        if request is not None:
            entry["request"] = redact(request)
        if query is not None:
            entry["query"] = redact(query)
        if status is not None and body is not None:
            entry["responses"][str(status)] = redact(body)
        return entry

    def error(self, key, status, body, note):
        entry = self.data.setdefault(key, {"source": "captured-live", "responses": {}, "errors": []})
        # de-dupe by (status, note)
        for e in entry["errors"]:
            if e["status"] == status and e["note"] == note:
                return
        entry["errors"].append({"status": status, "body": redact(body), "note": note})

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  ! {msg}", file=sys.stderr)


def rand(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def status_uri_from_sdjwt(sd_jwt: str):
    """Pull the Token-Status-List URI out of an issued SD-JWT's payload (status.status_list.uri)."""
    import base64
    try:
        payload_b64 = sd_jwt.split("~", 1)[0].split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
        return payload.get("status", {}).get("status_list", {}).get("uri")
    except Exception:  # noqa: BLE001
        return None


# ──────────────────────────────────────────────────────────────────────────────
# tenant bootstrap
# ──────────────────────────────────────────────────────────────────────────────
def bootstrap_tenant(cli: Client, cap: Capture | None = None, *, label="docs-capture"):
    """register -> dev/otp -> verify-email -> tenant/bootstrap. Returns (api_key, slug, email)."""
    email = f"{label}-{rand()}@diditcapture.dev"
    pw = "Test-Passw0rd-" + rand(4)
    s, _ = cli.call("POST", "/auth/v2/programmatic/register/", body={"email": email, "password": pw})
    if s != 201:
        raise RuntimeError(f"register failed {s} for {email}")
    s, otp = cli.call("GET", "/v1/dev/otp", query={"email": email})
    if s != 200 or not isinstance(otp, dict) or "code" not in otp:
        raise RuntimeError(f"dev/otp failed {s}: {otp}")
    s, verified = cli.call("POST", "/auth/v2/programmatic/verify-email/",
                           body={"email": email, "code": otp["code"]})
    if s != 200:
        raise RuntimeError(f"verify-email failed {s}: {verified}")
    user_token = verified["access_token"]
    s, boot = cli.call("POST", "/v1/tenant/bootstrap", body={}, token=user_token)
    if s != 200:
        raise RuntimeError(f"tenant/bootstrap failed {s}: {boot}")
    if cap is not None:
        cap.record("POST /v1/tenant/bootstrap", request={}, status=s, body=boot,
                   summary="Exchange a user access token for a tenant API key (first call seeds "
                           "the tenant's signing key + demo schemas).")
    return boot["api_key"], boot["tenant"]["slug"], email


# ──────────────────────────────────────────────────────────────────────────────
# main walk
# ──────────────────────────────────────────────────────────────────────────────
def run(base: str, venv: Path, out: Path):
    cli = Client(base)
    crypto = Crypto(venv)
    cap = Capture()

    print("Bootstrapping primary tenant …")
    key, slug, email = bootstrap_tenant(cli, cap, label="docs-capture")
    issuer_id = f"{base.rstrip('/')}/v1/issuers/{slug}"
    # A second tenant supplies a REAL external issuer identifier (with a reachable JWKS) to
    # register as a trusted issuer — the primary tenant's own iss is auto-trusted and would
    # collide on the (tenant, iss) unique constraint.
    _keyB, slugB, _ = bootstrap_tenant(cli, label="docs-external-issuer")
    external_iss = f"{base.rstrip('/')}/v1/issuers/{slugB}"

    # Pre-generate holder keys (1 pipenv spawn) for the presentation + OpenID4VCI proof flows.
    hk_present, hk_openid, hk_offer = crypto.keygen(count=3)

    def A(method, path, key_="__primary__", **kw):
        """Authed call with the primary tenant key unless overridden."""
        tok = key if key_ == "__primary__" else key_
        return cli.call(method, path, token=tok, **kw)

    # ── Credentials group ────────────────────────────────────────────────────
    print("Credentials: schema / template / issue / lifecycle …")
    schema_req = {"name": "Loyalty Membership", "vct": "AirlineLoyalty",
                  "attributes": [{"name": "given_name", "sd": True}, {"name": "tier", "sd": True}]}
    s, schema = A("POST", "/v1/credential-schemas", body=schema_req)
    cap.record("POST /v1/credential-schemas", request=schema_req, status=s, body=schema,
               summary="Create a credential schema (the reusable claim + VCT definition).")
    schema_id = schema.get("uuid")

    s, schemas = A("GET", "/v1/credential-schemas")
    cap.record("GET /v1/credential-schemas", status=s, body=schemas,
               summary="List the tenant's credential schemas.")

    s, schema_detail = A("GET", f"/v1/credential-schemas/{schema_id}")
    cap.record("GET /v1/credential-schemas/{uuid}", status=s, body=schema_detail,
               summary="Fetch one schema plus its full version family.")

    tpl_req = {"schema": schema_id, "name": "standard", "validity_seconds": 31536000}
    s, tpl = A("POST", "/v1/credential-templates", body=tpl_req)
    cap.record("POST /v1/credential-templates", request=tpl_req, status=s, body=tpl,
               summary="Create an issuance template bound to a schema.")
    tpl_id = tpl.get("uuid")

    s, tpls = A("GET", "/v1/credential-templates")
    cap.record("GET /v1/credential-templates", status=s, body=tpls,
               summary="List the tenant's issuance templates.")

    issue_req = {"template_id": tpl_id, "holder_jwk": hk_present["pub"],
                 "claims": {"given_name": "Ada", "tier": "gold"}}
    s, issued = A("POST", "/v1/credentials/issue", body=issue_req)
    cap.record("POST /v1/credentials/issue", request=issue_req, status=s, body=issued,
               summary="Issue an SD-JWT VC directly to a holder's public JWK.")
    sd_jwt = issued.get("sd_jwt")
    cred_id = issued.get("credential_id")

    s, cred_list = A("GET", "/v1/credentials")
    cap.record("GET /v1/credentials", status=s, body=cred_list,
               summary="List the tenant's issued credentials.")
    # 401: no bearer
    s401, b401 = cli.call("GET", "/v1/credentials")
    cap.error("GET /v1/credentials", s401, b401, "missing bearer token")

    s, cred_detail = A("GET", f"/v1/credentials/{cred_id}")
    cap.record("GET /v1/credentials/{uuid}", status=s, body=cred_detail,
               summary="Fetch one issued-credential management record.")
    # 404: unknown uuid
    s404, b404 = A("GET", "/v1/credentials/00000000-0000-0000-0000-000000000000")
    cap.error("GET /v1/credentials/{uuid}", s404, b404, "unknown credential id")

    # ── OpenID4VP presentation + verification ────────────────────────────────
    print("Verification: request / present / response / verifications …")
    pr_req = {"requested_vct": "AirlineLoyalty", "requested_claims": ["tier"],
              "aud": "checkin-rp", "purpose": "Verify loyalty tier for lounge access"}
    s, pr = A("POST", "/v1/presentations/request", body=pr_req)
    cap.record("POST /v1/presentations/request", request=pr_req, status=s, body=pr,
               summary="Create an OpenID4VP presentation request (mints a single-use nonce + DCQL query).")
    pr_uuid = pr.get("uuid")
    pr_nonce = pr.get("nonce")
    pr_txid = pr.get("transaction_id")

    s, pr_list = A("GET", "/v1/presentations/requests")
    cap.record("GET /v1/presentations/requests", status=s, body=pr_list,
               summary="List the tenant's presentation requests.")
    # /presentations/requests is a create+list alias of /presentations/request
    s, pr_alias = A("POST", "/v1/presentations/requests", body=pr_req)
    cap.record("POST /v1/presentations/requests", request=pr_req, status=s, body=pr_alias,
               summary="Create a presentation request (alias of POST /v1/presentations/request).")
    s, pr_list2 = A("GET", "/v1/presentations/request")
    cap.record("GET /v1/presentations/request", status=s, body=pr_list2,
               summary="List the tenant's presentation requests (alias of /presentations/requests).")

    s, pr_params = cli.call("GET", f"/v1/presentations/{pr_uuid}/request")
    cap.record("GET /v1/presentations/{uuid}/request", status=s, body=pr_params,
               summary="The signed OpenID4VP request parameters a wallet dereferences (public).")

    s, pub_detail = cli.call("GET", f"/v1/presentations/{pr_uuid}")
    cap.record("GET /v1/presentations/{uuid}", status=s, body=pub_detail,
               summary="Public holder-poll view of a presentation request + terminal result summary.")

    # Present the credential (crypto side-car) and post the vp_token (public, no auth).
    try:
        vp = crypto.present(hk_present["priv"], sd_jwt, ["tier"], pr_nonce, "checkin-rp")
        resp_req = {"vp_token": vp}
        s, verdict = cli.call("POST", f"/v1/presentations/{pr_uuid}/response", body=resp_req)
        cap.record("POST /v1/presentations/{uuid}/response", request=resp_req, status=s, body=verdict,
                   summary="Wallet posts the vp_token; the verifier returns the verdict (public endpoint).")
    except Exception as e:  # noqa: BLE001
        cap.warn(f"presentation response capture failed: {e}")
    # 422: garbage vp_token on a fresh request
    s, pr2 = A("POST", "/v1/presentations/request", body=pr_req)
    s422, b422 = cli.call("POST", f"/v1/presentations/{pr2['uuid']}/response",
                          body={"vp_token": "not.a.real.presentation"})
    cap.error("POST /v1/presentations/{uuid}/response", s422, b422, "malformed vp_token fails verification")

    s, ver_list = A("GET", "/v1/verifications")
    cap.record("GET /v1/verifications", status=s, body=ver_list,
               summary="List completed verification results for the tenant.")
    s, ver_detail = A("GET", f"/v1/verifications/{pr_uuid}")
    cap.record("GET /v1/verifications/{uuid}", status=s, body=ver_detail,
               summary="Fetch one verification result incl. disclosed claims (tenant-authed; by request or result id).")

    # demo-present (dev-only convenience) — issue a fresh cred + request, then demo-present.
    try:
        s, pr3 = A("POST", "/v1/presentations/request", body=pr_req)
        s, demo = cli.call("POST", f"/v1/presentations/{pr3['uuid']}/demo-present", body={})
        cap.record("POST /v1/presentations/{uuid}/demo-present", request={}, status=s, body=demo,
                   summary="Dev-only shortcut: server-side present a sample credential against the request (404 in production).")
    except Exception as e:  # noqa: BLE001
        cap.warn(f"demo-present capture failed: {e}")

    # ── Credential lifecycle (throwaway credential) ──────────────────────────
    print("Credentials: suspend / reactivate / revoke (throwaway) …")
    s, life_issued = A("POST", "/v1/credentials/issue",
                       body={"template_id": tpl_id, "holder_jwk": hk_openid["pub"],
                             "claims": {"given_name": "Grace", "tier": "silver"}})
    life_id = life_issued.get("credential_id")
    s, susp = A("POST", f"/v1/credentials/{life_id}/suspend")
    cap.record("POST /v1/credentials/{uuid}/suspend", request={}, status=s, body=susp,
               summary="Temporarily disable a credential (reversible).")
    s409, b409 = A("POST", f"/v1/credentials/{life_id}/suspend")
    cap.error("POST /v1/credentials/{uuid}/suspend", s409, b409, "already suspended (only issued -> suspended)")
    s, react = A("POST", f"/v1/credentials/{life_id}/reactivate")
    cap.record("POST /v1/credentials/{uuid}/reactivate", request={}, status=s, body=react,
               summary="Return a suspended credential to issued.")
    s409, b409 = A("POST", f"/v1/credentials/{life_id}/reactivate")
    cap.error("POST /v1/credentials/{uuid}/reactivate", s409, b409, "reactivating an already-issued credential")
    s, revoked = A("POST", f"/v1/credentials/{life_id}/revoke")
    cap.record("POST /v1/credentials/{uuid}/revoke", request={}, status=s, body=revoked,
               summary="Permanently revoke a credential (terminal).")
    s409, b409 = A("POST", f"/v1/credentials/{life_id}/revoke")
    cap.error("POST /v1/credentials/{uuid}/revoke", s409, b409, "re-revoking a revoked credential")

    # ── Schema versions / status / bulk-revoke (throwaway schema family) ──────
    print("Credentials: schema versions / status / revoke-credentials …")
    s, sv = A("POST", "/v1/credential-schemas",
              body={"name": "Employee Badge " + rand(4), "vct": "EmployeeBadge",
                    "attributes": [{"name": "employee_id", "sd": True}, {"name": "department", "sd": False}]})
    sv_id = sv.get("uuid")
    s, tv = A("POST", "/v1/credential-templates",
              body={"schema": sv_id, "name": "badge", "validity_seconds": 2592000})
    tv_id = tv.get("uuid")
    A("POST", "/v1/credentials/issue",
      body={"template_id": tv_id, "holder_jwk": hk_offer["pub"], "claims": {"employee_id": "E-1024", "department": "Ops"}})
    ver_req = {"attributes": [{"name": "employee_id", "sd": True}, {"name": "department", "sd": False},
                              {"name": "clearance", "sd": True}]}
    s, newver = A("POST", f"/v1/credential-schemas/{sv_id}/versions", body=ver_req)
    cap.record("POST /v1/credential-schemas/{uuid}/versions", request=ver_req, status=s, body=newver,
               summary="Cut the next immutable version of a schema (bumps version, deprecates the source).")
    patch_req = {"status": "deprecated"}
    s, patched = A("PATCH", f"/v1/credential-schemas/{sv_id}", body=patch_req)
    cap.record("PATCH /v1/credential-schemas/{uuid}", request=patch_req, status=s, body=patched,
               summary="Deprecate or reactivate a schema version (deprecated blocks NEW issuance only).")
    s, bulk = A("POST", f"/v1/credential-schemas/{sv_id}/revoke-credentials", body={})
    cap.record("POST /v1/credential-schemas/{uuid}/revoke-credentials", request={}, status=s, body=bulk,
               summary="Bulk-revoke every live credential issued under this schema version (destructive).")

    # ── Offers / OpenID4VCI ──────────────────────────────────────────────────
    print("OpenID4VCI: offers / token / nonce / credential …")
    offer_req = {"template_id": tpl_id, "claims": {"given_name": "Ada", "tier": "gold"}}
    s, offer = A("POST", "/v1/credential-offers", body=offer_req)
    cap.record("POST /v1/credential-offers", request=offer_req, status=s, body=offer,
               summary="Create a credential offer (returns the pre-authorized code + QR/deep-link URI).")
    offer_id = offer.get("offer_id")
    pre_auth = offer.get("pre_authorized_code")
    tx_code = offer.get("tx_code")

    # email-delivery variant
    s, offer_email = A("POST", "/v1/credential-offers",
                       body={"template_id": tpl_id, "claims": {"given_name": "Ada", "tier": "gold"},
                             "recipient_email": "holder@diditcapture.dev"})
    email_offer_id = offer_email.get("offer_id")
    # keep the direct offer as the primary 201 example; email variant documented via resend below

    s, offer_list = A("GET", "/v1/credential-offers")
    cap.record("GET /v1/credential-offers", status=s, body=offer_list,
               summary="List the tenant's credential offers.")
    s, offer_detail = cli.call("GET", f"/v1/credential-offers/{offer_id}")
    cap.record("GET /v1/credential-offers/{uuid}", status=s, body=offer_detail,
               summary="Public offer preview (labels only while a tx_code is required).")
    s, offer_ref = cli.call("GET", f"/v1/credential-offers/{offer_id}/offer")
    cap.record("GET /v1/credential-offers/{uuid}/offer", status=s, body=offer_ref,
               summary="Standard OpenID4VCI credential-offer-by-reference document.")
    s, resolved = cli.call("GET", "/v1/credential-offers/resolve",
                           query={"tenant": slug, "code": pre_auth})
    cap.record("GET /v1/credential-offers/resolve", query={"tenant": slug, "code": pre_auth},
               status=s, body=resolved,
               summary="Resolve an offer by (tenant, pre-authorized code) for the wallet claim screen.")
    if email_offer_id:
        s, resent = A("POST", f"/v1/credential-offers/{email_offer_id}/resend-email", body={})
        cap.record("POST /v1/credential-offers/{uuid}/resend-email", request={}, status=s, body=resent,
                   summary="Re-send the claim email for a pending email-delivery offer.")

    # accept (dev-only) on a fresh offer
    s, acc_offer = A("POST", "/v1/credential-offers", body=offer_req)
    s, accepted = cli.call("POST", f"/v1/credential-offers/{acc_offer['offer_id']}/accept", body={})
    cap.record("POST /v1/credential-offers/{uuid}/accept", request={}, status=s, body=accepted,
               summary="Dev-only shortcut: server-side accept an offer and mint the credential (404 in production).")

    # well-known metadata + jwks
    s, wk = cli.call("GET", f"/v1/issuers/{slug}/.well-known/openid-credential-issuer")
    cap.record("GET /v1/issuers/{slug}/.well-known/openid-credential-issuer", status=s, body=wk,
               summary="OpenID4VCI issuer metadata (endpoints + credential_configurations_supported).")
    credential_issuer = wk.get("credential_issuer", issuer_id) if isinstance(wk, dict) else issuer_id
    s, jwks = cli.call("GET", f"/v1/issuers/{slug}/.well-known/jwt-vc-issuer")
    cap.record("GET /v1/issuers/{slug}/.well-known/jwt-vc-issuer", status=s, body=jwks,
               summary="SD-JWT VC issuer JWKS document (the keys that verify this issuer's credentials).")

    # token -> nonce -> proof -> credential (fresh direct offer)
    s, tok_offer = A("POST", "/v1/credential-offers", body=offer_req)
    tok_req = {"grant_type": PRE_AUTH_GRANT,
               "pre-authorized_code": tok_offer["pre_authorized_code"], "tx_code": tok_offer["tx_code"]}
    s, token_resp = cli.call("POST", "/v1/oauth/token", body=tok_req)
    cap.record("POST /v1/oauth/token", request=tok_req, status=s, body=token_resp,
               summary="Redeem a pre-authorized code (+ tx_code) for a short-lived issuance access token.")
    access = token_resp.get("access_token")
    s, nonce_resp = cli.call("POST", "/v1/nonce", body={})
    cap.record("POST /v1/nonce", request={}, status=s, body=nonce_resp,
               summary="Mint a single-use c_nonce the holder proof must bind to.")
    c_nonce = nonce_resp.get("c_nonce")
    try:
        proof = crypto.proof(hk_openid["priv"], credential_issuer, c_nonce)
        cred_req = {"proof": {"proof_type": "jwt", "jwt": proof}}
        s, cred_resp = cli.call("POST", "/v1/credential", body=cred_req, token=access)
        cap.record("POST /v1/credential", request=cred_req, status=s, body=cred_resp,
                   summary="Redeem the access token + holder proof for the issued SD-JWT VC (OpenID4VCI).")
    except Exception as e:  # noqa: BLE001
        cap.warn(f"POST /v1/credential capture failed: {e}")
    s401, b401 = cli.call("POST", "/v1/credential", body={"proof": {"proof_type": "jwt", "jwt": "a.b.c"}},
                          token="not-a-real-token")
    cap.error("POST /v1/credential", s401, b401, "invalid issuance access token")

    # ── Keys + status list ───────────────────────────────────────────────────
    print("Keys: list / impact / rotate + status list …")
    s, keys_list = A("GET", "/v1/keys")
    cap.record("GET /v1/keys", status=s, body=keys_list, summary="List the tenant's issuer signing keys.")
    s, impact = A("GET", "/v1/keys/impact")
    cap.record("GET /v1/keys/impact", status=s, body=impact,
               summary="Preview how many live credentials a key rotation would affect.")
    # rotate on a SEPARATE tenant so tenant A's captured verifications stay valid
    try:
        rk, rslug, _ = bootstrap_tenant(cli, label="docs-rotate")
        s, rot = cli.call("POST", "/v1/keys/rotate", body={"overlap_days": 7}, token=rk)
        cap.record("POST /v1/keys/rotate", request={"overlap_days": 7}, status=s, body=rot,
                   summary="Rotate the issuer signing key with an overlap window (old key still verifies).")
    except Exception as e:  # noqa: BLE001
        cap.warn(f"keys/rotate capture failed: {e}")

    status_uri = status_uri_from_sdjwt(sd_jwt or "")
    if status_uri:
        sl_path = status_uri.split("/v1/", 1)[-1]
        s, sl = cli.call("GET", "/v1/" + sl_path)
        cap.record("GET /v1/status-lists/{slug}/{uuid}", status=s, body=sl,
                   summary="Fetch a Token-Status-List (the revocation/suspension bitstring token).")
    else:
        cap.warn("no status-list uri found in issued sd-jwt; skipping status-list capture")

    # ── Trust registry ───────────────────────────────────────────────────────
    print("Trust registry: frameworks / issuers / relying-parties …")
    s, fw_list = A("GET", "/v1/trust-frameworks")
    cap.record("GET /v1/trust-frameworks", status=s, body=fw_list,
               summary="List governed (platform-catalog) + custom trust frameworks.")
    fw_req = {"name": "ACME Partner Framework " + rand(4), "region": "EU", "profile": "custom",
              "formats": ["sd_jwt_vc"], "description": "Partner onboarding trust rules."}
    s, fw = A("POST", "/v1/trust-frameworks", body=fw_req)
    cap.record("POST /v1/trust-frameworks", request=fw_req, status=s, body=fw,
               summary="Create a custom, tenant-owned trust framework.")
    fw_slug = fw.get("slug")
    s, fw_detail = A("GET", f"/v1/trust-frameworks/{fw_slug}")
    cap.record("GET /v1/trust-frameworks/{slug}", status=s, body=fw_detail,
               summary="Fetch one trust framework by slug.")
    fw_patch = {"description": "Updated partner onboarding trust rules."}
    s, fw_patched = A("PATCH", f"/v1/trust-frameworks/{fw_slug}", body=fw_patch)
    cap.record("PATCH /v1/trust-frameworks/{slug}", request=fw_patch, status=s, body=fw_patched,
               summary="Edit a custom framework (governed frameworks are immutable -> 403).")
    s403, b403 = A("PATCH", "/v1/trust-frameworks/eidas2", body={"description": "x"})
    cap.error("PATCH /v1/trust-frameworks/{slug}", s403, b403, "editing a governed framework")
    # delete a throwaway custom framework
    s, fw2 = A("POST", "/v1/trust-frameworks",
               body={"name": "Throwaway Framework " + rand(4), "formats": ["sd_jwt_vc"]})
    s, fw_del = A("DELETE", f"/v1/trust-frameworks/{fw2['slug']}")
    cap.record("DELETE /v1/trust-frameworks/{slug}", status=s, body=(fw_del or {"detail": "No content."}),
               summary="Delete a custom framework (204; governed -> 403).")
    cap.data["DELETE /v1/trust-frameworks/{slug}"]["responses"] = {"204": {}}
    s403, b403 = A("DELETE", "/v1/trust-frameworks/iso-mdl")
    cap.error("DELETE /v1/trust-frameworks/{slug}", s403, b403, "deleting a governed framework")

    ti_req = {"name": "Gov PID Issuer", "iss": external_iss, "trust_anchor": "https-jwks",
              "framework": fw_slug}
    s, ti = A("POST", "/v1/trusted-issuers", body=ti_req)
    cap.record("POST /v1/trusted-issuers", request=ti_req, status=s, body=ti,
               summary="Register a trusted issuer whose credentials this tenant will accept.")
    ti_id = ti.get("id") or ti.get("uuid")
    s, ti_list = A("GET", "/v1/trusted-issuers")
    cap.record("GET /v1/trusted-issuers", status=s, body=ti_list,
               summary="List the tenant's trusted issuers.")
    ti_patch = {"status": "disabled"}
    s, ti_patched = A("PATCH", f"/v1/trusted-issuers/{ti_id}", body=ti_patch)
    cap.record("PATCH /v1/trusted-issuers/{uuid}", request=ti_patch, status=s, body=ti_patched,
               summary="Enable or disable a trusted issuer (disabled fails the trust gate but keeps the entry).")
    A("PATCH", f"/v1/trusted-issuers/{ti_id}", body={"status": "active"})
    s, ti_valid = A("POST", f"/v1/trusted-issuers/{ti_id}/validate", body={})
    cap.record("POST /v1/trusted-issuers/{uuid}/validate", request={}, status=s, body=ti_valid,
               summary="Probe a trusted issuer's trust anchor (reachability + key resolution).")
    # delete a throwaway issuer
    s, ti2 = A("POST", "/v1/trusted-issuers",
               body={"name": "Throwaway Issuer", "iss": "https://old-issuer.example", "trust_anchor": "https-jwks"})
    s, ti_del = A("DELETE", f"/v1/trusted-issuers/{ti2.get('id') or ti2.get('uuid')}")
    cap.record("DELETE /v1/trusted-issuers/{uuid}", status=s, body=(ti_del or {}),
               summary="Remove a trusted issuer (soft delete, 204).")
    cap.data["DELETE /v1/trusted-issuers/{uuid}"]["responses"] = {"204": {}}

    rp_req = {"name": "Campus Door", "origin": "https://door.acme.example"}
    s, rp = A("POST", "/v1/relying-parties", body=rp_req)
    cap.record("POST /v1/relying-parties", request=rp_req, status=s, body=rp,
               summary="Register a relying party / verifier origin.")
    s, rp_list = A("GET", "/v1/relying-parties")
    cap.record("GET /v1/relying-parties", status=s, body=rp_list,
               summary="List the tenant's relying parties.")
    s, rp2 = A("POST", "/v1/relying-parties", body={"name": "Throwaway RP", "origin": "https://rp.example"})
    s, rp_del = A("DELETE", f"/v1/relying-parties/{rp2.get('id') or rp2.get('uuid')}")
    cap.record("DELETE /v1/relying-parties/{uuid}", status=s, body=(rp_del or {}),
               summary="Remove a relying party (soft delete, 204).")
    cap.data["DELETE /v1/relying-parties/{uuid}"]["responses"] = {"204": {}}

    # ── Members ──────────────────────────────────────────────────────────────
    print("Members …")
    s, members = A("GET", "/v1/members")
    cap.record("GET /v1/members", status=s, body=members, summary="List the tenant's team members + roles.")
    mem_req = {"email": f"teammate-{rand(4)}@diditcapture.dev", "role": "reader"}
    s, mem = A("POST", "/v1/members", body=mem_req)
    cap.record("POST /v1/members", request=mem_req, status=s, body=mem,
               summary="Invite a team member with a role.")
    mem_email = mem_req["email"]
    s, mem_patched = A("PATCH", f"/v1/members/{mem_email}", body={"role": "admin"})
    cap.record("PATCH /v1/members/{email}", request={"role": "admin"}, status=s, body=mem_patched,
               summary="Change a member's role.")
    s, mem_del = A("DELETE", f"/v1/members/{mem_email}")
    cap.data.setdefault("DELETE /v1/members/{email}", {"source": "captured-live", "responses": {}, "errors": []})
    cap.data["DELETE /v1/members/{email}"]["responses"] = {"204": {}}
    cap.data["DELETE /v1/members/{email}"]["summary"] = "Remove a team member (204)."

    # ── write ────────────────────────────────────────────────────────────────
    out.write_text(json.dumps(cap.data, indent=2, sort_keys=True) + "\n")
    n_live = sum(1 for v in cap.data.values() if v.get("source") == "captured-live")
    n_resp = sum(len(v.get("responses", {})) for v in cap.data.values())
    n_err = sum(len(v.get("errors", [])) for v in cap.data.values())
    print(f"\nCaptured {len(cap.data)} endpoints ({n_live} live), "
          f"{n_resp} success bodies, {n_err} error bodies -> {out}")
    if cap.warnings:
        print(f"\n{len(cap.warnings)} warning(s):")
        for w in cap.warnings:
            print("  -", w)
    return cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8011")
    ap.add_argument("--venv", default=str(DEFAULT_VENV))
    ap.add_argument("--out", default=str(ROOT / "scripts" / "captured-examples.json"))
    args = ap.parse_args()
    run(args.base, Path(args.venv), Path(args.out))


if __name__ == "__main__":
    main()
