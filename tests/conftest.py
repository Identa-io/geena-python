"""A fake Geena behind ``httpx.MockTransport``: tests script responses per (method, path)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from geena import GeenaClient

Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeGeena:
    """Register responses with ``on()``; every request the client made is kept in ``calls``."""

    routes: dict[tuple[str, str], Handler] = field(default_factory=dict)
    calls: list[httpx.Request] = field(default_factory=list)

    def on(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json_body: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            if content is not None:
                return httpx.Response(status, content=content, headers=headers)
            return httpx.Response(status, json=json_body if json_body is not None else {})

        self.routes[(method.upper(), path)] = handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"error": "not_found", "message": "unrouted in test"})
        return handler(request)

    def last(self) -> httpx.Request:
        return self.calls[-1]

    def last_json(self) -> Any:
        return json.loads(self.last().content)


@pytest.fixture
def geena() -> FakeGeena:
    return FakeGeena()


@pytest.fixture
async def client(geena: FakeGeena) -> AsyncIterator[GeenaClient]:
    c = GeenaClient(
        "https://api.test.geena.eu",
        client_id="acme-portal",
        client_secret="s3cret",
        dashboard_base_url="https://dashboard.test.geena.eu",
        httpx_transport=httpx.MockTransport(geena.handle),
    )
    yield c
    await c.aclose()
