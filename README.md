# geena-python

The Python client for Geena's partner integration surface — the `geena` package.

A partner's backend uses it to hold a **connection** with a Geena user and to act for its own
organization:

- **app tokens** (`geena.app_tokens`): an app that signs its own users in signs a short-lived
  token for each of them — data tokens for both planes, connect hints for its staff, claim links
  for the people it imported. No client secret, no code exchange, no refresh;
- the **connect ceremony** (`geena.oauth`, `geena.pkce`): the authorize URL with PKCE and
  `manifest_id`, `scope=ORGANIZATION_SCOPE` for the back-office sign-in, or `connect_url()` to
  connect a staff member with a connect hint; the code exchange; refresh with rotation;
  revocation;
- the **Partner API** (`/partner/v1`, `geena.partner`): connections, status, serving, filling,
  participants (relatives and companies), corrections by held accounts and contacts;
- the **Organization API** (`/org/v1`, `geena.org`): imports, the manifest, requests and
  records, kept copies and corrections, pending versions, request files;
- **token custody** (`geena.tokens`): a `TokenSet` per OAuth connection and `ensure_fresh()`;
  where tokens are stored and who holds the lock while they rotate stays the integrator's
  decision.

The API itself is documented at https://docs.test.geena.eu/. This package follows that contract:
`openapi/` holds identa's two OpenAPI documents at the release the package was built against
(`openapi/PIN.yaml`), and the test suite holds every model to them.

## Status

`0.2.0.dev0`, pinned to identa **v0.40.0**. Installable from the repository until the first tag:

```bash
pip install "git+https://github.com/Identa-io/geena-python@main"
```

Python 3.11 or newer; depends on `httpx`, `pydantic` v2 and `PyJWT` (with `cryptography`, for
app tokens).

## Quickstart: an app that signs its own tokens

Your app already signs its users in. Register one key pair on your apps in Geena (Organization
→ Apps → *This app signs its own tokens*: issuer, public key, `ES256`), keep the private key on
your backend, and sign a token per person:

```python
from geena import AppTokenSigner, GeenaClient
from geena.models.org import ImportPerson, ImportRequest, ImportValue
from geena.pkce import challenge_for, new_state, new_verifier

geena = GeenaClient(
    "https://api.test.geena.eu",
    client_id="dff-staff",  # no client secret: nothing is exchanged or refreshed
    dashboard_base_url="https://dashboard.test.geena.eu",  # claim pages
)
signer = AppTokenSigner(
    issuer="https://flow.example.com",  # the iss registered on your apps
    private_key=GEENA_SIGNING_KEY,  # PEM; a literal "\n" from an environment variable is fine
    audience="https://api.test.geena.eu",
)
```

**Call as the person** — one token per signed-in user, at most ten minutes, reusable until
`expires_at`. Hand it to the page or call from your backend; never mint one while someone
impersonates the user:

```python
token = signer.data_token("dff-staff", staff_user.id)
requests = await geena.org.list_requests(token.token)
```

**Connect a staff member, once** — they must already be a member of your organization in Geena
(and have signed in there once, or `/org/v1` answers `423 org_sealed`):

```python
url = geena.oauth.connect_url(
    redirect_uri="https://flow.example.com/geena/connected",
    state=new_state(),
    code_challenge=challenge_for(new_verifier()),  # the code that comes back is not exchanged
    connect_hint=signer.connect_hint("dff-staff", staff_user.id).token,
)
```

**Import an investor you already serve** (`request_manage`) — slot ids come from the manifest,
never hard-coded; a re-run adds what is new and never overwrites:

```python
manifest = await geena.org.manifest(token.token, MANIFEST_ID)
result = await geena.org.import_investor(
    token.token,
    ImportRequest(
        client_id="dff-client",  # the app whose users the people are
        manifest_id=MANIFEST_ID,
        external_ref=investor.id,
        kind="individual",
        people=[ImportPerson(sub=contact.id, email=contact.email, role="owner")],
        values=[
            ImportValue(
                slot_id=manifest.slot("PersonFullName").slot_id,
                data={"firstName": "Henrik", "lastName": "van den Berg"},
            )
        ],
    ),
)
```

**Let the investor claim** their account — Geena mails them a code:

```python
claim = geena.claim_url(signer.claim_link("dff-client", contact.id).token)  # send them here
```

**Decide what is pending** — a held investor's or a contact's correction, or an update on a
manual slot:

```python
for version in (await geena.org.pending(token.token, request_id)).pending:
    await geena.org.accept_pending(token.token, request_id, version.resource_id, version.version)
```

