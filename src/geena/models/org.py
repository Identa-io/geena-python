"""``/org/v1`` shapes — see openapi/org-v1.yaml, whose schema names these classes carry."""

from __future__ import annotations

from pydantic import Field

from geena.models.common import DocumentData, ParticipantRef, Payload


class Error(Payload):
    error: str
    message: str = ""


class Request(Payload):
    """One manifest version sent to one person; accepted, it is the connection."""

    request_id: str = Field(alias="requestId")
    manifest_id: str = Field(alias="manifestId")
    manifest_version: int = Field(alias="manifestVersion")
    manifest_name: str | None = Field(default=None, alias="manifestName")
    recipient_email: str = Field(alias="recipientEmail")
    #: ``pending``, ``active``, ``rejected_by_sender``, ``rejected_by_recipient``, ``expired``,
    #: ``revoked``, ``suspended`` — evaluated at call time on both clocks.
    state: str
    #: ``org`` (sent from the dashboard) or ``recipient`` (opened from an app's ceremony).
    initiated_by: str = Field(alias="initiatedBy")
    initiating_client_id: str | None = Field(default=None, alias="initiatingClientId")
    invitation_expires_at: str = Field(alias="invitationExpiresAt")
    created_at: str = Field(alias="createdAt")

    @property
    def active(self) -> bool:
        return self.state == "active"


class RequestsResponse(Payload):
    requests: list[Request] = Field(default_factory=list)


class RequestItemRecord(Payload):
    """One standing grant of an item: whose it is, where the source stands, and whether it
    can still be acted on."""

    resource_id: str = Field(alias="resourceId")
    #: ``None`` for the recipient's own item.
    participant: ParticipantRef | None = None
    #: The version the person's resource stands at now; absent on ``unavailable`` records.
    source_version: int | None = Field(default=None, alias="sourceVersion")
    #: ``available`` or ``unavailable``.
    status: str
    #: ``connection_inactive``, ``participant_ineligible`` or ``source_unavailable``.
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.status == "available"


class RequestItem(Payload):
    slot_id: str = Field(alias="slotId")
    label: str | None = None
    group: str | None = None
    subject: str | None = None
    multiple: bool = False
    #: ``schema``, ``id_document``, ``personal_files``, ``entity_files``, ``custom_schema``.
    kind: str
    target: str | None = None
    verbs: list[str] = Field(default_factory=list)
    #: The ``keep`` slot's adoption policy: ``manual`` or ``auto``.
    adoption: str | None = None
    #: ``granted`` or ``pending`` — any record granted makes the item granted.
    status: str
    records: list[RequestItemRecord] = Field(default_factory=list)

    @property
    def granted(self) -> bool:
        return self.status == "granted"


class Adoption(Payload):
    """A copy the organization kept: one version of the org document that record's copies
    chain into."""

    adoption_id: str = Field(alias="adoptionId")
    slot_id: str | None = Field(default=None, alias="slotId")
    item_kind: str = Field(alias="itemKind")
    item_target: str | None = Field(default=None, alias="itemTarget")
    source_resource_id: str = Field(alias="sourceResourceId")
    source_version: int = Field(alias="sourceVersion")
    org_resource_id: str | None = Field(default=None, alias="orgResourceId")
    org_version: int | None = Field(default=None, alias="orgVersion")
    #: ``document``, ``id_document`` or ``file``.
    resource_type: str = Field(alias="resourceType")
    #: ``materialized`` or ``pending`` (a cold key at keep time; drain retries it).
    state: str
    adopted_at: str = Field(alias="adoptedAt")
    materialized_at: str | None = Field(default=None, alias="materializedAt")
    last_error: str | None = Field(default=None, alias="lastError")
    #: Whose data this copy is, snapshotted at keep time; ``None`` for the recipient's own.
    participant: ParticipantRef | None = None

    @property
    def materialized(self) -> bool:
        return self.state == "materialized"


class Proposal(Payload):
    """A notice: the source of something you hold has a newer version."""

    proposal_id: str = Field(alias="proposalId")
    slot_id: str | None = Field(default=None, alias="slotId")
    item_kind: str = Field(alias="itemKind")
    item_target: str | None = Field(default=None, alias="itemTarget")
    resource_id: str = Field(alias="resourceId")
    new_version: int = Field(alias="newVersion")
    proposed_at: str = Field(alias="proposedAt")
    participant: ParticipantRef | None = None


class RequestDetailResponse(Payload):
    request: Request
    manifest_name: str = Field(alias="manifestName")
    items: list[RequestItem] = Field(default_factory=list)
    adoptions: list[Adoption] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)


