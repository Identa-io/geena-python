"""The `geena` package: a Python client for Geena's partner integration surface.

Four layers, one entry point:

- :class:`GeenaClient` holds the app's credentials and one HTTP connection pool, and exposes
  ``.oauth`` (the connect ceremony and tokens), ``.partner`` (``/partner/v1``: what a user
  granted your app) and ``.org`` (``/org/v1``: what your organization holds).
- :mod:`geena.app_tokens` signs your app's own tokens when it signs its users in itself: data
  tokens for both planes, connect hints for your staff, claim links for the people you imported.
- :mod:`geena.tokens` keeps a user's or a member's OAuth tokens fresh; where they are stored,
  and who holds the lock while they rotate, is the integrator's decision.
- :mod:`geena.models` are the wire shapes, checked against identa's OpenAPI documents by the
  test suite (``openapi/PIN.yaml`` names the identa release they match).
"""

from importlib.metadata import PackageNotFoundError, version

from geena.app_tokens import AppToken, AppTokenSigner, TokenUse
from geena.client import GeenaClient
from geena.errors import (
    GeenaAPIError,
    GeenaError,
    GeenaOAuthError,
    GeenaTransportError,
    ReconnectRequired,
)
from geena.http import Download, Upload
from geena.oauth import (
    CONNECT_SCOPE,
    ORGANIZATION_SCOPE,
    OAuthClient,
    TokenClaims,
    TokenResponse,
)
from geena.org import OrgClient
from geena.partner import PartnerClient
from geena.tokens import TokenSet, ensure_fresh

try:
    __version__ = version("geena")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = [
    "CONNECT_SCOPE",
    "ORGANIZATION_SCOPE",
    "AppToken",
    "AppTokenSigner",
    "Download",
    "GeenaAPIError",
    "GeenaClient",
    "GeenaError",
    "GeenaOAuthError",
    "GeenaTransportError",
    "OAuthClient",
    "OrgClient",
    "PartnerClient",
    "ReconnectRequired",
    "TokenClaims",
    "TokenResponse",
    "TokenSet",
    "TokenUse",
    "Upload",
    "__version__",
    "ensure_fresh",
]