## Quickstart: the OAuth connect ceremony

```python
from geena import GeenaClient, ORGANIZATION_SCOPE, TokenSet, ensure_fresh
from geena.pkce import challenge_for, new_state, new_verifier

geena = GeenaClient(
    "https://api.test.geena.eu",
    client_id="acme-portal",
    client_secret=SECRET,  # backend only, never in a browser
    dashboard_base_url="https://dashboard.test.geena.eu",  # deep links
)
```

**Start a data connection** (the "Connect with Geena" button). Keep `state` and `verifier`
server-side, keyed by `state`, for the return:

```python
verifier, state = new_verifier(), new_state()
url = geena.oauth.authorize_url(
    redirect_uri="https://app.example.com/geena/callback",  # exactly a registered origin
    state=state,
    code_challenge=challenge_for(verifier),
    manifest_id=MANIFEST_ID,
)
```

**Finish it** on the callback — the exchange returns the tokens **and the `request_id`**, the
address of everything on the partner plane:

```python
tokens = await geena.oauth.exchange_code(
    code=code, code_verifier=verifier, redirect_uri=redirect_uri
)
stored = TokenSet.from_response(tokens)  # persist: access token, expiry, refresh token, request_id
claims = geena.oauth.decode_claims(tokens.access_token)  # sub + email, for your own bookkeeping
```

**Read and fill**, always with a fresh access token:

```python
stored = await ensure_fresh(stored, geena.oauth)  # hold a row lock around this; persist the result
status = await geena.partner.status(stored.access_token, stored.request_id)
for item in status.items:
    if item.granted:
        slot = await geena.partner.serve_slot(stored.access_token, stored.request_id, item.slot_id)
        for record in slot.records:  # one per party on a subject slot
            if record.available:
                ...  # record.data / record.download_url / record.participant
    elif item.allows("fill"):
        picks = await geena.partner.candidates(stored.access_token, stored.request_id, item.slot_id)
```

**Sign your back office in** — the same ceremony with `scope=ORGANIZATION_SCOPE` and no
manifest. The token response's `scope` says whether the person is a member; only then does the
token open `/org/v1`:

```python
url = geena.oauth.authorize_url(
    redirect_uri=..., state=..., code_challenge=..., scope=ORGANIZATION_SCOPE
)
...
tokens = await geena.oauth.exchange_code(...)
if tokens.grants("organization"):
    detail = await geena.org.request(tokens.access_token, request_id)
    kept = await geena.org.adopt(tokens.access_token, request_id, slot_id)  # read kept.skipped
    copies = await geena.org.copies(tokens.access_token, request_id)  # copy.values = the head
```

**Errors.** Every refusal is typed: `GeenaAPIError` carries the plane's `status` and stable
`code` (`not_found`, `slot_conflict`, `participant_ineligible`, `org_sealed`, `account_held`,
`import_refused`, ...), with `is_unauthorized` for a refused token (sign a new one),
`GeenaOAuthError` the RFC 6749 code, `GeenaTransportError` an unreachable or off-contract
server, and `ReconnectRequired` says the stored tokens cannot be refreshed. The code constants
live in `geena.errors`.

## Layout

```
openapi/            identa's partner-v1.yaml + org-v1.yaml at the pinned release, PIN.yaml
src/geena/
  client.py         GeenaClient: credentials + one connection pool; .oauth .partner .org, claim_url
  app_tokens.py     AppTokenSigner: data tokens, connect hints, claim links
  oauth.py          authorize URL, connect URL, token exchange/refresh/revoke, claims
  pkce.py           verifier, S256 challenge, state
  tokens.py         TokenSet + ensure_fresh
  partner.py        /partner/v1
  org.py            /org/v1
  http.py           transport, error envelope, multipart, streaming downloads
  errors.py         exceptions and the stable codes
  models/           wire shapes, named as the OpenAPI schemas name them
tests/              httpx.MockTransport fakes + the OpenAPI conformance test
```

## Development

```bash
make sync        # uv sync --all-groups
make check       # ruff, ruff format --check, mypy --strict, pytest  (what CI runs)
make openapi-sync IDENTA_TAG=vX.Y.Z   # re-vendor identa's documents; the conformance test shows what changed
```

## Versioning

Each release names the identa tag it was built against, in `openapi/PIN.yaml` and in the
release notes. `0.x` while the Flow integration settles; `1.0` when the first migration runs
on it. Breaking changes in identa's contract become a new minor release here.
