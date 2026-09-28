"""The entry point: one client per app, holding its credentials and one connection pool."""

from __future__ import annotations

from types import TracebackType

import httpx

from geena.http import Transport
from geena.oauth import OAuthClient
from geena.org import OrgClient
from geena.partner import PartnerClient


class GeenaClient:
    """Your app's handle on Geena.

    ``base_url`` is the API (``https://api.test.geena.eu``); ``public_base_url`` is where the
    user's browser reaches it when that differs (a container calling ``host.docker.internal``
    while the popup opens ``localhost``); ``dashboard_base_url`` is the hosted pages
    (``https://dashboard.test.geena.eu``), used for deep links and the step-up page.

    Use it as an async context manager, or call :meth:`aclose` when the process stops.
    """

    def __init__(
        self,
        base_url: str,
        *,
        client_id: str,
        client_secret: str,
        public_base_url: str | None = None,
        dashboard_base_url: str | None = None,
        timeout: float = 30.0,
        httpx_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.transport = Transport(base_url, timeout=timeout, httpx_transport=httpx_transport)
        self.oauth = OAuthClient(
            self.transport,
            client_id=client_id,
            client_secret=client_secret,
            public_base_url=public_base_url,
        )
        self.partner = PartnerClient(self.transport)
        self.org = OrgClient(self.transport)
        self.dashboard_base_url = (dashboard_base_url or "").rstrip("/") or None

    @property
    def client_id(self) -> str:
        return self.oauth.client_id

    def grant_url(self, request_id: str) -> str | None:
        """The user's own view of the connection on the Geena dashboard, for a deep link."""
        if not self.dashboard_base_url:
            return None
        return f"{self.dashboard_base_url}/personal/connections/{request_id}"

    async def aclose(self) -> None:
        await self.transport.aclose()

    async def __aenter__(self) -> GeenaClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
