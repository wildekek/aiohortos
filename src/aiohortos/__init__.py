"""Async client for the Ridder HortOS Automation API."""

from __future__ import annotations

from .client import HortosClient
from .const import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_HISTORY_WINDOW,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW,
)
from .exceptions import (
    HortosAuthenticationError,
    HortosConnectionError,
    HortosError,
    HortosResponseError,
)
from .models import (
    Device,
    DeviceHealth,
    OnlineStatus,
    Organisation,
    Readout,
    ReadoutDefinition,
    ReadoutValue,
    ReadoutValueType,
    Source,
    TokenPair,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT",
    "MAX_HISTORY_WINDOW",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW",
    "Device",
    "DeviceHealth",
    "HortosAuthenticationError",
    "HortosClient",
    "HortosConnectionError",
    "HortosError",
    "HortosResponseError",
    "OnlineStatus",
    "Organisation",
    "Readout",
    "ReadoutDefinition",
    "ReadoutValue",
    "ReadoutValueType",
    "Source",
    "TokenPair",
]
