"""The `geena` package: a Python client for Geena's partner integration surface.

Three layers, one entry point:

- :class:`GeenaClient` holds the app's credentials and one HTTP connection pool, and exposes
  ``.oauth`` (the connect ceremony and tokens), ``.partner`` (``/partner/v1``: what a user
  granted your app) and ``.org`` (``/org/v1``: what your organization holds).
- :mod:`geena.tokens` keeps a user's or a member's tokens fresh; where they are stored, and who
  holds the lock while they rotate, is the integrator's decision.
- :mod:`geena.models` are the wire shapes, checked against identa's OpenAPI documents by the
  test suite (``openapi/PIN.yaml`` names the identa release they match).
"""

from importlib.metadata import PackageNotFoundError, version

from geena.client import GeenaClient
from geena.errors import (
    GeenaAPIError,
    GeenaError,
    GeenaOAuthError,
    GeenaTransportError,
    ReconnectRequired,
)
from geena.http import Download, Upload
from geena.oauth import ORGANIZATION_SCOPE, OAuthClient, StepUpHandoff, TokenClaims, TokenResponse
from geena.org import OrgClient
from geena.partner import PartnerClient
from geena.tokens import TokenSet, ensure_fresh

try:
    __version__ = version("geena")
except PackageNotFoundError:  # pragma: no cover - source checkout without an install
    __version__ = "0.0.0"

__all__ = [
    "ORGANIZATION_SCOPE",
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
    "StepUpHandoff",
    "TokenClaims",
    "TokenResponse",
    "TokenSet",
    "Upload",
    "__version__",
    "ensure_fresh",
]
