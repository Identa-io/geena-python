from __future__ import annotations

import io
from urllib.parse import parse_qs

import pytest

from geena import GeenaAPIError, GeenaClient, Upload
from geena.models.org import CorrectCopyRequest, ImportPerson, ImportRequest, ImportValue
from tests.conftest import FakeGeena

REQ = "6f9b2c9e-6a4e-4a44-9d5e-2f0f6f2a9b11"
SLOT = "7c2b9e11-30cf-4f2e-9f57-b8a4f7f4f2ad"
ADOPTION = {
    "adoptionId": "ad-1",
    "slotId": SLOT,
    "itemKind": "schema",
    "itemTarget": "PersonBankAccount",
    "sourceResourceId": "src-1",
    "sourceVersion": 4,
    "orgResourceId": "org-1",
    "orgVersion": 2,
    "resourceType": "document",
    "state": "materialized",
    "adoptedAt": "2026-09-02T09:00:00Z",
    "materializedAt": "2026-09-02T09:00:00Z",
    "participant": None,
}


async def test_list_requests_narrows_by_email(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "GET",
        "/org/v1/requests",
        json_body={
            "requests": [
                {
                    "requestId": REQ,
                    "manifestId": "m-1",
                    "manifestVersion": 3,
                    "recipientEmail": "anna@example.com",
                    "state": "active",
                    "initiatedBy": "recipient",
                    "initiatingClientId": "acme-portal",
                    "externalRef": "investor-118",
                    "invitationExpiresAt": "2026-10-01T00:00:00Z",
                    "createdAt": "2026-09-01T10:12:00Z",
                }
            ]
        },
    )
    listing = await client.org.list_requests("m-tok", email="anna@example.com")
    assert parse_qs(geena.last().url.query.decode()) == {"email": ["anna@example.com"]}
    assert listing.requests[0].active and listing.requests[0].initiating_client_id == "acme-portal"
    assert listing.requests[0].external_ref == "investor-118"


async def test_request_detail_records_name_their_party(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "GET",
        f"/org/v1/requests/{REQ}",
        json_body={
            "request": {
                "requestId": REQ,
                "manifestId": "m-1",
                "manifestVersion": 3,
                "recipientEmail": "a@x",
                "state": "active",
                "initiatedBy": "org",
                "invitationExpiresAt": "2026-10-01T00:00:00Z",
                "createdAt": "2026-09-01T10:12:00Z",
            },
            "manifestName": "Investor onboarding",
            "items": [
                {
                    "slotId": SLOT,
                    "multiple": False,
                    "kind": "schema",
                    "target": "LegalEntity",
                    "verbs": ["fill", "edit", "keep"],
                    "adoption": "auto",
                    "status": "granted",
                    "subject": "investing-company",
                    "records": [
                        {
                            "resourceId": "e41c",
                            "status": "unavailable",
                            "reason": "participant_ineligible",
                            "participant": {
                                "subjectId": "investing-company",
                                "type": "legal_entity",
                                "alias": "9a7f",
                            },
                        }
                    ],
                }
            ],
            "adoptions": [ADOPTION],
            "pending": None,
        },
    )
    detail = await client.org.request("m-tok", REQ)
    item = detail.items[0]
    assert item.granted and item.adoption == "auto"
    record = item.records[0]
    assert not record.available and record.source_version is None
    assert record.participant is not None and record.participant.type == "legal_entity"
    assert detail.adoptions[0].materialized and detail.pending == []


async def test_adopt_per_participant_reports_skipped(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "POST",
        f"/org/v1/requests/{REQ}/slots/{SLOT}/adopt",
        json_body={
            "adoptions": [ADOPTION],
            "skipped": [
                {
                    "resourceId": "e41c",
                    "participant": None,
                    "reason": "participant_ineligible",
                    "message": "the recipient no longer manages this company",
                }
            ],
        },
    )
    kept = await client.org.adopt("m-tok", REQ, SLOT, participant="9a7f")
    assert geena.last_json() == {"participant": "9a7f"}
    assert len(kept.adoptions) == 1 and kept.skipped[0].reason == "participant_ineligible"

    await client.org.adopt("m-tok", REQ, SLOT)
    assert geena.last().content == b"", "no body keeps every record of the slot"


