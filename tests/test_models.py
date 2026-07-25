"""Model parsing, exercised directly on the raw shapes HortOS sends."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aiohortos import HortosResponseError, OnlineStatus, ReadoutValueType
from aiohortos.models import (
    Device,
    DeviceHealth,
    Organisation,
    Readout,
    ReadoutDefinition,
    Source,
    TokenPair,
    _latest_value,
    _timestamp,
)


def test_unknown_value_type_does_not_raise() -> None:
    assert ReadoutValueType("Something") is ReadoutValueType.UNKNOWN
    assert ReadoutValueType("Double") is ReadoutValueType.DOUBLE


def test_unknown_online_status_does_not_raise() -> None:
    assert OnlineStatus(None) is OnlineStatus.UNKNOWN
    assert DeviceHealth(name="x").is_online is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-06-12T08:00:00Z", datetime(2026, 6, 12, 8, 0, tzinfo=UTC)),
        ("2026-06-12T08:00:00.000Z", datetime(2026, 6, 12, 8, 0, tzinfo=UTC)),
        # No offset: documented as UTC, so treated as UTC.
        ("2026-06-12T08:00:00", datetime(2026, 6, 12, 8, 0, tzinfo=UTC)),
        ("2026-06-12T10:00:00+02:00", datetime(2026, 6, 12, 8, 0, tzinfo=UTC)),
        ("nonsense", None),
        (None, None),
        (12345, None),
    ],
)
def test_timestamp_parsing(raw: object, expected: datetime | None) -> None:
    assert _timestamp(raw) == expected


def test_organisation_id_is_stringified() -> None:
    assert Organisation.from_api({"id": 42}).id == "42"
    assert Organisation.from_api({}).id is None


def test_device_without_a_name_is_rejected() -> None:
    with pytest.raises(HortosResponseError, match="without a name"):
        Device.from_api({"label": "No name"})


def test_device_health_without_a_name_is_rejected() -> None:
    with pytest.raises(HortosResponseError, match="without a name"):
        DeviceHealth.from_api({"onlineStatus": "Online"})


def test_device_health_out_of_sync_list() -> None:
    health = DeviceHealth.from_api(
        {
            "name": "dev",
            "onlineStatus": "Offline",
            "readoutsOutOfSync": ["A", None, "B"],
        }
    )
    assert health.is_online is False
    assert health.readouts_out_of_sync == ("A", "B")


def test_source_defaults() -> None:
    source = Source.from_api(None)
    assert source.name == ""
    assert source.type == ""
    assert source.display_name == ""
    assert source.groups == ()


def test_readout_without_identifier_is_dropped() -> None:
    assert Readout.from_api({"name": "x"}) is None
    assert ReadoutDefinition.from_api({"name": "x"}) is None


def test_readout_falls_back_to_the_identifier_for_a_name() -> None:
    readout = Readout.from_api({"readoutIdentifier": "OutsideTemperature-Measured"})
    assert readout is not None
    assert readout.name == "OutsideTemperature-Measured"
    assert readout.value is None
    assert readout.timestamp is None


def test_definition_bounds_ignore_booleans() -> None:
    definition = ReadoutDefinition.from_api(
        {"readoutIdentifier": "X-Measured", "min": True, "max": 3}
    )
    assert definition is not None
    assert definition.minimum is None
    assert definition.maximum == 3.0


def test_latest_value_skips_unusable_samples() -> None:
    assert _latest_value(None) is None
    assert _latest_value([]) is None
    assert _latest_value(["nope", {"value": 1}]) is None
    latest = _latest_value(
        [
            {"timestampUTC": "2026-06-12T07:00:00Z", "value": 1},
            {"timestampUTC": "2026-06-12T09:00:00Z", "value": 3},
            {"timestampUTC": "2026-06-12T08:00:00Z", "value": 2},
        ]
    )
    assert latest is not None
    assert latest.value == 3


def test_token_pair_rejects_incomplete_responses() -> None:
    with pytest.raises(HortosResponseError, match="Unexpected authentication"):
        TokenPair.from_api("nope")
    with pytest.raises(HortosResponseError, match="no refresh token"):
        TokenPair.from_api({"token": "t"})
    with pytest.raises(HortosResponseError, match="Incomplete token pair"):
        TokenPair.from_api(
            {"token": "t", "refreshToken": {"token": "r", "expireTime": "x"}}
        )
