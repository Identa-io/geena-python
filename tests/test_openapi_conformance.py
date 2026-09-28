"""The models are held to identa's OpenAPI documents vendored in ``openapi/``.

For every schema with properties in either document there is a model of the same name in the
matching module, and its wire names (aliases) are exactly the schema's properties. A property
identa adds shows up here as a failing test, which is the point: ``make openapi-sync
IDENTA_TAG=...`` then tells you what to model.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from geena.models import org, partner

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"

#: Request bodies the clients take as plain arguments rather than models.
REQUEST_SCHEMAS = {
    "partner": {
        "AttachRequest",
        "WriteRequest",
        "CreateDocumentRequest",
        "CreateFileForm",
        "SubjectParticipantCreateRequest",
    },
    "org": {
        "AdoptSlotRequest",
        "AttachFileForm",
        "ReplaceFileForm",
        "RelabelFileRequest",
    },
}

#: Schemas the document leaves open (``additionalProperties: true``) — modelled by hand.
OPEN_SCHEMAS = {"partner": {"ServedRecord"}, "org": set[str]()}

#: Spec schemas served under another name in the model module.
RENAMED = {"partner": {"StatusParticipant": "StatusParticipant"}, "org": {}}


def _schemas(name: str) -> dict[str, Any]:
    spec = yaml.safe_load((OPENAPI / f"{name}-v1.yaml").read_text())
    schemas: dict[str, Any] = spec["components"]["schemas"]
    return schemas


def _wire_names(model: type[Any]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


@pytest.mark.parametrize(("plane", "module"), [("partner", partner), ("org", org)])
def test_every_response_schema_has_a_model_with_the_same_wire_names(
    plane: str, module: ModuleType
) -> None:
    mismatches: list[str] = []
    for name, schema in _schemas(plane).items():
        if name in REQUEST_SCHEMAS[plane] or name in OPEN_SCHEMAS[plane]:
            continue
        properties = schema.get("properties")
        if not properties:
            continue  # enums and other primitives
        model = getattr(module, RENAMED[plane].get(name, name), None)
        if model is None:
            mismatches.append(f"{plane}.{name}: no model")
            continue
        expected, actual = set(properties), _wire_names(model)
        if expected != actual:
            mismatches.append(
                f"{plane}.{name}: spec-only={sorted(expected - actual)} "
                f"model-only={sorted(actual - expected)}"
            )
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.parametrize(("plane", "module"), [("partner", partner), ("org", org)])
def test_open_and_request_schemas_are_exactly_the_ones_listed(
    plane: str, module: ModuleType
) -> None:
    schemas = _schemas(plane)
    open_in_spec = {n for n, s in schemas.items() if s.get("additionalProperties") is True}
    assert open_in_spec == OPEN_SCHEMAS[plane]
    for name in OPEN_SCHEMAS[plane]:
        assert getattr(module, name, None) is not None, f"{plane}.{name}: no hand-written model"
    for name in REQUEST_SCHEMAS[plane]:
        assert name in schemas, f"{plane}.{name}: listed as a request schema but not in the spec"


def test_pin_names_the_identa_release() -> None:
    pin = yaml.safe_load((OPENAPI / "PIN.yaml").read_text())
    assert pin["identa_tag"].startswith("v")
    assert pin["partner"] == "pkg/partnerapi/openapi.yaml"
    assert pin["org"] == "pkg/orgapi/openapi.yaml"
