"""Typed models for the HortOS Automation API.

Every model is built from the raw JSON with a ``from_api`` classmethod that is
deliberately forgiving: HortOS omits fields, sends ``null`` where a list is
documented, and pads several string fields with stray whitespace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from .exceptions import HortosResponseError


def _text(value: Any) -> str | None:
    """Return a stripped string, or None when there is nothing left."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _timestamp(value: Any) -> datetime | None:
    """Parse an API timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Timestamps are documented as UTC; some are sent without an offset.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class ReadoutValueType(StrEnum):
    """How a readout's value should be interpreted.

    The OpenAPI spec only defines ``Double`` and ``String``; anything else
    maps to ``UNKNOWN`` so a future addition does not break the client.
    """

    DOUBLE = "Double"
    STRING = "String"
    UNKNOWN = "Unknown"

    @classmethod
    def _missing_(cls, value: object) -> ReadoutValueType:  # noqa: ARG003
        return cls.UNKNOWN

    @classmethod
    def parse(cls, value: object) -> ReadoutValueType:
        """Map a raw API value to a member, defaulting to UNKNOWN."""
        return cls(value) if isinstance(value, str) else cls.UNKNOWN


class OnlineStatus(StrEnum):
    """Connection state of a controller as reported by the HortOS cloud."""

    ONLINE = "Online"
    OFFLINE = "Offline"
    UNKNOWN = "Unknown"

    @classmethod
    def _missing_(cls, value: object) -> OnlineStatus:  # noqa: ARG003
        return cls.UNKNOWN

    @classmethod
    def parse(cls, value: object) -> OnlineStatus:
        """Map a raw API value to a member, defaulting to UNKNOWN."""
        return cls(value) if isinstance(value, str) else cls.UNKNOWN


@dataclass(frozen=True, slots=True, kw_only=True)
class Organisation:
    """The organisation an API key belongs to."""

    id: str | None
    href: str | None = None
    name: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Build an organisation from its API representation."""
        raw_id = data.get("id")
        return cls(
            id=None if raw_id is None else str(raw_id),
            href=_text(data.get("href")),
            name=_text(data.get("name")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenPair:
    """A bearer token plus the refresh token that can renew it.

    The bearer token is valid for 15 minutes, the refresh token for 7 days.
    """

    token: str
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    organisation: Organisation | None = None

    @classmethod
    def from_api(cls, data: Any) -> Self:
        """Build a token pair from an authentication response."""
        if not isinstance(data, dict):
            raise HortosResponseError(f"Unexpected authentication response: {data!r}")
        refresh = data.get("refreshToken")
        if not isinstance(refresh, dict):
            raise HortosResponseError("Authentication response has no refresh token")
        token = data.get("token")
        refresh_token = refresh.get("token")
        expires_at = _timestamp(data.get("expireTime"))
        refresh_expires_at = _timestamp(refresh.get("expireTime"))
        if (
            not isinstance(token, str)
            or not isinstance(refresh_token, str)
            or expires_at is None
            or refresh_expires_at is None
        ):
            raise HortosResponseError(
                "Incomplete token pair in authentication response"
            )
        organisation = data.get("organisation")
        return cls(
            token=token,
            expires_at=expires_at,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
            organisation=(
                Organisation.from_api(organisation)
                if isinstance(organisation, dict)
                else None
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Device:
    """A greenhouse controller known to the organisation."""

    name: str
    label: str | None = None
    public_id: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Build a device from its API representation."""
        name = _text(data.get("name"))
        if name is None:
            raise HortosResponseError(f"Device without a name: {data!r}")
        return cls(
            name=name,
            label=_text(data.get("label")),
            public_id=_text(data.get("publicId")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceHealth:
    """Connection and synchronisation state of one controller."""

    name: str
    label: str | None = None
    public_id: str | None = None
    online_status: OnlineStatus = OnlineStatus.UNKNOWN
    readout_status: str | None = None
    readouts_out_of_sync: tuple[str, ...] = ()
    last_update: datetime | None = None

    @property
    def is_online(self) -> bool | None:
        """Whether the controller is online, or None when unreported."""
        if self.online_status is OnlineStatus.UNKNOWN:
            return None
        return self.online_status is OnlineStatus.ONLINE

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Build a health record from its API representation."""
        name = _text(data.get("name"))
        if name is None:
            raise HortosResponseError(f"Device health without a name: {data!r}")
        out_of_sync = data.get("readoutsOutOfSync")
        return cls(
            name=name,
            label=_text(data.get("label")),
            public_id=_text(data.get("publicId")),
            online_status=OnlineStatus.parse(data.get("onlineStatus")),
            readout_status=_text(data.get("readoutStatus")),
            readouts_out_of_sync=tuple(
                str(item) for item in out_of_sync if item is not None
            )
            if isinstance(out_of_sync, list)
            else (),
            last_update=_timestamp(data.get("lastDeviceUpdateTimeUTC")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Source:
    """A measuring source inside a controller.

    Controllers group their readouts by source: a weather station, a
    ventilation group, a valve group, and so on.
    """

    name: str
    type: str
    user_defined_name: str | None = None
    groups: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        """The name a grower would recognise, falling back to the technical one."""
        return self.user_defined_name or self.name

    @classmethod
    def from_api(cls, data: dict[str, Any] | None) -> Self:
        """Build a source from its API representation."""
        data = data or {}
        groups = data.get("sourceGroups")
        return cls(
            name=_text(data.get("sourceName")) or "",
            type=_text(data.get("sourceType")) or "",
            user_defined_name=_text(data.get("userDefinedName")),
            groups=tuple(str(item) for item in groups if item is not None)
            if isinstance(groups, list)
            else (),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadoutValue:
    """One timestamped sample of a readout."""

    value: float | str | None
    timestamp: datetime | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Build a sample from its API representation."""
        value = data.get("value")
        return cls(
            # Doubles and strings come through as-is; anything else
            # (unexpected objects) is treated as unknown.
            value=value if isinstance(value, (int, float, str)) else None,
            timestamp=_timestamp(data.get("timestampUTC")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Readout:
    """The latest known state of a single readout.

    ``identifier`` follows ``<CamelCaseSubject>-<Kind>``, e.g.
    ``VentPositionLeewardSide-Measured``. ``name`` is the API's display name,
    which embeds the source's user-defined name and is therefore a poor label
    on its own.
    """

    identifier: str
    name: str
    value_type: ReadoutValueType = ReadoutValueType.DOUBLE
    unit: str | None = None
    source: Source
    value: float | str | None = None
    timestamp: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self | None:
        """Build a readout from its API representation.

        Returns None for entries without an identifier, which cannot be
        addressed and are therefore useless to a caller.
        """
        identifier = _text(data.get("readoutIdentifier"))
        if identifier is None:
            return None
        latest = _latest_value(data.get("values"))
        return cls(
            identifier=identifier,
            name=_text(data.get("name")) or identifier,
            value_type=ReadoutValueType.parse(data.get("readoutValueType")),
            unit=_text(data.get("unitIdentifier")),
            source=Source.from_api(data.get("source")),
            value=latest.value if latest else None,
            timestamp=latest.timestamp if latest else None,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadoutDefinition:
    """The definition of a readout, without any value.

    ``quantity`` is generic (``Ratio``, ``Mass/Mass``, …) and rarely useful;
    ``min``/``max`` are null for enumeration-coded readouts.
    """

    identifier: str
    name: str
    value_type: ReadoutValueType = ReadoutValueType.DOUBLE
    unit: str | None = None
    quantity: str | None = None
    source: Source
    minimum: float | None = None
    maximum: float | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self | None:
        """Build a definition from its API representation."""
        identifier = _text(data.get("readoutIdentifier"))
        if identifier is None:
            return None
        return cls(
            identifier=identifier,
            name=_text(data.get("name")) or identifier,
            value_type=ReadoutValueType.parse(data.get("readoutValueType")),
            unit=_text(data.get("unitIdentifier")),
            quantity=_text(data.get("quantity")),
            source=Source.from_api(data.get("source")),
            minimum=_number(data.get("min")),
            maximum=_number(data.get("max")),
        )


def _number(value: Any) -> float | None:
    """Coerce an API number to a float, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _latest_value(values: Any) -> ReadoutValue | None:
    """Pick the most recent sample from a readout's value list.

    HortOS returns a short window of samples in no guaranteed order, so the
    newest timestamp wins. Samples without a usable timestamp are ignored.
    """
    if not isinstance(values, list):
        return None
    latest: ReadoutValue | None = None
    latest_at: datetime | None = None
    for item in values:
        if not isinstance(item, dict):
            continue
        sample = ReadoutValue.from_api(item)
        if sample.timestamp is None:
            continue
        if latest_at is None or sample.timestamp > latest_at:
            latest = sample
            latest_at = sample.timestamp
    return latest