class Copy(Payload):
    """A kept copy with its values: ``data`` as kept, ``current_data`` the head of the chain."""

    adoption: Adoption
    #: The copy's id in the organization's vault — never the record to correct.
    resource_id: str = Field(alias="resourceId")
    name: str
    schema_ref: str | None = Field(default=None, alias="schemaRef")
    #: The version this adoption pinned (a kept file: that version's metadata).
    data: DocumentData = Field(default_factory=dict)
    org_version: int | None = Field(default=None, alias="orgVersion")
    #: ``copy`` here — a correction is never pinned by an adoption.
    origin: str | None = None
    current_org_version: int | None = Field(default=None, alias="currentOrgVersion")
    #: ``copy`` or ``correction`` (a member's own revision).
    current_origin: str | None = Field(default=None, alias="currentOrigin")
    #: The head's values — what the organization uses today; absent on a kept file.
    current_data: DocumentData | None = Field(default=None, alias="currentData")
    #: A kept file only: the adoption-scoped route for the version THIS adoption kept.
    download_url: str | None = Field(default=None, alias="downloadUrl")
    participant: ParticipantRef | None = None

    @property
    def values(self) -> DocumentData:
        """What the organization uses today: the head when there is one, else the copy as kept."""
        return self.current_data if self.current_data is not None else self.data


class CopiesResponse(Payload):
    copies: list[Copy] = Field(default_factory=list)


class CorrectCopyRequest(Payload):
    """One correction, pinned to the two versions the editor was opened on.

    Take ``source_resource_id`` and ``expected_source_version`` from the newest keep's
    ``adoption``, and ``expected_org_version`` from that copy's ``current_org_version``.
    ``data`` is the complete corrected document, never a patch.
    """

    source_resource_id: str | None = Field(default=None, alias="sourceResourceId")
    expected_source_version: int = Field(alias="expectedSourceVersion", gt=0)
    expected_org_version: int = Field(alias="expectedOrgVersion", gt=0)
    data: DocumentData

    @classmethod
    def for_copy(cls, copy: Copy, data: DocumentData) -> CorrectCopyRequest:
        """Pin a correction to ``copy`` (the newest materialized keep of the record)."""
        if copy.current_org_version is None:
            raise ValueError("the copy has no head version to pin the correction to")
        return cls(
            source_resource_id=copy.adoption.source_resource_id,
            expected_source_version=copy.adoption.source_version,
            expected_org_version=copy.current_org_version,
            data=data,
        )


class CopyCorrectionResult(Payload):
    #: The record's newest keep, unchanged — a correction creates no adoption.
    adoption: Adoption
    #: The version the correction became: the new head, and the next ``expected_org_version``.
    org_version: int = Field(alias="orgVersion")


class RequestFile(Payload):
    """One version of one file the organization holds for a request: kept, or attached itself."""

    file_id: str = Field(alias="fileId")
    #: ``kept`` (a copy of the person's file) or ``added`` (the organization's own).
    origin: str
    org_version: int = Field(alias="orgVersion")
    adoption_id: str | None = Field(default=None, alias="adoptionId")
    source_version: int | None = Field(default=None, alias="sourceVersion")
    slot_id: str | None = Field(default=None, alias="slotId")
    label: str | None = None
    file_name: str = Field(alias="fileName")
    file_size: int = Field(alias="fileSize")
    #: Detected from the bytes at write time, never the declared type.
    mime_type: str = Field(alias="mimeType")
    written_by: str = Field(alias="writtenBy")
    written_at: str = Field(alias="writtenAt")
    #: The plane's version-pinned route for THIS version's bytes.
    download_url: str = Field(alias="downloadUrl")

    @property
    def kept(self) -> bool:
        return self.origin == "kept"

    @property
    def display_name(self) -> str:
        return self.label or self.file_name


class RequestFilesResponse(Payload):
    files: list[RequestFile] = Field(default_factory=list)


class RemovedFileResponse(Payload):
    file_id: str = Field(alias="fileId")


class SkippedRecord(Payload):
    """A record a keep could not take. The grant stands; a retry after the condition lifts
    takes it."""

    resource_id: str = Field(alias="resourceId")
    participant: ParticipantRef | None = None
    #: ``participant_ineligible`` or ``adoption_refused``.
    reason: str
    message: str | None = None


class AdoptionsResponse(Payload):
    adoptions: list[Adoption] = Field(default_factory=list)
    #: Read this on every keep: fewer ``adoptions`` than the slot has records is this, not a
    #: failure.
    skipped: list[SkippedRecord] = Field(default_factory=list)


class DrainResponse(Payload):
    materialized: int = 0
    still_pending: int = Field(default=0, alias="stillPending")


class ProposalsResponse(Payload):
    proposals: list[Proposal] = Field(default_factory=list)


class ProposalCandidateResponse(Payload):
    """The proposed version's values — looking is taking: this read is receipted to the person."""

    proposal: Proposal
    version: int
    name: str
    schema_ref: str | None = Field(default=None, alias="schemaRef")
    data: DocumentData = Field(default_factory=dict)


class DismissResponse(Payload):
    dismissed: bool
