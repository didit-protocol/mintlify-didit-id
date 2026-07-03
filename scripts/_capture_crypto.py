#!/usr/bin/env python3
"""Crypto side-car for scripts/capture_examples.py.

The SD-JWT VC holder proof (OpenID4VCI) and the vp_token presentation (OpenID4VP) can only be
produced with the holder's private key + the IETF `sd-jwt` reference library. This tiny helper
reuses the credentials-service's own `credentials.services.sdjwt` module (pure-python, no Django)
so the captured proofs/presentations are byte-for-byte what a real wallet would send.

It MUST run with the credentials-service virtualenv (which ships jwcrypto + sd_jwt), e.g.:

    ~/Documents/projects_v2/didit/didit-credentials-service/.venv/bin/python \
        scripts/_capture_crypto.py    # (reads one job as JSON on stdin, prints JSON on stdout)

Job shapes (one per invocation, JSON on stdin):
  {"cmd": "keygen", "count": 3}
      -> {"keys": [{"priv": "<jwk-json>", "pub": {..public jwk..}}, ...]}
  {"cmd": "proof", "priv": "<jwk-json>", "audience": "...", "nonce": "..."}
      -> {"proof": "<compact-jwt>"}
  {"cmd": "present", "priv": "<jwk-json>", "issuance": "<sd-jwt>", "disclose": ["tier"],
   "nonce": "...", "aud": "..."}
      -> {"vp_token": "<sd-jwt~...~kb-jwt>"}

The credentials-service source dir is taken from CRED_SERVICE_SRC or the default path below.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

DEFAULT_SRC = Path.home() / "Documents/projects_v2/didit/didit-credentials-service/src"


def _load_sdjwt():
    src = Path(os.environ.get("CRED_SERVICE_SRC", DEFAULT_SRC))
    path = src / "credentials" / "services" / "sdjwt.py"
    spec = importlib.util.spec_from_file_location("sdjwt_standalone", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass in the module needs itself registered
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    sdjwt = _load_sdjwt()
    from jwcrypto.jwk import JWK

    job = json.loads(sys.stdin.read())
    cmd = job["cmd"]

    if cmd == "keygen":
        keys = []
        for _ in range(int(job.get("count", 1))):
            k = sdjwt.generate_holder_key()
            keys.append({"priv": k.export(private_key=True), "pub": k.export_public(as_dict=True)})
        print(json.dumps({"keys": keys}))
        return 0

    if cmd == "proof":
        hk = JWK.from_json(job["priv"])
        proof = sdjwt.make_proof_jwt(holder_key=hk, audience=job["audience"], nonce=job["nonce"])
        print(json.dumps({"proof": proof}))
        return 0

    if cmd == "present":
        hk = JWK.from_json(job["priv"])
        vp = sdjwt.present_sd_jwt_vc(
            issuance=job["issuance"],
            disclose=list(job["disclose"]),
            holder_key=hk,
            nonce=job["nonce"],
            aud=job["aud"],
        )
        print(json.dumps({"vp_token": vp}))
        return 0

    print(json.dumps({"error": f"unknown cmd {cmd!r}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
