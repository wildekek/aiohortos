"""Decoding for HortOS enumeration-coded readouts.

Some readouts arrive with ``unitIdentifier: "Scalar"`` and a ``Double``
value, but the number is not a measurement: it is a member id of an
enumeration table the API does not expose. The readout definition carries no
``min``/``max`` for these, and there is no enumeration endpoint, so the only
way to decode one is to observe a full cycle of its values and anchor them
against a known reference.

``CardinalWindDirection`` is the one decoded so far.
"""

from __future__ import annotations

from typing import Any, Final

#: Member id of due north on a HortiMaX controller. The 16 compass points
#: occupy contiguous ids from here, clockwise in 22.5 degree steps. Confirmed
#: over a full day of history and cross-checked against the official app
#: (8782 = SW, 8783 = WSW). A controller using a different id base would only
#: change this number.
WIND_DIRECTION_CODE_NORTH: Final = 8772

#: Number of compass points in the block.
WIND_DIRECTION_SECTORS: Final = 16

#: Degrees between two neighbouring compass points.
WIND_DIRECTION_STEP_DEGREES: Final = 360 / WIND_DIRECTION_SECTORS


def decode_cardinal_wind_direction(value: Any) -> float | None:
    """Return the compass bearing for a CardinalWindDirection member id.

    Returns None for anything that is not a member of the known block, so a
    controller using a different table, or a value that is not an id at all,
    reports nothing rather than a plausible-looking bearing.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Member ids are whole numbers; a fractional value is not one of them
    # and must not be rounded into the block.
    if float(value) != int(value):
        return None
    sector = int(value) - WIND_DIRECTION_CODE_NORTH
    if not 0 <= sector < WIND_DIRECTION_SECTORS:
        return None
    return sector * WIND_DIRECTION_STEP_DEGREES