async def test_copies_expose_the_head_and_pin_a_correction(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "GET",
        f"/org/v1/requests/{REQ}/copies",
        json_body={
            "copies": [
                {
                    "adoption": ADOPTION,
                    "resourceId": "org-1",
                    "name": "Payout account",
                    "schemaRef": "https://schema.geena.eu/core/PersonBankAccount.json",
                    "data": {"bankName": "Nya Banken"},
                    "orgVersion": 2,
                    "origin": "copy",
                    "currentOrgVersion": 3,
                    "currentOrigin": "correction",
                    "currentData": {"bankName": "Nya Banken AB"},
                    "participant": None,
                }
            ]
        },
    )
    copies = await client.org.copies("m-tok", REQ)
    copy = copies.copies[0]
    assert copy.values == {"bankName": "Nya Banken AB"} and copy.data == {"bankName": "Nya Banken"}

    correction = CorrectCopyRequest.for_copy(copy, {"bankName": "Nya Banken AB", "currency": "SEK"})
    geena.on(
        "POST",
        f"/org/v1/requests/{REQ}/slots/{SLOT}/correct",
        json_body={"adoption": ADOPTION, "orgVersion": 4},
    )
    result = await client.org.correct("m-tok", REQ, SLOT, correction)
    assert result.org_version == 4
    assert geena.last_json() == {
        "sourceResourceId": "src-1",
        "expectedSourceVersion": 4,
        "expectedOrgVersion": 3,
        "data": {"bankName": "Nya Banken AB", "currency": "SEK"},
    }

    geena.on(
        "POST",
        f"/org/v1/requests/{REQ}/slots/{SLOT}/correct",
        status=409,
        json_body={"error": "version_conflict", "message": "stale"},
    )
    with pytest.raises(GeenaAPIError) as info:
        await client.org.correct("m-tok", REQ, SLOT, correction)
    assert info.value.code == "version_conflict" and info.value.is_conflict


async def test_request_files_round_trip(client: GeenaClient, geena: FakeGeena) -> None:
    row = {
        "fileId": "f-1",
        "origin": "added",
        "orgVersion": 1,
        "fileName": "agreement.pdf",
        "fileSize": 12,
        "mimeType": "application/pdf",
        "writtenBy": "member-1",
        "writtenAt": "2026-09-05T14:20:00Z",
        "downloadUrl": f"/org/v1/requests/{REQ}/files/f-1/download?version=1",
    }
    geena.on("POST", f"/org/v1/requests/{REQ}/files", json_body=row)
    attached = await client.org.attach_file(
        "m-tok",
        REQ,
        Upload(io.BytesIO(b"%PDF-1.4 agree"), "agreement.pdf"),
        label="Signed agreement",
    )
    assert not attached.kept and attached.display_name == "agreement.pdf"
    assert b'name="label"' in geena.last().content

    geena.on("PUT", f"/org/v1/requests/{REQ}/files/f-1", json_body={**row, "orgVersion": 2})
    replaced = await client.org.replace_file(
        "m-tok",
        REQ,
        "f-1",
        Upload(io.BytesIO(b"%PDF-1.4 v2"), "agreement-v2.pdf"),
        expected_org_version=1,
    )
    assert replaced.org_version == 2 and b'name="expectedOrgVersion"' in geena.last().content

    geena.on(
        "PATCH", f"/org/v1/requests/{REQ}/files/f-1", json_body={**row, "label": "Countersigned"}
    )
    assert (
        await client.org.relabel_file("m-tok", REQ, "f-1", "Countersigned")
    ).label == "Countersigned"

    geena.on(
        "GET",
        f"/org/v1/requests/{REQ}/files/f-1/download",
        content=b"v1",
        headers={"Content-Type": "application/pdf"},
    )
    download = await client.org.download_file("m-tok", REQ, "f-1", version=1)
    assert parse_qs(geena.last().url.query.decode()) == {"version": ["1"]}
    assert await download.read() == b"v1"

    geena.on("DELETE", f"/org/v1/requests/{REQ}/files/f-1", json_body={"fileId": "f-1"})
    assert (await client.org.remove_file("m-tok", REQ, "f-1")).file_id == "f-1"


