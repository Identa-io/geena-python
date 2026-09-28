# geena-python

The Python client for Geena's partner integration surface — the `geena` package.

A partner's backend uses it to hold a **connection** with a Geena user and to act for its own
organization:

- the **connect ceremony** (`geena.oauth`, `geena.pkce`): the authorize URL with PKCE and
  `manifest_id`, or `scope=ORGANIZATION_SCOPE` for the back-office sign-in; the code exchange;
  refresh with rotation; revocation; the step-up hand-off;
- the **Partner API** (`/partner/v1`, `geena.partner`): connections, status, serving, filling,
  participants (relatives and companies);
- the **Organization API** (`/org/v1`, `geena.org`): requests and records, kept copies and
  corrections, request files, update proposals;
- **token custody** (`geena.tokens`): a `TokenSet` per connection and `ensure_fresh()`; where
  tokens are stored and who holds the lock while they rotate stays the integrator's decision.

The API itself is documented at https://docs.test.geena.eu/. This package follows that contract:
`openapi/` holds identa's two OpenAPI documents at the release the package was built against
(`openapi/PIN.yaml`), and the test suite holds every model to them.

## Status

`0.1.0.dev0`, pinned to identa **v0.36.0**. Installable from the repository until the first tag:

```bash
pip install "git+https://github.com/Identa-io/geena-python@main"
```

Python 3.11 or newer; depends on `httpx` and `pydantic` v2 only.

## Quickstart

```python
from geena import GeenaClient, ORGANIZATION_SCOPE, TokenSet, ensure_fresh
from geena.pkce import challenge_for, new_state, new_verifier

geena = GeenaClient(
    "https://api.test.geena.eu",
    client_id="acme-portal",
    client_secret=SECRET,  # backend only, never in a browser
    dashboard_base_url="https://dashboard.test.geena.eu",  # deep links + the step-up page
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
`code` (`not_found`, `slot_conflict`, `participant_ineligible`, `org_sealed`, ...),
`GeenaOAuthError` the RFC 6749 code, `GeenaTransportError` an unreachable or off-contract
server, and `ReconnectRequired` says the stored tokens cannot be refreshed. The code constants
live in `geena.errors`.

## Layout

```
openapi/            identa's partner-v1.yaml + org-v1.yaml at the pinned release, PIN.yaml
src/geena/
  client.py         GeenaClient: credentials + one connection pool; .oauth .partner .org
  oauth.py          authorize URL, token exchange/refresh/revoke, step-up, claims
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
make openapi-sync IDENTA_TAG=v0.37.0   # re-vendor identa's documents; the conformance test shows what changed
```

## Versioning

Each release names the identa tag it was built against, in `openapi/PIN.yaml` and in the
release notes. `0.x` while the Flow integration settles; `1.0` when the first migration runs
on it. Breaking changes in identa's contract become a new minor release here.
