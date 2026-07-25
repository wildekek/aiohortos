"""Exceptions raised by aiohortos."""

from __future__ import annotations


class HortosError(Exception):
    """Base class for every error raised by this library."""


class HortosConnectionError(HortosError):
    """The HortOS API could not be reached, or the request timed out."""


class HortosAuthenticationError(HortosError):
    """The API key or token was rejected by the HortOS API."""


class HortosResponseError(HortosError):
    """The HortOS API returned an unexpected status or payload."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        """Store the HTTP status alongside the message, when there is one."""
        super().__init__(message)
        self.status = status
