"""Wire shapes for both planes, named as identa's OpenAPI documents name them.

The classes here are hand-written pydantic models that read Geena's camelCase JSON by alias,
ignore fields they do not know, and treat a ``null`` list as empty.
``tests/test_openapi_conformance.py``
holds them to the vendored OpenAPI documents in ``openapi/``: every response schema has a model
of the same name whose fields are exactly the schema's properties.
"""

from geena.models import org, partner
from geena.models.common import (
    COMPANY,
    LEGAL_ENTITY,
    PERSON,
    DocumentData,
    ParticipantRef,
    Payload,
)

__all__ = [
    "COMPANY",
    "LEGAL_ENTITY",
    "PERSON",
    "DocumentData",
    "ParticipantRef",
    "Payload",
    "org",
    "partner",
]
