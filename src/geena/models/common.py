"""What both planes share: the tolerant base model, document data, and the participant handle."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: A document's ``data``: a schema-typed JSON object Geena validates; relayed untouched.
DocumentData = dict[str, Any]

#: Participant types. The partner plane speaks to apps about people and companies; the
#: organization plane speaks the manifest's own vocabulary (``person`` | ``legal_entity``).
PERSON = "person"
COMPANY = "company"
LEGAL_ENTITY = "legal_entity"


class Payload(BaseModel):
    """Geena's JSON is camelCase and may grow fields: read by alias, ignore extras.

    Only the fields a caller cannot do without are required; what the server always sends
    but a reader can live without (timestamps, kinds, routes) is optional, so a partial
    fixture or an older server never turns a whole response into a validation error.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _null_lists_are_empty(cls, value: object) -> object:
        """Go may encode an empty slice as ``null``; a missing list is an empty list."""
        if not isinstance(value, dict):
            return value
        result = dict(value)
        for name, field in cls.model_fields.items():
            key = field.alias or name
            if result.get(key, ...) is None and field.default_factory is list:
                result[key] = []
        return result


class ParticipantRef(Payload):
    """One party answering a manifest subject, by its pairwise alias — never a vault id.

    ``alias`` is stable across this organization's connections with the party and meaningless
    to any other organization. ``type`` is ``person`` or ``company`` on the partner plane and
    ``person`` or ``legal_entity`` on the organization plane. A record's ``participant`` is
    ``None`` for the recipient's own data.
    """

    subject_id: str = Field(alias="subjectId")
    type: str
    alias: str