async def test_pending_versions_are_decided_by_chain_and_version(
    client: GeenaClient, geena: FakeGeena
) -> None:
    pending = {
        "resourceId": "org-1",
        "version": 3,
        "slotId": SLOT,
        "itemKind": "schema",
        "itemTarget": "PersonPhone",
        "sourceVersion": 4,
        "proposedAt": "2026-10-14T08:00:00Z",
        "origin": "user_correction",
        "participant": None,
        "name": "Phone",
        "proposed": {"phoneNumber": "+31 6 1234 5678"},
        "current": {"phoneNumber": "+31 6 0000 0000"},
        "currentOrgVersion": 2,
    }
    geena.on("GET", f"/org/v1/requests/{REQ}/pending", json_body={"pending": [pending]})
    listed = (await client.org.pending("m-tok", REQ)).pending[0]
    assert listed.is_correction and listed.proposed == {"phoneNumber": "+31 6 1234 5678"}
    assert listed.current_org_version == 2

    geena.on(
        "POST",
        f"/org/v1/requests/{REQ}/pending/org-1/3/accept",
        json_body={**ADOPTION, "orgVersion": 3},
    )
    accepted = await client.org.accept_pending("m-tok", REQ, "org-1", 3)
    assert accepted.org_version == 3

    geena.on("POST", f"/org/v1/requests/{REQ}/pending/org-1/3/reject", json_body={"rejected": True})
    assert (await client.org.reject_pending("m-tok", REQ, "org-1", 3)).rejected


async def test_import_sends_the_wire_names_and_reads_the_result(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "POST",
        "/org/v1/imports",
        json_body={
            "requestId": REQ,
            "requestCreated": True,
            "people": [
                {"sub": "c-1", "role": "owner", "accountCreated": True, "added": True},
                {"sub": "c-2", "role": "contact", "accountCreated": False, "added": True},
            ],
            "recordsCreated": 3,
            "recordsSkipped": 0,
        },
    )
    result = await client.org.import_investor(
        "staff-tok",
        ImportRequest(
            client_id="dff-client",
            manifest_id="m-1",
            external_ref="investor-118",
            kind="company",
            people=[
                ImportPerson(sub="c-1", email="owner@example.com", role="owner"),
                ImportPerson(sub="c-2", email="contact@example.com", role="contact"),
            ],
            values=[
                ImportValue(slot_id=SLOT, data={"firstName": "Henrik"}),
                ImportValue(slot_id=SLOT, person="c-2", data={"firstName": "Marta"}),
            ],
        ),
    )
    assert geena.last_json() == {
        "clientId": "dff-client",
        "manifestId": "m-1",
        "externalRef": "investor-118",
        "kind": "company",
        "people": [
            {"sub": "c-1", "email": "owner@example.com", "role": "owner"},
            {"sub": "c-2", "email": "contact@example.com", "role": "contact"},
        ],
        "values": [
            {"slotId": SLOT, "data": {"firstName": "Henrik"}},
            {"slotId": SLOT, "person": "c-2", "data": {"firstName": "Marta"}},
        ],
    }
    assert result.request_created and result.records_created == 3
    assert [p.account_created for p in result.people] == [True, False]

    geena.on(
        "POST",
        "/org/v1/imports",
        status=400,
        json_body={"error": "import_refused", "message": "a company needs exactly one owner"},
    )
    with pytest.raises(GeenaAPIError) as refused:
        await client.org.import_investor(
            "staff-tok",
            ImportRequest(
                client_id="dff-client", manifest_id="m-1", external_ref="x", kind="company"
            ),
        )
    assert refused.value.code == "import_refused"


async def test_the_manifest_names_the_slot_an_import_maps_onto(
    client: GeenaClient, geena: FakeGeena
) -> None:
    geena.on(
        "GET",
        "/org/v1/manifests/m-1",
        json_body={
            "manifestId": "m-1",
            "version": 2,
            "name": "DFF investor onboarding",
            "subjects": [{"id": "company", "type": "company", "repeat": False}],
            "items": [
                {
                    "slotId": "s-name",
                    "multiple": False,
                    "kind": "schema",
                    "target": "PersonFullName",
                    "verbs": ["fill", "edit", "keep"],
                },
                {
                    "slotId": "s-entity",
                    "multiple": False,
                    "kind": "schema",
                    "target": "LegalEntity",
                    "subject": "company",
                    "verbs": ["fill"],
                },
            ],
        },
    )
    manifest = await client.org.manifest("staff-tok", "m-1")
    assert manifest.slot("PersonFullName").slot_id == "s-name"
    assert manifest.slot("LegalEntity", subject="company").slot_id == "s-entity"
    with pytest.raises(LookupError):
        manifest.slot("LegalEntity")


async def test_org_sealed_is_a_423(client: GeenaClient, geena: FakeGeena) -> None:
    geena.on(
        "GET",
        f"/org/v1/requests/{REQ}/copies",
        status=423,
        json_body={"error": "org_sealed", "message": "the organization's key is cold"},
    )
    with pytest.raises(GeenaAPIError) as info:
        await client.org.copies("m-tok", REQ)
    assert info.value.is_sealed and info.value.code == "org_sealed"
