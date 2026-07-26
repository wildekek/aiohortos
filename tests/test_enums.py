"""Decoding of enumeration-coded readouts."""

from __future__ import annotations

import pytest

from aiohortos import (
    WIND_DIRECTION_CODE_NORTH,
    WIND_DIRECTION_SECTORS,
    decode_cardinal_wind_direction,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (8772, 0.0),  # N, the anchor of the block
        (8773, 22.5),  # NNE
        (8782, 225.0),  # SW, cross-checked against the official app
        (8783, 247.5),  # WSW, likewise
        (8787, 337.5),  # NNW, the last member
        (8783.0, 247.5),  # the API sends doubles
    ],
)
def test_known_member_ids(value: float, expected: float) -> None:
    """Test every id in the block maps to its bearing."""
    assert decode_cardinal_wind_direction(value) == expected


def test_the_block_is_contiguous_and_complete() -> None:
    """Test the 16 compass points cover the circle exactly once."""
    bearings = [
        decode_cardinal_wind_direction(WIND_DIRECTION_CODE_NORTH + offset)
        for offset in range(WIND_DIRECTION_SECTORS)
    ]
    assert bearings == [step * 22.5 for step in range(16)]
    assert len(set(bearings)) == WIND_DIRECTION_SECTORS


@pytest.mark.parametrize(
    "value",
    [
        8771,  # just below the block
        8788,  # just above it
        0,
        -1,
        # Fractional values are not member ids and must not be rounded into
        # the block: 8771.6 would otherwise read as due north.
        8771.6,
        8787.4,
        8772.5,
        # Not numbers at all.
        None,
        "8783",
        True,
        False,
    ],
)
def test_values_outside_the_block(value: object) -> None:
    """Test anything that is not a member id decodes to None."""
    assert decode_cardinal_wind_direction(value) is None
