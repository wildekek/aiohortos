"""Shared fixtures: a fake HortOS server backed by aiohttp's test utilities."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiohortos import HortosClient

API_KEY = "test-key"
DEVICE = "HOR10805485.627"


@dataclass
class FakeHortos:
    """State and behaviour of the fake HortOS API."""

    auth_calls: int = 0
    refresh_calls: int = 0
    get_calls: list[str] = field(default_factory=list)
    #: The same requests, before aiohttp decoded the percent-escapes.
    raw_get_calls: list[str] = field(default_factory=list)
    #: Issue tokens that are already expired, to force a refresh.
    expire_immediately: bool = False
    #: Reject every bearer token, to force a re-authentication.
    reject_bearer: bool = False
    #: Reject this many bearer tokens before accepting them again.
    reject_bearer_times: int = 0
    #: Make /v1/token/refresh fail, to exercise the fallback path.
    break_refresh: bool = False
    #: Make /v1/token/refresh reject the refresh token itself.
    reject_refresh: bool = False
    #: Answer every GET with a payload of the wrong shape.
    misbehave: bool = False
    #: Answer every GET with a body that is not JSON at all.
    send_html: bool = False
    #: Never answer a GET, to exercise the request timeout.
    stall: bool = False
    base_url: str = ""
    server: TestServer | None = None

    def tokens(self, serial: int) -> dict[str, Any]:
        """Build an authentication response."""
        now = datetime.now(UTC)
        expires = now + (
            timedelta(seconds=-1) if self.expire_immediately else timedelta(minutes=15)
        )
        return {
            "organisation": {"id": 42, "href": "/org/42", "name": "De Hortus"},
            "token": f"tok-{serial}",
            "expireTime": expires.isoformat().replace("+00:00", "Z"),
            "refreshToken": {
                "token": f"refresh-{serial}",
                "expireTime": (now + timedelta(days=7))
                .isoformat()
                .replace("+00:00", "Z"),
            },
        }


LATEST_READOUTS: dict[str, Any] = {
    "readouts": [
        {
            "name": "Outside temperature (Weerstation )",
            "readoutIdentifier": "OutsideTemperature-Measured",
            "readoutValueType": "Double",
            "unitIdentifier": "DegreeCelsius",
            "device": DEVICE,
            "source": {
                "sourceName": "Weather station 001",
                "sourceType": "WeatherStation",
                "userDefinedName": "Weerstation ",
                "sourceGroups": ["Weather"],
            },
            # Deliberately out of order: the newest sample must win.
            "values": [
                {"timestampUTC": "2026-06-12T08:00:00Z", "value": 18.2},
                {"timestampUTC": "2026-06-12T07:55:00Z", "value": 17.9},
                {"timestampUTC": "not-a-timestamp", "value": 99.9},
            ],
        },
        {
            "name": "Screen status",
            "readoutIdentifier": "ScreenStatus-Measured",
            "readoutValueType": "String",
            "unitIdentifier": None,
            "device": DEVICE,
            "source": {
                "sourceName": "Screen 1",
                "sourceType": "Screen",
                "userDefinedName": None,
                "sourceGroups": None,
            },
            "values": [{"timestampUTC": "2026-06-12T08:00:00Z", "value": "Closed"}],
        },
        {
            "name": "Irrigation volume",
            "readoutIdentifier": "IrrigationVolume-Measuered",
            "readoutValueType": "Double",
            "unitIdentifier": "Liter/SquareMeter",
            "device": DEVICE,
            "source": {"sourceName": "Valve group 003", "sourceType": "ValveGroup"},
            "values": [{"timestampUTC": "2026-06-12T08:00:00Z", "value": {"bad": 1}}],
        },
        {
            # No identifier: unusable, must be dropped.
            "name": "Mystery",
            "readoutValueType": "Double",
            "values": [],
        },
        "not-an-object",
    ]
}


def build_app(fake: FakeHortos) -> web.Application:
    """Create the fake HortOS application."""

    async def guard(request: web.Request) -> web.Response | None:
        fake.get_calls.append(request.path)
        fake.raw_get_calls.append(request.raw_path)
        if fake.stall:
            await asyncio.sleep(10)
        if fake.reject_bearer_times > 0:
            fake.reject_bearer_times -= 1
            return web.Response(status=401)
        if fake.reject_bearer:
            return web.Response(status=401)
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            return web.Response(status=401)
        if fake.send_html:
            return web.Response(
                text="<html>maintenance</html>", content_type="text/html"
            )
        if fake.misbehave:
            # Every endpoint gets the opposite of the shape it promises: the
            # list endpoints an object, the object endpoints a list.
            return web.json_response(
                [] if "/readouts/device/" in request.path else {"nope": 1}
            )
        return None

    async def auth(request: web.Request) -> web.Response:
        body = await request.json()
        if body.get("apikey") != API_KEY:
            return web.Response(status=401)
        fake.auth_calls += 1
        return web.json_response(fake.tokens(fake.auth_calls))

    async def refresh(request: web.Request) -> web.Response:
        body = await request.json()
        assert "token" in body
        assert "refreshToken" in body
        if fake.break_refresh:
            return web.Response(status=500, text="refresh exploded")
        if fake.reject_refresh:
            return web.Response(status=401, text="refresh token rejected")
        fake.refresh_calls += 1
        return web.json_response(fake.tokens(100 + fake.refresh_calls))

    async def devices(request: web.Request) -> web.Response:
        if err := await guard(request):
            return err
        return web.json_response([DEVICE])

    async def devices_info(request: web.Request) -> web.Response:
        if err := await guard(request):
            return err
        return web.json_response(
            [{"publicId": "pid", "name": DEVICE, "label": "De Hortus Multima"}]
        )

    async def health(request: web.Request) -> web.Response:
        if err := await guard(request):
            return err
        return web.json_response(
            [
                {
                    "publicId": "pid",
                    "name": DEVICE,
                    "label": "De Hortus Multima",
                    "lastDeviceUpdateTimeUTC": "2026-06-12T08:00:00.000Z",
                    "onlineStatus": "Online",
                    "readoutStatus": "Healthy",
                    "readoutsOutOfSync": [],
                }
            ]
        )

    async def definitions(request: web.Request) -> web.Response:
        if err := await guard(request):
            return err
        assert request.match_info["device"] == DEVICE
        return web.json_response(
            [
                {
                    "name": "Outside temperature",
                    "readoutIdentifier": "OutsideTemperature-Measured",
                    "readoutValueType": "Double",
                    "unitIdentifier": "DegreeCelsius",
                    "quantity": "Temperature",
                    "source": {
                        "sourceName": "Weather station 001",
                        "sourceType": "WeatherStation",
                    },
                    "min": -50.0,
                    "max": 60.0,
                },
                {
                    "name": "Cardinal wind direction",
                    "readoutIdentifier": "CardinalWindDirection-Measured",
                    "readoutValueType": "Double",
                    "unitIdentifier": "Scalar",
                    "quantity": "Ratio",
                    "source": {
                        "sourceName": "Weather station 001",
                        "sourceType": "WeatherStation",
                    },
                    "min": None,
                    "max": None,
                },
                {"name": "Nameless", "readoutValueType": "Double"},
            ]
        )

    async def latest(request: web.Request) -> web.Response:
        if err := await guard(request):
            return err
        return web.json_response(LATEST_READOUTS)

    async def history(request: web.Request) -> web.Response:
        if err := await guard(request):
            return err
        return web.json_response(
            {
                "readouts": [
                    {"timestampUTC": "2026-06-12T07:00:00Z", "value": 8772},
                    {"timestampUTC": "2026-06-12T08:00:00Z", "value": 8783},
                ]
            }
        )

    app = web.Application()
    app.router.add_post("/v1/auth/apikey", auth)
    app.router.add_post("/v1/token/refresh", refresh)
    app.router.add_get("/v1/devices", devices)
    app.router.add_get("/v1/devices/info", devices_info)
    app.router.add_get("/v1/devices/health", health)
    app.router.add_get("/v1/definitions/readout/device/{device}", definitions)
    app.router.add_get("/v1/readouts/device/{device}/values/latest", latest)
    app.router.add_get(
        "/v1/readouts/device/{device}/values/{readout}/{source}/{type}/{start}/{end}",
        history,
    )
    return app


@pytest.fixture
async def fake_hortos() -> AsyncIterator[FakeHortos]:
    """Run the fake HortOS API and yield its state object."""
    fake = FakeHortos()
    server = TestServer(build_app(fake))
    await server.start_server()
    fake.server = server
    fake.base_url = str(server.make_url("")).rstrip("/")
    yield fake
    await server.close()


@pytest.fixture
async def client(fake_hortos: FakeHortos) -> AsyncIterator[HortosClient]:
    """A client pointed at the fake API, with its own session."""
    async with HortosClient(API_KEY, base_url=fake_hortos.base_url) as hortos:
        yield hortos
