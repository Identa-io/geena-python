"""``/partner/v1``: what a user granted your app, addressed by the connection's ``request_id``.

Every method takes the user's access token: tokens are the integrator's to store and refresh
(:mod:`geena.tokens`). Every act is receipted to the user with your app's client id; reads
included. What was not granted answers ``404 not_found`` — the oracle rule.
"""

from __future__ import annotations

from collections.abc import Mapping

from geena.http import Download, JSONObject, Transport, Upload
from geena.models.common import DocumentData
from geena.models.partner import (
    AttachResponse,
    CandidatesResponse,
    ConnectionsResponse,
    CreateResponse,
    ItemResponse,
    StatusResponse,
    SubjectCandidatesResponse,
    SubjectParticipantCreateResponse,
    WriteResponse,
)

PREFIX = "/partner/v1"


class PartnerClient:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    # -- connections and status --------------------------------------------------------------

    async def list_connections(self, access_token: str) -> ConnectionsResponse:
        """Every active connection your organization holds with the token's user."""
        return ConnectionsResponse.model_validate(
            await self._t.json("GET", f"{PREFIX}/requests", token=access_token)
        )

    async def status(self, access_token: str, request_id: str) -> StatusResponse:
        """The connection's state, groups, subjects, participants and per-slot grant status."""
        return StatusResponse.model_validate(
            await self._t.json("GET", f"{PREFIX}/requests/{request_id}/status", token=access_token)
        )

    # -- reading and writing granted slots ---------------------------------------------------

    async def serve_slot(self, access_token: str, request_id: str, slot_id: str) -> ItemResponse:
        """One record per grant, decrypted at call time; read each record's ``status`` first."""
        return ItemResponse.model_validate(
            await self._t.json(
                "GET", f"{PREFIX}/requests/{request_id}/slots/{slot_id}", token=access_token
            )
        )

    async def download_file(
        self, access_token: str, request_id: str, slot_id: str, file_id: str
    ) -> Download:
        """Stream a granted file's bytes (the record's ``download_url``). Relay the stream to
        your own response; never hand the token to the browser."""
        return await self._t.download(
            f"{PREFIX}/requests/{request_id}/slots/{slot_id}/files/{file_id}", token=access_token
        )

    async def write_slot(
        self,
        access_token: str,
        request_id: str,
        slot_id: str,
        data: DocumentData,
        *,
        name: str | None = None,
    ) -> WriteResponse:
        """A new version of the slot's one granted document (``edit`` verb). ``data`` replaces
        the document wholesale: read, merge, write — never a patch."""
        payload: JSONObject = {"data": data}
        if name:
            payload["name"] = name
        return WriteResponse.model_validate(
            await self._t.json(
                "PUT",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}",
                token=access_token,
                json=payload,
            )
        )

    async def delete_slot(self, access_token: str, request_id: str, slot_id: str) -> None:
        """The user's own hard delete, delegated (``edit`` verb); the grant goes with it."""
        await self._t.json(
            "DELETE", f"{PREFIX}/requests/{request_id}/slots/{slot_id}", token=access_token
        )

    # -- the fill surface (``fill`` verb, user present) ---------------------------------------

    async def candidates(
        self,
        access_token: str,
        request_id: str,
        slot_id: str,
        *,
        participant: str | None = None,
    ) -> CandidatesResponse:
        """What could back the slot, from the user's vault or the named participant's."""
        return CandidatesResponse.model_validate(
            await self._t.json(
                "GET",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}/candidates",
                token=access_token,
                params=_participant(participant),
            )
        )

    async def attach(
        self,
        access_token: str,
        request_id: str,
        slot_id: str,
        resource_id: str,
        *,
        participant: str | None = None,
    ) -> AttachResponse:
        """The user's tap is the approval: grant an existing resource to the slot (idempotent)."""
        body: JSONObject = {"resourceId": resource_id}
        if participant:
            body["participant"] = participant
        return AttachResponse.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}/attach",
                token=access_token,
                json=body,
            )
        )

    async def create_document(
        self,
        access_token: str,
        request_id: str,
        slot_id: str,
        data: DocumentData,
        *,
        name: str | None = None,
        participant: str | None = None,
    ) -> CreateResponse:
        """Always-create: a fresh document in the named vault, granted to the slot in one act."""
        body: JSONObject = {"data": data}
        if name:
            body["name"] = name
        if participant:
            body["participant"] = participant
        return CreateResponse.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}",
                token=access_token,
                json=body,
            )
        )

    async def create_file(
        self,
        access_token: str,
        request_id: str,
        slot_id: str,
        upload: Upload,
        *,
        label: str | None = None,
        participant: str | None = None,
    ) -> CreateResponse:
        """Upload a file into a ``personal_files`` or ``entity_files`` slot and grant it."""
        fields: dict[str, str] = {}
        if label:
            fields["label"] = label
        if participant:
            fields["participant"] = participant
        return CreateResponse.model_validate(
            await self._t.multipart(
                "POST",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}",
                token=access_token,
                upload=upload,
                fields=fields,
            )
        )

    # -- subjects: relatives and companies ---------------------------------------------------

    async def subject_candidates(
        self, access_token: str, request_id: str, subject_id: str
    ) -> SubjectCandidatesResponse:
        """Who could answer a subject: family members of the right relation, or companies
        the user manages right now."""
        return SubjectCandidatesResponse.model_validate(
            await self._t.json(
                "GET",
                f"{PREFIX}/requests/{request_id}/subjects/{subject_id}/candidates",
                token=access_token,
            )
        )

    async def add_participant(
        self, access_token: str, request_id: str, subject_id: str, label: str
    ) -> SubjectParticipantCreateResponse:
        """Mint a family-member vault, or found a company, to answer the subject. Not idempotent."""
        return SubjectParticipantCreateResponse.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/subjects/{subject_id}/participants",
                token=access_token,
                json={"label": label},
            )
        )


def _participant(alias: str | None) -> Mapping[str, str] | None:
    return {"participant": alias} if alias else None
