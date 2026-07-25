"""Constants for aiohortos."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

#: Public HortOS cloud endpoint. On-premise installations expose the same API
#: on their own host.
DEFAULT_BASE_URL: Final = "https://hortos.ridder.com/api/process-control"

#: Total timeout for a single request, in seconds.
DEFAULT_TIMEOUT: Final = 30.0

#: Tokens are renewed this long before they actually expire.
TOKEN_LEEWAY: Final = timedelta(seconds=60)

#: The API accepts at most 100 requests per 15 seconds per API key. The
#: library does not enforce this; callers should pace their own polling.
RATE_LIMIT_REQUESTS: Final = 100
RATE_LIMIT_WINDOW: Final = timedelta(seconds=15)

#: The history endpoint refuses windows longer than this.
MAX_HISTORY_WINDOW: Final = timedelta(hours=24)
