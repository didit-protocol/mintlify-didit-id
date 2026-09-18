/**
 * The canonical Didit ID (Didit Credentials) integration prompt — paste into
 * Claude Code, Codex, Cursor, Copilot, Devin, or any AI coding agent to
 * integrate the verifiable-credentials platform end-to-end.
 *
 * Verified against:
 *   - openapi.json                     (management + protocol API — every path cross-checked)
 *   - guides/programmatic-access.mdx   (register / verify-email / login / tenant bootstrap)
 *   - guides/issuance.mdx              (schema, template, offer, OpenID4VCI claim)
 *   - guides/verification.mdx          (DCQL request, vp_token response, checks)
 *   - docs-schemas/openid4vci.json     (token / nonce / credential field-level contracts)
 *
 * The two-secret contract is sacred: the user access_token is ONLY for
 * POST /v1/tenant/bootstrap; the tenant api_key is for every other /v1
 * management call and must never reach a wallet, browser, or email.
 */
export const DIDIT_ID_INTEGRATION_PROMPT = `# Integrate Didit ID (verifiable credentials) into my application

You are integrating Didit ID — Didit's verifiable-credentials platform — into my application end-to-end. Didit ID issues and verifies SD-JWT VC credentials with OpenID4VCI (issuance) and OpenID4VP (verification): selective disclosure, holder key binding, Token Status List revocation, and a per-tenant trust registry, all behind one \`/v1\` API. Build a working issue -> claim -> present -> verify integration on my backend. Follow this spec exactly.

## My application context

<my_stack>
Stack: [framework + language — e.g. Next.js 15 + TypeScript, Django, Rails, Go]
Surface: [web | mobile | backend-only]
Credential to issue: [e.g. employee badge | membership card | age-over-18 | student ID]
Claims: [e.g. employee_id, role, department]
Verifier use case: [e.g. office door check needs role only]
Database: [Postgres | MySQL | Mongo | other]
</my_stack>

## Environment

\`\`\`bash
# Base server — all paths below are relative to this host.
DIDIT_BASE_URL="http://localhost:8011"        # local dev; production: replace with your deployed Didit ID host
# Two distinct secrets — do not confuse them:
DIDIT_ACCESS_TOKEN="..."   # user token from verify-email / login — ONLY for POST /v1/tenant/bootstrap
DIDIT_API_KEY="..."        # tenant API key from POST /v1/tenant/bootstrap — every other /v1 management call
\`\`\`

Programmatic auth lives under \`{BASE}/auth/v2/programmatic/*\` (public, no auth header, CORS-open). The tenant bridge is \`{BASE}/v1/tenant/bootstrap\` (Bearer user access_token). The management API is \`{BASE}/v1/*\` (Bearer tenant api_key). Wallet-facing protocol endpoints (\`/v1/oauth/token\`, \`/v1/nonce\`, \`/v1/credential\`, \`/v1/credential-offers/{uuid}\`, \`/v1/presentations/{uuid}\`, \`/v1/presentations/{uuid}/response\`, \`/v1/issuers/{slug}/.well-known/*\`) never use the tenant API key. Send \`Content-Type: application/json\` on every request with a body.

## Step 1 — Get access programmatically (no browser)

\`\`\`bash
# 1) Register — creates the account + emails a 6-character UPPERCASE OTP.
curl -X POST "$DIDIT_BASE_URL/auth/v2/programmatic/register/" \\
  -H "Content-Type: application/json" \\
  -d '{"email": "agent@example.com", "password": "a-strong-password"}'
# -> 201 { message, email }

# 2) Verify the email OTP — ONE-TIME bootstrap: returns tokens AND provisions
#    the organization + application.
curl -X POST "$DIDIT_BASE_URL/auth/v2/programmatic/verify-email/" \\
  -H "Content-Type: application/json" \\
  -d '{"email": "agent@example.com", "code": "AB12CD"}'
# -> 200 { access_token, refresh_token, token_type: "Bearer", expires_in,
#          organization: { uuid, name },
#          application:  { uuid, name, client_id, api_key } }

# (If the OTP is lost: POST /auth/v2/programmatic/resend-otp/ with { email, password }.)
# (For fresh tokens later: POST /auth/v2/programmatic/login/ with { email, password }.)

# 3) Bootstrap the credentials tenant — idempotent; the USER access_token goes here and ONLY here.
curl -X POST "$DIDIT_BASE_URL/v1/tenant/bootstrap" \\
  -H "Authorization: Bearer $DIDIT_ACCESS_TOKEN"
# -> 200 { tenant: { slug, name }, api_key, environment: "sandbox", seeded: bool }
\`\`\`

Persist the returned \`api_key\` as \`DIDIT_API_KEY\` (server-side secret — never in a wallet, browser bundle, QR payload, or email). Note your \`tenant.slug\`: it is the issuer slug used in the \`.well-known\` issuer-metadata URLs below.

## Step 2 — Define the credential (schema + template)

\`\`\`bash
# Schema = the credential type (vct) + its attributes. sd: true marks an
# attribute as selectively disclosable (the holder can reveal it independently).
curl -X POST "$DIDIT_BASE_URL/v1/credential-schemas" \\
  -H "Authorization: Bearer $DIDIT_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Employee Badge",
    "vct": "EmployeeBadge",
    "attributes": [
      { "name": "employee_id", "type": "string", "sd": true },
      { "name": "role",        "type": "string", "sd": true },
      { "name": "department",  "type": "string", "sd": true }
    ]
  }'
# -> { uuid, vct, format: "sd_jwt_vc" }

# Template = reusable issuance config for that schema; its uuid is TEMPLATE_ID.
curl -X POST "$DIDIT_BASE_URL/v1/credential-templates" \\
  -H "Authorization: Bearer $DIDIT_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{ "schema": "<schema uuid>", "name": "standard", "validity_seconds": 31536000 }'
# -> { uuid }   (TEMPLATE_ID)
\`\`\`

## Step 3 — Issue via a credential offer (email claim link)

\`\`\`bash
curl -X POST "$DIDIT_BASE_URL/v1/credential-offers" \\
  -H "Authorization: Bearer $DIDIT_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "template_id": "<TEMPLATE_ID>",
    "claims": { "employee_id": "E-1042", "role": "Engineer", "department": "Platform" },
    "recipient_email": "holder@example.com",
    "send_email": true
  }'
# -> 201 { offer_id, credential_offer_uri, credential_issuer,
#          pre_authorized_code, tx_code,
#          grants: { "urn:ietf:params:oauth:grant-type:pre-authorized_code":
#                    { "pre-authorized_code": "..." } } }
\`\`\`

- With \`recipient_email\` + \`send_email: true\`, Didit ID emails the holder a claim link that opens the holder wallet with this offer loaded. Without them, deliver \`credential_offer_uri\` yourself as a QR code or deep link.
- \`tx_code\` (transaction code / PIN) defaults to ON: the response carries a 6-digit \`tx_code\` that the wallet must present at token exchange. **The issuer shares the PIN with the holder out-of-band** (SMS, chat, in person — never in the same email as the claim link). Pass \`"tx_code": false\` to disable it for low-risk credentials; the response \`tx_code\` is then an empty string.
- Offers are single-use and expire 10 minutes after creation.

## Step 4 — Holder claim (OpenID4VCI — what the wallet does)

The Didit ID holder wallet performs this exchange automatically when the claim link opens. Implement it yourself only if you are building a custom holder. Discover endpoints from the public issuer metadata: \`GET /v1/issuers/<slug>/.well-known/openid-credential-issuer\` -> \`{ credential_issuer, credential_endpoint, nonce_endpoint, token_endpoint, jwt_vc_issuer, credential_configurations_supported }\`.

\`\`\`bash
# 4a) Exchange the pre-authorized code (+ tx_code) for a single-use access token (300 s TTL).
#     NOTE: the body key is "pre-authorized_code" WITH a hyphen. 5 wrong tx_code attempts lock the offer.
curl -X POST "$DIDIT_BASE_URL/v1/oauth/token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "grant_type": "urn:ietf:params:oauth:grant-type:pre-authorized_code",
    "pre-authorized_code": "<pre_authorized_code from the offer>",
    "tx_code": "<6-digit PIN>"
  }'
# -> 200 { access_token, token_type: "Bearer", expires_in: 300 }

# 4b) Mint a single-use proof nonce (60 s TTL).
curl -X POST "$DIDIT_BASE_URL/v1/nonce" -H "Content-Type: application/json" -d '{}'
# -> 200 { c_nonce, c_nonce_expires_in: 60 }

# 4c) Redeem the token + holder proof for the SD-JWT VC.
#     The proof is a JWT with header { typ: "openid4vci-proof+jwt", alg: "ES256", jwk: <holder PUBLIC JWK> }
#     and payload { nonce: <c_nonce>, aud: <credential_issuer from issuer metadata>, iat }.
#     Sign it with the holder's PRIVATE key (ES256; EdDSA also accepted). The private key never leaves the holder.
curl -X POST "$DIDIT_BASE_URL/v1/credential" \\
  -H "Authorization: Bearer <access_token from 4a>" \\
  -H "Content-Type: application/json" \\
  -d '{ "proof": { "proof_type": "jwt", "jwt": "<openid4vci-proof+jwt>" } }'
# -> 200 { credential: "<jws>~<disclosure>~<disclosure>~", vct: "EmployeeBadge" }
\`\`\`

The response \`credential\` is the issued SD-JWT VC (issuer-signed JWS + tilde-separated disclosures, trailing tilde). The token, nonce, and offer are all consumed on success. To test before your wallet exists, open the offer's \`claim_url\` in the hosted sandbox wallet (https://wallet-idv0.staging.didit.me): it runs 4a–4c with its own holder key.

## Step 5 — Verify a presentation (OpenID4VP + DCQL)

\`\`\`bash
# 5a) Backend creates the presentation request (tenant API key).
curl -X POST "$DIDIT_BASE_URL/v1/presentations/request" \\
  -H "Authorization: Bearer $DIDIT_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "requested_vct": "EmployeeBadge",
    "requested_claims": ["role"],
    "aud": "office-access-rp",
    "trusted_iss": ""
  }'
# -> { uuid, transaction_id, dcql, requested_claims, aud, nonce, status: "pending" }

# 5b) Deliver the request to the holder wallet (W3C Digital Credentials API,
#     protocol "openid4vp-v1-signed"). The wallet signs a key-bound SD-JWT VC
#     presentation and submits it to the PUBLIC response endpoint:
#     POST /v1/presentations/<uuid>/response   body: { "vp_token": "<sd-jwt-vc presentation with KB-JWT>" }

# 5c) Backend polls the request until the result lands (public, PII-free).
curl "$DIDIT_BASE_URL/v1/presentations/<uuid>"
# -> { uuid, status, ..., result: { verdict: "verified", error: "",
#        checks: { signature, key_binding, aud, nonce, alg_allowlist, not_expired, not_revoked } } }

# 5d) Backend reads the disclosed claims (tenant API key; accepts the request uuid).
curl "$DIDIT_BASE_URL/v1/verifications/<uuid>" -H "Authorization: Bearer $DIDIT_API_KEY"
# -> { id, request_id, verdict, vct, verifier, requested_claims,
#      disclosed_claims: { "role": "Engineer" }, checks, error, created_at }
\`\`\`

Treat \`result.verdict === "verified"\` as the authoritative decision; use the boolean \`checks\` map to explain failures. Issuer trust also gates the verdict — a cryptographically valid credential from an issuer outside the tenant trust registry fails. Audit history: \`GET /v1/verifications\` and \`GET /v1/verifications/{uuid}\` (tenant API key). To test before your wallet exists, open \`https://wallet-idv0.staging.didit.me/present?request=<uuid>\` in the hosted sandbox wallet and approve the request there.

## Lifecycle & operations (wire these where relevant)

- Revoke / suspend / reactivate: \`POST /v1/credentials/{uuid}/revoke | suspend | reactivate\`; list with \`GET /v1/credentials\`. Revocation surfaces in verification as \`checks.not_revoked = false\` via IETF Token Status Lists (\`GET /v1/status-lists/{slug}/{uuid}\` is public).
- Trust registry: \`GET|POST /v1/trusted-issuers\`, \`DELETE /v1/trusted-issuers/{uuid}\`, \`POST /v1/trusted-issuers/{uuid}/validate\`, frameworks from \`GET /v1/trust-frameworks\`.
- Relying parties: \`GET|POST /v1/relying-parties\`, \`DELETE /v1/relying-parties/{uuid}\` — register each verifier origin used with the Digital Credentials API.
- Issuer keys: \`GET /v1/keys\`, \`GET /v1/keys/impact\` (preview), \`POST /v1/keys/rotate\` (old key stays valid during the overlap window).

## Deliverable

Build a small backend module that:

1. Reads \`DIDIT_BASE_URL\`, \`DIDIT_ACCESS_TOKEN\`, and \`DIDIT_API_KEY\` from the environment; if \`DIDIT_API_KEY\` is missing, calls \`POST /v1/tenant/bootstrap\` once and persists the returned \`api_key\`.
2. Exposes: \`createSchemaAndTemplate()\`, \`issueByEmail(recipientEmail, claims)\` (offer with \`recipient_email\` + \`send_email: true\`, returning \`offer_id\` and the \`tx_code\` to deliver out-of-band), \`requestPresentation(requestedClaims, aud)\`, and \`pollResult(presentationUuid)\` that resolves \`{ verdict, disclosed_claims, checks }\`.
3. Never logs or hard-codes secrets; uses the tenant \`api_key\` as Bearer for every management call and the user \`access_token\` ONLY for \`/v1/tenant/bootstrap\`; never sends the API key to a wallet, browser, or email.
4. Includes a runnable end-to-end script that prints the offer \`claim_url\` and the wallet present link, waits for the holder to act in the hosted sandbox wallet, and prints the final \`verdict\` + \`checks\` + \`disclosed_claims\`.

If anything in \`## My application context\` is missing, ask once at the top of your reply, then ship the complete change set in my stack's idioms (\`fetch\` / \`axios\` / \`requests\` / \`okhttp\`). Adjust the example schema (\`EmployeeBadge\`) and claims to my credential; keep the endpoint contract exactly as specified above.
`;
