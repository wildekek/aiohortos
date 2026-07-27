"""Async client for the Ridder HortOS Automation API.

Authentication model (per Ridder's OpenAPI spec):

- ``POST /v1/auth/apikey`` with the API key returns a bearer token (valid 15
  minutes) and a refresh token (valid 7 days).
- ``POST /v1/token/refresh`` exchanges an expired bearer token plus the
  refresh token for a fresh pair.
- The API allows at most 100 requests per 15 seconds per API key.

The client renews tokens on demand, so callers only ever deal with the
endpoint methods.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, MAX_HISTORY_WINDOW, TOKEN_LEEWAY
from .exceptions import (
    HortosAuthenticationError,
    HortosConnectionError,
    HortosResponseError,
)
from .models import (
    Device,
    DeviceHealth,
    Organisation,
    Readout,
    ReadoutDefinition,
    ReadoutValue,
    TokenPair,
)

if TYPE_CHECKING:
    from types import TracebackType

_HISTORY_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


class HortosClient:
    """Read-only client for the HortOS Automation API.

    Pass an existing :class:`aiohttp.ClientSession` to reuse a connection
    pool, or let the client create (and close) one of its own::

        async with HortosClient(api_key="...") as client:
            for device in await client.get_devices():
                print(await client.get_latest_readouts(device.name))
    """

    def __init__(
        self,
        api_key: str,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = DEFAULT_BASE_URL,
        request_timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the client."""
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._close_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._tokens: TokenPair | None = None
        self._auth_lock = asyncio.Lock()

    @property
    def organisation(self) -> Organisation | None:
        """The organisation the API key belongs to, once authenticated."""
        return self._tokens.organisation if self._tokens else None

    # ----------------------------------------------------------------- auth

    async def authenticate(self) -> TokenPair:
        """Exchange the API key for a fresh token pair.

        Raises :class:`HortosAuthenticationError` when the key is rejected.
        """
        async with self._auth_lock:
            return await self._authenticate()

    async def _authenticate(self) -> TokenPair:
        data = await self._post("/v1/auth/apikey", {"apikey": self._api_key})
        self._tokens = TokenPair.from_api(data)
        return self._tokens

    async def _refresh(self, tokens: TokenPair) -> TokenPair:
        data = await self._post(
            "/v1/token/refresh",
            {"token": tokens.token, "refreshToken": tokens.refresh_token},
        )
        self._tokens = TokenPair.from_api(data)
        return self._tokens

    async def _bearer(self, *, force: bool = False) -> str:
        """Return a usable bearer token, renewing it when needed."""
        async with self._auth_lock:
            tokens = self._tokens
            if not force and tokens is not None and _still_valid(tokens.expires_at):
                return tokens.token
            if tokens is not None and _still_valid(tokens.refresh_expires_at):
                try:
                    return (await self._refresh(tokens)).token
                except (HortosAuthenticationError, HortosResponseError):
                    # A refresh token can be rejected (401/403) or fail for
                    # reasons the API does not spell out; either way the API
                    # key is still good, so re-authenticate with it.
                    pass
            return (await self._authenticate()).token

    # ------------------------------------------------------------- requests

    @property
    def _client(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        """POST to an unauthenticated endpoint."""
        try:
            async with self._client.post(
                self._url(path), json=payload, timeout=self._timeout
            ) as response:
                return await self._read(response, path)
        except TimeoutError as err:
            raise HortosConnectionError(f"Timeout calling {path}") from err
        except aiohttp.ClientError as err:
            raise HortosConnectionError(f"Error calling {path}: {err}") from err

    async def _get(self, path: str) -> Any:
        """GET an authenticated endpoint, renewing the token once on a 401."""
        expired, data = await self._attempt_get(path, await self._bearer())
        if expired:
            token = await self._bearer(force=True)
            _, data = await self._attempt_get(path, token, final=True)
        return data

    async def _attempt_get(
        self, path: str, token: str, *, final: bool = False
    ) -> tuple[bool, Any]:
        """Perform one GET, returning (token expired, payload).

        A 401 on a non-final attempt is reported back rather than raised, so
        the caller can renew the token and try again.
        """
        try:
            async with self._client.get(
                self._url(path),
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            ) as response:
                if response.status == HTTPStatus.UNAUTHORIZED and not final:
                    return True, None
                return False, await self._read(response, path)
        except TimeoutError as err:
            raise HortosConnectionError(f"Timeout calling {path}") from err
        except aiohttp.ClientError as err:
            raise HortosConnectionError(f"Error calling {path}: {err}") from err

    def _url(self, path: str) -> URL:
        # encoded=True keeps the path segments we quoted ourselves intact.
        return URL(f"{self._base_url}{path}", encoded=True)

    @staticmethod
    async def _read(response: aiohttp.ClientResponse, path: str) -> Any:
        """Turn a response into JSON, mapping error statuses to exceptions."""
        if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise HortosAuthenticationError(
                f"HortOS rejected the credentials for {path} (HTTP {response.status})"
            )
        if response.status >= HTTPStatus.BAD_REQUEST:
            body = (await response.text())[:200]
            raise HortosResponseError(
                f"HTTP {response.status} from {path}: {body}", status=response.status
            )
        try:
            return await response.json()
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise HortosResponseError(f"Malformed JSON from {path}") from err

    # ------------------------------------------------------------ endpoints

    async def get_device_names(self) -> list[str]:
        """Return the identifiers of every controller in the organisation."""
        data = await self._get("/v1/devices")
        if not isinstance(data, list):
            raise HortosResponseError(f"Unexpected device list: {data!r}")
        return [str(item) for item in data]

    async def get_devices(self) -> list[Device]:
        """Return every controller with its friendly label."""
        path = "/v1/devices/info"
        return [
            Device.from_api(item)
            for item in self._expect_list(path, await self._get(path))
        ]

    async def get_devices_health(self) -> list[DeviceHealth]:
        """Return the connection state of every controller."""
        path = "/v1/devices/health"
        return [
            DeviceHealth.from_api(item)
            for item in self._expect_list(path, await self._get(path))
        ]

    async def get_readout_definitions(self, device: str) -> list[ReadoutDefinition]:
        """Return the definitions of every readout of one controller."""
        path = f"/v1/definitions/readout/device/{_segment(device)}"
        return [
            definition
            for item in self._expect_list(path, await self._get(path))
            if (definition := ReadoutDefinition.from_api(item)) is not None
        ]

    async def get_latest_readouts(self, device: str) -> list[Readout]:
        """Return the latest value of every readout of one controller.

        A controller publishes its changed readouts in a batch about once a
        minute; a readout whose value does not change keeps its old timestamp
        for up to five minutes. Polling faster than once a minute therefore
        gains nothing, but polling slower drops updates.
        """
        path = f"/v1/readouts/device/{_segment(device)}/values/latest"
        data = await self._get(path)
        if not isinstance(data, dict):
            raise HortosResponseError(f"Unexpected readout response from {path}")
        return [
            readout
            for item in self._expect_list(path, data.get("readouts"))
            if (readout := Readout.from_api(item)) is not None
        ]

    async def get_readout_history(  # noqa: PLR0913
        self,
        device: str,
        identifier: str,
        source_name: str,
        source_type: str,
        start: datetime,
        end: datetime,
    ) -> list[ReadoutValue]:
        """Return the samples of one readout between ``start`` and ``end``.

        The API refuses windows longer than 24 hours.
        """
        if end - start > MAX_HISTORY_WINDOW:
            raise ValueError("HortOS history windows may not exceed 24 hours")
        path = (
            f"/v1/readouts/device/{_segment(device)}/values/{_segment(identifier)}"
            f"/{_segment(source_name)}/{_segment(source_type)}"
            f"/{_segment(_history_time(start))}/{_segment(_history_time(end))}"
        )
        data = await self._get(path)
        if not isinstance(data, dict):
            raise HortosResponseError(f"Unexpected history response from {path}")
        return [
            ReadoutValue.from_api(item)
            for item in self._expect_list(path, data.get("readouts"))
        ]

    @staticmethod
    def _expect_list(path: str, data: Any) -> list[dict[str, Any]]:
        """Validate that an endpoint returned a list of objects."""
        if not isinstance(data, list):
            raise HortosResponseError(
                f"Expected a list from {path}, got {type(data).__name__}"
            )
        return [item for item in data if isinstance(item, dict)]

    # -------------------------------------------------------------- session

    async def close(self) -> None:
        """Close the session, if this client created it."""
        if self._session is not None and self._close_session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session on leaving the async context manager."""
        await self.close()


def _still_valid(expires_at: datetime) -> bool:
    """Whether a token is good for at least the leeway period."""
    return datetime.now(UTC) + TOKEN_LEEWAY < expires_at


def _segment(value: str) -> str:
    """Quote a value for use as a single URL path segment."""
    return quote(value, safe="")


def _history_time(value: datetime) -> str:
    """Format a datetime the way the history endpoint expects it (UTC)."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime(_HISTORY_TIME_FORMAT)
