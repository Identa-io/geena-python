"""``/partner/v1`` shapes — see openapi/partner-v1.yaml, whose schema names these classes carry."""

from __future__ import annotations

from pydantic import Field

from geena.models.common import DocumentData, ParticipantRef, Payload


class Error(Payload):
    error: str
    message: str = ""


class ConnectionItem(Payload):
    request_id: str = Field(alias="requestId")
    manifest_id: str = Field(alias="manifestId")
    manifest_name: str | None = Field(default=None, alias="manifestName")
    manifest_version: int = Field(alias="manifestVersion")
    state: str


class ConnectionsResponse(Payload):
    requests: list[ConnectionItem] = Field(default_factory=list)


class StatusGroup(Payload):
    id: str
    label: str
    order: int = 0


class StatusSubject(Payload):
    """The ask: a party beyond the recipient; ``relation`` is present on ``person`` only."""

    id: str
    type: str
    relation: str | None = None
    label: str | None = None
    repeat: bool = False


#: The answer to ``subjects``: who is cast, derived from the grants.
StatusParticipant = ParticipantRef


class StatusVerification(Payload):
    method: str
    level: str
    verified_at: str = Field(alias="verifiedAt")
    version: int


class StatusItem(Payload):
    slot_id: str = Field(alias="slotId")
    label: str | None = None
    group: str | None = None
    #: The manifest subject this slot is about; ``None`` = the recipient.
    subject: str | None = None
    #: ``False`` (the default): one standing grant, a later fill replaces it. ``True``: grants
    #: accrue.
    multiple: bool = False
    kind: str
    target: str | None = None
    #: What the app may do beyond reading: ``fill``, ``edit``, ``keep``.
    verbs: list[str] = Field(default_factory=list)
    #: ``granted`` or ``pending`` — nothing else, and a live reading, never a latch.
    status: str
    verification: list[StatusVerification] = Field(default_factory=list)

    @property
    def granted(self) -> bool:
        return self.status == "granted"

    def allows(self, verb: str) -> bool:
        return verb in self.verbs


class StatusResponse(Payload):
    state: str
    groups: list[StatusGroup] = Field(default_factory=list)
    subjects: list[StatusSubject] = Field(default_factory=list)
    participants: list[ParticipantRef] = Field(default_factory=list)
    items: list[StatusItem] = Field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.state == "active"


class ServedRecord(Payload):
    """One granted resource as served. Read ``status`` before ``type``.

    ``document`` carries ``data``; ``id_document`` carries ``document_type``, ``ocr``,
    ``verification`` and ``images``; ``file`` carries ``label``, ``file_name``, ``mime_type``,
    ``file_size`` and a ``download_url`` (the bytes never arrive inline). ``participant`` is
    always present on the wire: ``None`` for the recipient's own data. A record with
    ``status == "unavailable"`` has no ``type`` and a ``reason``: ``participant_ineligible``
    (the user no longer speaks for that party) or ``record_unreadable`` (retry later).
    """

    resource_id: str = Field(alias="resourceId")
    participant: ParticipantRef | None = None
    type: str | None = None
    status: str = "available"
    reason: str | None = None
    version: int | None = None
    name: str | None = None
    data: DocumentData | None = None
    document_type: str | None = Field(default=None, alias="documentType")
    ocr: DocumentData | None = None
    verification: list[StatusVerification] = Field(default_factory=list)
    images: list[DocumentData] = Field(default_factory=list)
    label: str | None = None
    file_name: str | None = Field(default=None, alias="fileName")
    mime_type: str | None = Field(default=None, alias="mimeType")
    file_size: int | None = Field(default=None, alias="fileSize")
    download_url: str | None = Field(default=None, alias="downloadUrl")

    @property
    def available(self) -> bool:
        return self.status == "available"


class ItemResponse(Payload):
    """A served slot: one record per grant — one per party on a subject slot."""

    slot_id: str = Field(alias="slotId")
    label: str | None = None
    group: str | None = None
    subject: str | None = None
    kind: str
    target: str | None = None
    records: list[ServedRecord] = Field(default_factory=list)


class CandidateItem(Payload):
    """A resource that could back a slot; ``data`` rides along when the key context can open it."""

    resource_id: str = Field(alias="resourceId")
    type: str
    name: str | None = None
    label: str | None = None
    file_name: str | None = Field(default=None, alias="fileName")
    mime_type: str | None = Field(default=None, alias="mimeType")
    file_size: int | None = Field(default=None, alias="fileSize")
    document_type: str | None = Field(default=None, alias="documentType")
    data: DocumentData | None = None
    version: int | None = None
    created_at: str = Field(alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    granted: bool = False


class CandidatesResponse(Payload):
    slot_id: str = Field(alias="slotId")
    kind: str | None = None
    target: str | None = None
    candidates: list[CandidateItem] = Field(default_factory=list)


class AttachResponse(Payload):
    slot_id: str = Field(alias="slotId")
    resource_id: str = Field(alias="resourceId")
    granted: bool = True
    already_granted: bool = Field(default=False, alias="alreadyGranted")


class WriteResponse(Payload):
    slot_id: str = Field(alias="slotId")
    kind: str | None = None
    target: str | None = None
    resource_id: str = Field(alias="resourceId")
    version: int


class CreateResponse(Payload):
    slot_id: str = Field(alias="slotId")
    resource_id: str = Field(alias="resourceId")
    version: int = 1
    granted: bool = True


class ParticipantDetails(Payload):
    """Company candidates only, best-effort: what tells two companies apart in a picker."""

    registration_country: str | None = Field(default=None, alias="registrationCountry")
    registration_number: str | None = Field(default=None, alias="registrationNumber")


class SubjectParticipantCandidate(Payload):
    alias: str
    #: The user's own label for the party; appears here and on no other partner surface.
    label: str
    bound: bool = False
    details: ParticipantDetails | None = None


class SubjectCandidatesResponse(Payload):
    subject_id: str = Field(alias="subjectId")
    type: str
    relation: str | None = None
    label: str | None = None
    repeat: bool = False
    participants: list[SubjectParticipantCandidate] = Field(default_factory=list)


class SubjectParticipantCreateResponse(Payload):
    alias: str
    label: str
