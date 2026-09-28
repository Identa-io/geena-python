"""One HTTP connection pool per client, and the plane error envelope decoded once."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO

import httpx

from geena.errors import SERVER_ERROR, GeenaAPIError, GeenaTransportError

logger = logging.getLogger("geena")

JSONObject = dict[str, Any]

#: identa's default per-file upload cap (``STORAGE_MAX_UPLOAD_BYTES``); over it answers 413.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


@dataclass
class Upload:
    """A file to send as ``multipart/form-data``: an open binary stream plus its name and type.

    The stream is read from its current position; ``validate`` seeks to measure and rewinds.
    Geena detects the stored ``mimeType`` from the bytes, so ``content_type`` is a hint only.
    """

    file: BinaryIO
    filename: str
    content_type: str = "application/octet-stream"

    def validate(self, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
        """Refuse locally what the server would refuse: empty or over the cap."""
        self.file.seek(0, 2)
        size = self.file.tell()
        self.file.seek(0)
        if size > max_bytes:
            raise GeenaAPIError(413, "too_large", f"{size} bytes is over the {max_bytes}-byte cap")
        if size == 0:
            raise GeenaAPIError(400, "invalid_body", "the file is empty")


class Download:
    """A streaming file body: relay ``chunks()`` to your own response, then ``aclose()``.

    ``headers`` carries the server's ``Content-Type``, ``Content-Length`` and
    ``Content-Disposition`` so a relay can pass them on unchanged.
    """

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def closed(self) -> bool:
        """True once the body has been consumed or ``aclose()`` ran."""
        return self._response.is_closed

    @property
    def headers(self) -> Mapping[str, str]:
        return {
            name: self._response.headers[name]
            for name in ("content-type", "content-length", "content-disposition")
            if name in self._response.headers
        }

    async def chunks(self, size: int = 64 * 1024) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._response.aiter_raw(chunk_size=size):
                yield chunk
        finally:
            await self.aclose()

    async def read(self) -> bytes:
        """The whole body in memory — for small files and tests; prefer ``chunks()``."""
        try:
            return await self._response.aread()
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        await self._response.aclose()


class Transport:
    """The HTTP layer under the three clients: bearer auth, JSON, multipart, streams, errors."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        httpx_transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = "geena-python",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=httpx_transport,
            headers={"User-Agent": user_agent},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- plain requests -------------------------------------------------------------------

    async def form(self, path: str, form: Mapping[str, str]) -> httpx.Response:
        """An ``application/x-www-form-urlencoded`` POST without bearer auth: the OAuth
        endpoints."""
        try:
            return await self._client.post(path, data=dict(form))
        except httpx.HTTPError as exc:
            raise GeenaTransportError(f"geena unreachable: {exc}") from exc

    async def json(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json: JSONObject | None = None,
        params: Mapping[str, str] | None = None,
    ) -> JSONObject:
        """A bearer-authenticated JSON call; a refusal raises :class:`GeenaAPIError`."""
        try:
            response = await self._client.request(
                method,
                path,
                headers=_bearer(token),
                json=json,
                params=dict(params) if params else None,
            )
        except httpx.HTTPError as exc:
            raise GeenaTransportError(f"geena unreachable: {exc}") from exc
        if response.status_code >= 300:
            raise plane_error(response)
        if response.status_code == 204 or not response.content:
            return {}
        return json_object(response)

    async def multipart(
        self,
        method: str,
        path: str,
        *,
        token: str,
        upload: Upload,
        fields: Mapping[str, str],
    ) -> JSONObject:
        """A file upload. Never retried here: the server may have stored it although the
        response was lost — re-list before retrying."""
        upload.validate()
        try:
            response = await self._client.request(
                method,
                path,
                headers=_bearer(token),
                data=dict(fields),
                files={"file": (upload.filename, upload.file, upload.content_type)},
            )
        except httpx.HTTPError as exc:
            raise GeenaTransportError(
                "upload outcome unknown; re-list the files before retrying"
            ) from exc
        if response.status_code >= 300:
            raise plane_error(response)
        return json_object(response)

    async def download(
        self, path: str, *, token: str, params: Mapping[str, str] | None = None
    ) -> Download:
        """Open a streaming GET; the caller relays :meth:`Download.chunks` and closes it."""
        request = self._client.build_request(
            "GET",
            path,
            headers={**_bearer(token), "Accept-Encoding": "identity"},
            params=dict(params) if params else None,
        )
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise GeenaTransportError(f"geena unreachable: {exc}") from exc
        if response.status_code >= 300:
            await response.aread()
            await response.aclose()
            raise plane_error(response)
        return Download(response)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def json_object(response: httpx.Response) -> JSONObject:
    try:
        body = response.json()
    except ValueError as exc:
        raise GeenaTransportError("geena returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise GeenaTransportError("geena returned a non-object response")
    return body


def json_or_empty(response: httpx.Response) -> JSONObject:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def plane_error(response: httpx.Response) -> GeenaAPIError:
    """Decode a refusal: the plane's ``{error, message}`` or the security gate's envelope."""
    body = json_or_empty(response)
    code = str(body.get("error") or gate_code(body) or SERVER_ERROR)
    message = str(body.get("message") or gate_message(body) or "")
    logger.info("geena %s %s refused: %s", response.request.method, response.url.path, code)
    return GeenaAPIError(response.status_code, code, message)


def gate_code(body: JSONObject) -> str | None:
    """The security gate answers ``{"errors":[{"extensions":{"code"}}]}`` instead."""
    first = _first_gate_error(body)
    if first is None:
        return None
    extensions = first.get("extensions")
    if not isinstance(extensions, dict):
        return None
    code = extensions.get("code")
    return str(code) if code else None


def gate_message(body: JSONObject) -> str | None:
    first = _first_gate_error(body)
    if first is None:
        return None
    message = first.get("message")
    return str(message) if message else None


def _first_gate_error(body: JSONObject) -> JSONObject | None:
    errors = body.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    return first if isinstance(first, dict) else None
