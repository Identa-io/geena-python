from __future__ import annotations

import io
from urllib.parse import parse_qs

import pytest

from geena import GeenaAPIError, GeenaClient, Upload
from tests.conftest import FakeGeena

REQ = "6f9b2c9e-6a4e-4a44-9d5e-2f0f6f2a9b11"
SLOT = "7c2b9e11-30cf-4f2e-9f57-b8a4f7f4f2ad"


async def test_status_reads_participants_and_treats_null_lists_as_empty(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "GET",
        f"/partner/v1/requests/{REQ}/status",
        json_body={
            "state": "active",
            "groups": None,
            "subjects": [
                {"id": "child", "type": "person", "relation": "child", "repeat": True},
                {"id": "investing-company", "type": "company", "repeat": False},
            ],
            "participants": [{"subjectId": "child", "type": "person", "alias": "c0ffee"}],
            "items": [
                {
                    "slotId": SLOT,
                    "kind": "schema",
                    "target": "PersonAddress",
                    "verbs": ["fill", "keep"],
                    "status": "pending",
                    "multiple": True,
                    "verification": None,
                },
                {
                    "slotId": "s2",
                    "subject": "child",
                    "kind": "schema",
                    "target": "PersonFullName",
                    "verbs": [],
                    "status": "granted",
                },
            ],
        },
    )
    status = await client.partner.status("a-1", REQ)
    assert geena.last().headers["Authorization"] == "Bearer a-1"
    assert status.active and status.groups == []
    assert [s.type for s in status.subjects] == ["person", "company"]
    assert status.subjects[1].relation is None
    assert status.participants[0].alias == "c0ffee"
    pending, granted = status.items
    assert pending.allows("fill") and pending.multiple and not pending.granted
    assert granted.subject == "child" and granted.granted and granted.verbs == []


async def test_served_records_carry_participant_and_unavailable_state(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "GET",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}",
        json_body={
            "slotId": SLOT,
            "subject": "child",
            "kind": "schema",
            "target": "PersonFullName",
            "records": [
                {
                    "resourceId": "r1",
                    "participant": {"subjectId": "child", "type": "person", "alias": "a1"},
                    "type": "document",
                    "version": 3,
                    "data": {"firstName": "Alma"},
                },
                {
                    "resourceId": "r2",
                    "participant": {"subjectId": "child", "type": "person", "alias": "a2"},
                    "status": "unavailable",
                    "reason": "participant_ineligible",
                },
                {
                    "resourceId": "r3",
                    "participant": None,
                    "type": "file",
                    "version": 1,
                    "fileName": "policy.pdf",
                    "downloadUrl": f"/partner/v1/requests/{REQ}/slots/{SLOT}/files/r3",
                },
            ],
        },
    )
    slot = await client.partner.serve_slot("a-1", REQ, SLOT)
    ok, gone, file = slot.records
    assert ok.available and ok.data == {"firstName": "Alma"} and ok.participant is not None
    assert not gone.available and gone.type is None and gone.reason == "participant_ineligible"
    assert file.participant is None and file.file_name == "policy.pdf"


async def test_plane_refusals_become_api_errors(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "POST",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}/attach",
        status=409,
        json_body={"error": "slot_conflict", "message": "the slot's grants changed just now"},
    )
    with pytest.raises(GeenaAPIError) as info:
        await client.partner.attach("a-1", REQ, SLOT, "res-1")
    assert (info.value.status, info.value.code) == (409, "slot_conflict")
    assert info.value.is_conflict
    assert geena.last_json() == {"resourceId": "res-1"}

    geena.on(
        "GET",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}",
        status=403,
        json_body={
            "errors": [{"message": "step-up required", "extensions": {"code": "step_up_required"}}]
        },
    )
    with pytest.raises(GeenaAPIError) as gate:
        await client.partner.serve_slot("a-1", REQ, SLOT)
    assert gate.value.code == "step_up_required" and gate.value.message == "step-up required"


async def test_fill_surface_names_the_participant(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "GET",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}/candidates",
        json_body={
            "slotId": SLOT,
            "kind": "schema",
            "candidates": [
                {
                    "resourceId": "c1",
                    "type": "document",
                    "name": "Home",
                    "createdAt": "2026-09-01T00:00:00Z",
                    "granted": False,
                    "data": {"city": "Amsterdam"},
                }
            ],
        },
    )
    listing = await client.partner.candidates("a-1", REQ, SLOT, participant="c0ffee")
    assert parse_qs(geena.last().url.query.decode()) == {"participant": ["c0ffee"]}
    assert listing.candidates[0].data == {"city": "Amsterdam"}

    geena.on(
        "POST",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}",
        json_body={"slotId": SLOT, "resourceId": "n1", "version": 1, "granted": True},
    )
    created = await client.partner.create_document(
        "a-1", REQ, SLOT, {"firstName": "Alma"}, participant="c0ffee"
    )
    assert created.resource_id == "n1"
    assert geena.last_json() == {"data": {"firstName": "Alma"}, "participant": "c0ffee"}

    geena.on(
        "POST",
        f"/partner/v1/requests/{REQ}/subjects/child/participants",
        json_body={"alias": "new-alias", "label": "Alma"},
    )
    added = await client.partner.add_participant("a-1", REQ, "child", "Alma")
    assert added.alias == "new-alias" and geena.last_json() == {"label": "Alma"}


async def test_file_upload_is_multipart_and_checked_locally(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "POST",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}",
        json_body={"slotId": SLOT, "resourceId": "f1", "version": 1, "granted": True},
    )
    upload = Upload(io.BytesIO(b"%PDF-1.4 ..."), "licence.pdf", "application/pdf")
    result = await client.partner.create_file("a-1", REQ, SLOT, upload, label="Driving licence")
    assert result.resource_id == "f1"
    body = geena.last().content
    assert geena.last().headers["Content-Type"].startswith("multipart/form-data")
    assert (
        b'name="label"' in body and b"Driving licence" in body and b'filename="licence.pdf"' in body
    )

    with pytest.raises(GeenaAPIError) as info:
        await client.partner.create_file("a-1", REQ, SLOT, Upload(io.BytesIO(b""), "empty.bin"))
    assert info.value.code == "invalid_body"


async def test_download_streams_and_relays_headers(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "GET",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}/files/f1",
        content=b"bytes",
        headers={
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="a.pdf"',
        },
    )
    download = await client.partner.download_file("a-1", REQ, SLOT, "f1")
    assert download.headers["content-type"] == "application/pdf"
    assert not download.closed
    assert await download.read() == b"bytes"
    assert download.closed

    geena.on(
        "GET",
        f"/partner/v1/requests/{REQ}/slots/{SLOT}/files/gone",
        status=404,
        json_body={"error": "not_found", "message": ""},
    )
    with pytest.raises(GeenaAPIError) as info:
        await client.partner.download_file("a-1", REQ, SLOT, "gone")
    assert info.value.is_not_found
