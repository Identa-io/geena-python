# geena-python

The Python client library for Geena's partner integration surface — the `geena` package.

It wraps what a partner's backend needs to hold a connection with a Geena user and to act for its
own organization:

- the **connect ceremony**: the authorize URL with PKCE and `manifest_id` (or `scope=organization`
  for the back-office sign-in), the code exchange, refresh with rotation, revocation, step-up;
- the **Partner API** (`/partner/v1`): status, serving, filling, participants;
- the **Organization API** (`/org/v1`): requests, records, kept copies, corrections, files,
  update proposals.

Models are generated from identa's OpenAPI documents (`pkg/partnerapi/openapi.yaml`,
`pkg/orgapi/openapi.yaml`); the OAuth layer is hand-written. Storage (connection rows, org
sessions, OAuth state) sits behind protocols so any backend can plug its own in.

The first extraction comes from the Flow fork's `backend/app/geena/` module
(`Identa-io/dff-flow-mark-2`, branch `feature/geena-flow-v2`), which stays the worked example.

Every release names the identa tag it was built against. Nothing here yet — 0.1.0 targets
identa v0.36.0.

Documentation for the API itself: https://docs.test.geena.eu/
