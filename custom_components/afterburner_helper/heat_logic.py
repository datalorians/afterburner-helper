"""Dependency-free staged heat selection logic."""

from __future__ import annotations


def ordered_sources(option: str) -> tuple[str, ...]:
    labels = {
        "Diesel": "diesel",
        "Electric 1": "electric_1",
        "Electric 2": "electric_2",
    }
    return tuple(labels[item.strip()] for item in option.split("→"))


def automatic_stage_count(room: float | None, target: float) -> int:
    if room is None:
        return 0
    deficit = target - room
    if deficit >= 3.0:
        return 3
    if deficit >= 1.5:
        return 2
    if deficit >= 0.3:
        return 1
    return 0


def hysteretic_stage_count(
    room: float | None,
    target: float,
    previous_count: int,
) -> int:
    """Select stages with separate on/off thresholds to prevent chatter.

    Stages enter at 0.3, 1.5, and 3.0 C of deficit. Once running, they do
    not leave until the deficit falls below 0.0, 0.75, and 1.5 C
    respectively. This is especially important when diesel becomes the
    second available source because another source is locked out.
    """
    if room is None:
        return max(0, min(3, previous_count))
    deficit = target - room
    count = max(0, min(3, previous_count))
    enter = (0.3, 1.5, 3.0)
    leave = (0.0, 0.75, 1.5)
    while count < 3 and deficit >= enter[count]:
        count += 1
    while count > 0 and deficit <= leave[count - 1]:
        count -= 1
    return count


def requested_sources(
    *,
    room: float | None,
    master_target: float,
    master_enabled: bool,
    priority: str,
    lockouts: dict[str, bool],
    member_modes: dict[str, str],
    member_targets: dict[str, float],
    automatic_count: int | None = None,
) -> tuple[str, ...]:
    # The master thermostat is authoritative. Member controls refine a live
    # group; they cannot energize a source while the group itself is Off.
    if not master_enabled:
        return ()
    sources = ("diesel", "electric_1", "electric_2")
    ordered = ordered_sources(priority)
    count = (
        automatic_stage_count(room, master_target)
        if automatic_count is None
        else automatic_count
    ) if master_enabled else 0
    automatic = [
        source
        for source in ordered
        if not lockouts[source] and member_modes[source] == "auto"
    ][:count]
    requested = []
    for source in ordered:
        mode = member_modes[source]
        if mode == "heat" and (room is None or room < member_targets[source]):
            requested.append(source)
        elif mode == "auto" and source in automatic:
            requested.append(source)
    return tuple(requested)


def minimum_cycle_decision(
    *,
    desired_on: bool,
    actual_on: bool,
    elapsed_seconds: float,
    minimum_on_seconds: float,
    minimum_off_seconds: float,
    force_off: bool = False,
) -> tuple[bool | None, float | None]:
    """Return an actuator command and optional delay for anti-short-cycling.

    None means do not command a transition yet. Master Off, member Off, and
    lockout are explicit force-off controls and bypass minimum-on duration.
    """
    if desired_on == actual_on:
        return None, None
    if not desired_on and force_off:
        return False, None
    required = minimum_off_seconds if desired_on else minimum_on_seconds
    remaining = max(0.0, required - max(0.0, elapsed_seconds))
    if remaining > 0:
        return None, remaining
    return desired_on, None
