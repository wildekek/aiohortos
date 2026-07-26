"""Human-readable names from HortOS identifiers.

Readout identifiers follow ``<CamelCaseSubject>-<Kind>``, as in
``VentPositionLeewardSide-Measured`` or ``MaximumPipeTemperature-ActualSetting``.
``Measured`` is the default kind and is dropped from a display name; other
kinds (``Calculated``, ``ActualSetting``) are appended in parentheses so
readouts sharing a subject stay distinguishable.

Source display names are not unique: a controller happily reports several
sources called "Reserve", and the API's own ``userDefinedName`` sometimes
carries trailing whitespace. :func:`disambiguate_source_names` resolves those
collisions.
"""

from __future__ import annotations

import re
from typing import Final

# Splits before an uppercase following a lowercase or digit, and before the
# last uppercase of an acronym run (CO2Level).
_CAMEL_RE: Final = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# "measuered" is a Ridder typo in the API, not a distinct kind.
_DEFAULT_KINDS: Final = frozenset({"measured", "measuered"})


def split_camel(value: str) -> str:
    """Turn 'VentPositionLeewardSide' into 'Vent position leeward side'."""
    words: list[str] = []
    for part in re.split(r"[-_/ ]+", value):
        if part:
            words.extend(_CAMEL_RE.split(part))
    if not words:
        return value
    # Acronyms (CO2, EC) stay intact.
    lowered = [word if word.isupper() else word.lower() for word in words]
    first = lowered[0]
    return " ".join([first[:1].upper() + first[1:], *lowered[1:]])


def readout_display_name(identifier: str) -> str:
    """Return a friendly name for a readout identifier."""
    subject, _, kind = identifier.partition("-")
    name = split_camel(subject)
    if kind and kind.lower() not in _DEFAULT_KINDS:
        name = f"{name} ({split_camel(kind).lower()})"
    return name


def readout_subject(identifier: str) -> str:
    """Return the identifier minus its '-kind' suffix, lowercased."""
    return identifier.partition("-")[0].lower()


def disambiguate_source_names(
    names: dict[str, tuple[str, str, str]],
) -> dict[str, str]:
    """Resolve display names for sources, de-duplicating clashes.

    Input maps a source key to (preferred display name, source type, technical
    source name). Clashing names get the source type appended ('OV1 Tropen
    screen'), and if that still clashes, the number from the technical name.
    """
    counts: dict[str, int] = {}
    for display, _, _ in names.values():
        counts[display] = counts.get(display, 0) + 1

    typed: dict[str, str] = {}
    typed_counts: dict[str, int] = {}
    for key, (display, source_type, _) in names.items():
        name = display
        if counts[display] > 1 and source_type:
            name = f"{display} {split_camel(source_type).lower()}"
        typed[key] = name
        typed_counts[name] = typed_counts.get(name, 0) + 1

    resolved: dict[str, str] = {}
    for key, (_, _, source_name) in names.items():
        name = typed[key]
        if typed_counts[name] > 1:
            match = re.search(r"\d+$", source_name)
            suffix = match.group(0) if match else source_name
            name = f"{name} {suffix}"
        resolved[key] = name
    return resolved
