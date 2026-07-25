"""The read-only endpoints and the models they return."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aiohortos import (
    HortosClient,
    HortosResponseError,
    OnlineStatus,
    ReadoutValueType,
)

from .conftest import DEVICE, FakeHortos


async def test_get_device_names(client: HortosClient) -> None:
    assert await client.get_device_names() == [DEVICE]


async def test_get_devices(client: HortosClient) -> None:
    devices = await client.get_devices()
    assert len(devices) == 1
    assert devices[0].name == DEVICE
    assert devices[0].label == "De Hortus Multima"
    assert devices[0].public_id == "pid"


async def test_get_devices_health(client: HortosClient) -> None:
    health = await client.get_devices_health()
    assert len(health) == 1
    assert health[0].online_status is OnlineStatus.ONLINE
    assert health[0].is_online is True
    assert health[0].readout_status == "Healthy"
    assert health[0].readouts_out_of_sync == ()
    assert health[0].last_update == datetime(2026, 6, 12, 8, 0, tzinfo=UTC)


async def test_get_readout_definitions(client: HortosClient) -> None:
    definitions = await client.get_readout_definitions(DEVICE)
    # The entry without an identifier is dropped.
    assert len(definitions) == 2
    temperature, wind = definitions
    assert temperature.identifier == "OutsideTemperature-Measured"
    assert temperature.unit == "DegreeCelsius"
    assert temperature.quantity == "Temperature"
    assert temperature.minimum == -50.0
    assert temperature.maximum == 60.0
    # Enumeration-coded readouts have no bounds.
    assert wind.identifier == "CardinalWindDirection-Measured"
    assert wind.minimum is None
    assert wind.maximum is None


async def test_get_latest_readouts(client: HortosClient) -> None:
    readouts = await client.get_latest_readouts(DEVICE)
    # The identifier-less entry and the non-object entry are dropped.
    assert len(readouts) == 3
    by_identifier = {readout.identifier: readout for readout in readouts}

    temperature = by_identifier["OutsideTemperature-Measured"]
    assert temperature.value_type is ReadoutValueType.DOUBLE
    assert temperature.unit == "DegreeCelsius"
    # Newest sample wins, regardless of the order the API sent them in.
    assert temperature.value == 18.2
    assert temperature.timestamp == datetime(2026, 6, 12, 8, 0, tzinfo=UTC)
    # Trailing whitespace in the API's user-defined name is stripped.
    assert temperature.source.user_defined_name == "Weerstation"
    assert temperature.source.display_name == "Weerstation"
    assert temperature.source.groups == ("Weather",)

    screen = by_identifier["ScreenStatus-Measured"]
    assert screen.value_type is ReadoutValueType.STRING
    assert screen.value == "Closed"
    assert screen.unit is None
    assert screen.source.user_defined_name is None
    assert screen.source.display_name == "Screen 1"
    assert screen.source.groups == ()

    # A value that is neither a number nor a string is reported as unknown.
    irrigation = by_identifier["IrrigationVolume-Measuered"]
    assert irrigation.value is None
    assert irrigation.timestamp == datetime(2026, 6, 12, 8, 0, tzinfo=UTC)


async def test_get_readout_history(client: HortosClient) -> None:
    start = datetime(2026, 6, 12, 7, 0, tzinfo=UTC)
    values = await client.get_readout_history(
        DEVICE,
        "CardinalWindDirection-Measured",
        "Weather station 001",
        "WeatherStation",
        start,
        start + timedelta(hours=2),
    )
    assert [value.value for value in values] == [8772, 8783]


async def test_history_window_is_capped(client: HortosClient) -> None:
    start = datetime(2026, 6, 12, 7, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="24 hours"):
        await client.get_readout_history(
            DEVICE, "X", "S", "T", start, start + timedelta(hours=25)
        )


async def test_source_names_with_spaces_survive_quoting(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    """Path segments are quoted exactly once, so spaces round-trip."""
    start = datetime(2026, 6, 12, 7, 0, tzinfo=UTC)
    await client.get_readout_history(
        DEVICE, "X", "Weather station 001", "WeatherStation", start, start
    )
    raw = fake_hortos.raw_get_calls[-1]
    assert "Weather%20station%20001" in raw
    # Double-encoding would turn the escapes into %2520.
    assert "%25" not in raw
    # ... and the server sees the original name back.
    assert "Weather station 001" in fake_hortos.get_calls[-1]


async def test_wrong_payload_shapes_raise(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    """Payloads of the wrong shape become errors, not crashes."""
    await client.authenticate()
    fake_hortos.misbehave = True

    with pytest.raises(HortosResponseError, match="Unexpected device list"):
        await client.get_device_names()
    with pytest.raises(HortosResponseError, match="Expected a list"):
        await client.get_devices()
    with pytest.raises(HortosResponseError, match="Expected a list"):
        await client.get_devices_health()
    with pytest.raises(HortosResponseError, match="Expected a list"):
        await client.get_readout_definitions(DEVICE)
    with pytest.raises(HortosResponseError, match="Unexpected readout response"):
        await client.get_latest_readouts(DEVICE)
    with pytest.raises(HortosResponseError, match="Unexpected history response"):
        start = datetime(2026, 6, 12, 7, 0, tzinfo=UTC)
        await client.get_readout_history(DEVICE, "X", "S", "T", start, start)


async def test_non_json_response_raises(
    client: HortosClient, fake_hortos: FakeHortos
) -> None:
    await client.authenticate()
    fake_hortos.send_html = True

    with pytest.raises(HortosResponseError, match="Malformed JSON"):
        await client.get_device_names()
