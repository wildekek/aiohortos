"""Authentication, token renewal and error mapping."""

from __future__ import annotations

import aiohttp
import pytest

from aiohortos import (
    HortosAuthenticationError,
    HortosClient,
    HortosConnectionError,
    HortosResponseError,
)

from .conftest import API_KEY, DEVICE, FakeHortos


async def test_authenticate_returns_tokens(client: HortosClient) -> None:
    tokens = await client.authenticate()
    assert tokens.token == "tok-1"
    assert tokens.refresh_token == "refresh-1"
    assert tokens.organisation is not None
    assert tokens.organisation.id == "42"
    assert tokens.organisation.name == "De Hortus"
    assert client.organisation == tokens.organisation


async def test_organisation_is_none_before_authenticating(
    fake_hortos: FakeHortos,
) -> None:
    async with HortosClient(API_KEY, base_url=fake_hortos.base_url) as client:
        assert client.organisation is None


async def test_invalid_api_key(fake_hortos: FakeHortos) -> None:
    async with HortosClient("wrong", base_url=fake_hortos.base_url) as client:
        with pytest.raises(HortosAuthenticationError):
            await client.authenticate()


async def test_token_is_reused_across_calls(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    await client.get_device_names()
    await client.get_device_names()
    assert fake_hortos.auth_calls == 1
    assert fake_hortos.refresh_calls == 0


async def test_expired_token_triggers_refresh(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    fake_hortos.expire_immediately = True
    await client.authenticate()
    fake_hortos.expire_immediately = False

    await client.get_device_names()

    assert fake_hortos.refresh_calls == 1


async def test_failed_refresh_falls_back_to_reauthentication(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    fake_hortos.expire_immediately = True
    await client.authenticate()
    fake_hortos.expire_immediately = False
    fake_hortos.break_refresh = True

    await client.get_device_names()

    assert fake_hortos.refresh_calls == 0
    assert fake_hortos.auth_calls == 2


async def test_rejected_bearer_retries_once_then_raises(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    await client.authenticate()
    fake_hortos.reject_bearer = True

    with pytest.raises(HortosAuthenticationError):
        await client.get_device_names()

    # One initial attempt plus exactly one retry with a fresh token.
    assert fake_hortos.get_calls.count("/v1/devices") == 2


async def test_recovers_when_the_retry_succeeds(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    """A token the server has forgotten is renewed and the call succeeds."""
    await client.authenticate()
    fake_hortos.reject_bearer_times = 1

    assert await client.get_device_names() == [DEVICE]

    assert fake_hortos.get_calls.count("/v1/devices") == 2
    # The 401 forced a fresh token even though the stored one had not expired.
    assert fake_hortos.refresh_calls == 1


async def test_connection_error(unused_tcp_port: int) -> None:
    async with HortosClient(
        API_KEY, base_url=f"http://127.0.0.1:{unused_tcp_port}"
    ) as client:
        with pytest.raises(HortosConnectionError):
            await client.authenticate()


async def test_timeout_is_a_connection_error(fake_hortos: FakeHortos) -> None:
    async with aiohttp.ClientSession() as session:
        client = HortosClient(
            API_KEY,
            session=session,
            base_url=fake_hortos.base_url,
            request_timeout=0.000_001,
        )
        with pytest.raises(HortosConnectionError):
            await client.authenticate()


async def test_get_timeout_is_a_connection_error(fake_hortos: FakeHortos) -> None:
    """A stalled read, not just a stalled authentication, is mapped too."""
    async with HortosClient(
        API_KEY, base_url=fake_hortos.base_url, request_timeout=0.05
    ) as client:
        await client.authenticate()
        fake_hortos.stall = True
        with pytest.raises(HortosConnectionError, match="Timeout"):
            await client.get_device_names()


async def test_get_against_a_dead_server_is_a_connection_error(
    fake_hortos: FakeHortos,
) -> None:
    async with HortosClient(API_KEY, base_url=fake_hortos.base_url) as client:
        await client.authenticate()
        assert fake_hortos.server is not None
        await fake_hortos.server.close()
        with pytest.raises(HortosConnectionError, match="Error calling"):
            await client.get_device_names()


async def test_injected_session_is_not_closed(fake_hortos: FakeHortos) -> None:
    async with aiohttp.ClientSession() as session:
        client = HortosClient(API_KEY, session=session, base_url=fake_hortos.base_url)
        await client.authenticate()
        await client.close()
        assert not session.closed


async def test_owned_session_is_closed(fake_hortos: FakeHortos) -> None:
    client = HortosClient(API_KEY, base_url=fake_hortos.base_url)
    await client.authenticate()
    session = client._client
    await client.close()
    assert session.closed
    # Closing twice is harmless.
    await client.close()


async def test_malformed_auth_response(fake_hortos: FakeHortos) -> None:
    async with HortosClient(
        API_KEY, base_url=f"{fake_hortos.base_url}/v1/devices"
    ) as client:
        # Posting to a route that does not exist yields a 404, not JSON.
        with pytest.raises(HortosResponseError) as err:
            await client.authenticate()
    assert err.value.status == 404
