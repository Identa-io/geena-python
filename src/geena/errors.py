"""The four ways a call to Geena fails, and the stable codes the planes answer with.

Geena's planes refuse with ``{"error": "<code>", "message": "..."}`` and a stable machine-readable
code; the security gate (a missing scope, a step-up owed) answers ``403`` with the platform's
``{"errors": [{"message", "extensions": {"code"}}]}`` envelope instead. Both surface here as
:class:`GeenaAPIError` with the code in ``.code``. Token-endpoint refusals follow RFC 6749 and
surface as :class:`GeenaOAuthError`.
"""

from __future__ import annotations


class GeenaError(Exception):
    """Base class: anything that went wrong talking to Geena."""


class GeenaTransportError(GeenaError):
    """Geena was unreachable or answered outside its contract (not JSON, not an object)."""


class GeenaOAuthError(GeenaError):
    """A token endpoint refused with an RFC 6749 error code (``invalid_grant``, ...)."""

    def __init__(self, code: str, description: str = "") -> None:
        super().__init__(description or code)
        self.code = code
        self.description = description

    @property
    def interaction_required(self) -> bool:
        """The user's consent is gone: nothing but a new ceremony will mint tokens."""
        return self.code == "interaction_required"


class GeenaAPIError(GeenaError):
    """A partner- or organization-plane route refused; ``status`` and ``code`` say why."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or f"{code} ({status})")
        self.status = status
        self.code = code
        self.message = message

    @property
    def is_not_found(self) -> bool:
        """The oracle answer: ungranted, foreign, malformed or nonexistent, deliberately one."""
        return self.status == 404

    @property
    def is_sealed(self) -> bool:
        """A vault key is cold (``sealed`` needs the user's step-up, ``org_sealed`` a member's)."""
        return self.status == 423

    @property
    def is_conflict(self) -> bool:
        """Re-read and retry: a concurrent fill, a stale version pin, a casting race."""
        return self.status == 409

    @property
    def connection_inactive(self) -> bool:
        return self.code == "connection_inactive"


class ReconnectRequired(GeenaError):
    """The stored tokens cannot be made fresh: no refresh token, or the refresh was refused.

    The only way forward is a new ceremony. Raised by :func:`geena.tokens.ensure_fresh`.
    """


# Codes both planes share.
NOT_FOUND = "not_found"
SEALED = "sealed"
ORG_SEALED = "org_sealed"
SERVER_ERROR = "server_error"
CONNECTION_INACTIVE = "connection_inactive"

# Partner plane.
VERB_NOT_GRANTED = "verb_not_granted"
SLOT_CONFLICT = "slot_conflict"
PARTICIPANT_REQUIRED = "participant_required"
PARTICIPANT_NOT_ALLOWED = "participant_not_allowed"
PARTICIPANT_UNKNOWN = "participant_unknown"
PARTICIPANT_INELIGIBLE = "participant_ineligible"
PARTICIPANT_CONFLICT = "participant_conflict"
SUBJECT_ITEM_READONLY = "subject_item_readonly"
SUBJECT_KIND_UNSUPPORTED = "subject_kind_unsupported"
DELETE_REFUSED = "delete_refused"
UNSUPPORTED_ITEM = "unsupported_item"
INVALID_DOCUMENT = "invalid_document"
TOO_LARGE = "too_large"

# Organization plane.
NOT_A_MEMBER = "not_a_member"
ROLE_INSUFFICIENT = "role_insufficient"
ADOPTION_REFUSED = "adoption_refused"
VERSION_CONFLICT = "version_conflict"

# Record-level reasons (a served or listed record with ``status: "unavailable"``).
RECORD_UNREADABLE = "record_unreadable"
SOURCE_UNAVAILABLE = "source_unavailable"
