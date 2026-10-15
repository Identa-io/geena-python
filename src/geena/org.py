"""``/org/v1``: what your organization holds, with a member-bound token.

The token is either an app token your app signed for a member it connected
(:mod:`geena.app_tokens`), or a partner access token whose consent carries the ``organization``
scope (an organization-access ceremony, see :mod:`geena.oauth`). Every call re-checks that the
member is still active and that their role covers the act: ``request_read`` to read requests,
``request_manage`` to import, keep, correct and decide, plus the file permissions to attach
files. An organization key the member's context cannot open answers ``423 org_sealed``: the
member has not activated their membership by signing in to Geena yet.
"""

from __future__ import annotations

from geena.http import Download, JSONObject, Transport, Upload
from geena.models.org import (
    Adoption,
    AdoptionsResponse,
    CopiesResponse,
    CopyCorrectionResult,
    CorrectCopyRequest,
    DrainResponse,
    ImportRequest,
    ImportResult,
    Manifest,
    PendingVersionsResponse,
    RejectResponse,
    RemovedFileResponse,
    RequestDetailResponse,
    RequestFile,
    RequestFilesResponse,
    RequestsResponse,
)

PREFIX = "/org/v1"


class OrgClient:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    # -- requests and records ----------------------------------------------------------------

    async def list_requests(self, token: str, *, email: str | None = None) -> RequestsResponse:
        """Every request the organization holds, newest first. ``email`` narrows the list to
        one recipient."""
        return RequestsResponse.model_validate(
            await self._t.json(
                "GET",
                f"{PREFIX}/requests",
                token=token,
                params={"email": email} if email else None,
            )
        )

    async def request(self, token: str, request_id: str) -> RequestDetailResponse:
        """One request in full: items with their records, the kept copies, the pending
        versions."""
        return RequestDetailResponse.model_validate(
            await self._t.json("GET", f"{PREFIX}/requests/{request_id}", token=token)
        )

    async def manifest(self, token: str, manifest_id: str) -> Manifest:
        """The manifest's newest published version: its subjects and slots, with the slot ids
        an import maps your fields onto."""
        return Manifest.model_validate(
            await self._t.json("GET", f"{PREFIX}/manifests/{manifest_id}", token=token)
        )

    # -- importing investors -----------------------------------------------------------------

    async def import_investor(self, token: str, investor: ImportRequest) -> ImportResult:
        """Bring one investor your organization already serves into Geena, in one transaction.

        People are found by your app's ``sub`` for them, or created as held accounts that your
        app's tokens reach until they claim. The request is found by ``external_ref`` or
        created, active, with every held person on it; every non-empty value becomes the first
        version of a copy your organization keeps. Nothing reaches anyone's own vault and no mail
        is sent. A re-run adds what is new and never overwrites (correct a copy instead).
        Requires ``request_manage``; ``400 import_refused`` names what to fix.
        """
        return ImportResult.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/imports",
                token=token,
                json=investor.model_dump(by_alias=True, exclude_none=True),
            )
        )

    # -- kept copies -------------------------------------------------------------------------

    async def adopt(
        self, token: str, request_id: str, slot_id: str, *, participant: str | None = None
    ) -> AdoptionsResponse:
        """Keep the slot's current version(s): every party, or one ``participant``. Always
        read ``skipped``."""
        body: JSONObject | None = {"participant": participant} if participant else None
        return AdoptionsResponse.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}/adopt",
                token=token,
                json=body,
            )
        )

    async def drain(self, token: str, request_id: str) -> DrainResponse:
        """Retry the request's adoptions that queued as pending on a cold key."""
        return DrainResponse.model_validate(
            await self._t.json(
                "POST", f"{PREFIX}/requests/{request_id}/adoptions/drain", token=token
            )
        )

    async def copies(self, token: str, request_id: str) -> CopiesResponse:
        """The values of every materialized copy: ``data`` as kept, ``current_data`` the head."""
        return CopiesResponse.model_validate(
            await self._t.json("GET", f"{PREFIX}/requests/{request_id}/copies", token=token)
        )

    async def download_copy(self, token: str, request_id: str, adoption_id: str) -> Download:
        """The bytes of a kept file, at the version THIS adoption kept."""
        return await self._t.download(
            f"{PREFIX}/requests/{request_id}/copies/{adoption_id}/download", token=token
        )

    async def correct(
        self, token: str, request_id: str, slot_id: str, correction: CorrectCopyRequest
    ) -> CopyCorrectionResult:
        """Append the organization's own revision to a kept copy's chain. The person's data is
        never touched."""
        return CopyCorrectionResult.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/slots/{slot_id}/correct",
                token=token,
                json=correction.model_dump(by_alias=True, exclude_none=True),
            )
        )

    # -- request files -----------------------------------------------------------------------

    async def files(self, token: str, request_id: str) -> RequestFilesResponse:
        """One row per file, at its head: kept copies and the organization's own attachments."""
        return RequestFilesResponse.model_validate(
            await self._t.json("GET", f"{PREFIX}/requests/{request_id}/files", token=token)
        )

    async def file_history(self, token: str, request_id: str, file_id: str) -> RequestFilesResponse:
        """Every version of one file, newest first."""
        return RequestFilesResponse.model_validate(
            await self._t.json(
                "GET", f"{PREFIX}/requests/{request_id}/files/{file_id}/history", token=token
            )
        )

    async def attach_file(
        self,
        token: str,
        request_id: str,
        upload: Upload,
        *,
        label: str | None = None,
        slot_id: str | None = None,
    ) -> RequestFile:
        """Attach one of the organization's own files to the request (``file_create``)."""
        fields: dict[str, str] = {}
        if label:
            fields["label"] = label
        if slot_id:
            fields["slotId"] = slot_id
        return RequestFile.model_validate(
            await self._t.multipart(
                "POST",
                f"{PREFIX}/requests/{request_id}/files",
                token=token,
                upload=upload,
                fields=fields,
            )
        )

    async def replace_file(
        self,
        token: str,
        request_id: str,
        file_id: str,
        upload: Upload,
        *,
        expected_org_version: int,
    ) -> RequestFile:
        """The next version of an attached file, pinned to the version you read; ``409`` when
        that version is no longer the head."""
        return RequestFile.model_validate(
            await self._t.multipart(
                "PUT",
                f"{PREFIX}/requests/{request_id}/files/{file_id}",
                token=token,
                upload=upload,
                fields={"expectedOrgVersion": str(expected_org_version)},
            )
        )

    async def relabel_file(
        self, token: str, request_id: str, file_id: str, label: str
    ) -> RequestFile:
        """Rename an attached file: same bytes, new label, a row saying who and when."""
        return RequestFile.model_validate(
            await self._t.json(
                "PATCH",
                f"{PREFIX}/requests/{request_id}/files/{file_id}",
                token=token,
                json={"label": label},
            )
        )

    async def remove_file(self, token: str, request_id: str, file_id: str) -> RemovedFileResponse:
        """Delete an attached file, every version and its bytes (a kept copy is refused)."""
        return RemovedFileResponse.model_validate(
            await self._t.json(
                "DELETE", f"{PREFIX}/requests/{request_id}/files/{file_id}", token=token
            )
        )

    async def download_file(
        self, token: str, request_id: str, file_id: str, *, version: int | None = None
    ) -> Download:
        """One version's bytes (the head when ``version`` is None)."""
        return await self._t.download(
            f"{PREFIX}/requests/{request_id}/files/{file_id}/download",
            token=token,
            params={"version": str(version)} if version is not None else None,
        )

    # -- pending versions --------------------------------------------------------------------

    async def pending(self, token: str, request_id: str) -> PendingVersionsResponse:
        """The versions of your copies waiting for a member: a person's update on a manual
        slot, or a correction someone on the connection proposed — with their values beside
        the copy's head."""
        return PendingVersionsResponse.model_validate(
            await self._t.json("GET", f"{PREFIX}/requests/{request_id}/pending", token=token)
        )

    async def accept_pending(
        self, token: str, request_id: str, resource_id: str, version: int
    ) -> Adoption:
        """Accept a pending version: it becomes the head everyone reads, the keep recorded."""
        return Adoption.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/pending/{resource_id}/{version}/accept",
                token=token,
            )
        )

    async def reject_pending(
        self, token: str, request_id: str, resource_id: str, version: int
    ) -> RejectResponse:
        """Reject a pending version: the head stays, the rejected version stays on record."""
        return RejectResponse.model_validate(
            await self._t.json(
                "POST",
                f"{PREFIX}/requests/{request_id}/pending/{resource_id}/{version}/reject",
                token=token,
            )
        )
