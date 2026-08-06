"""Camera and capture-time metadata from NVR filenames.

The problem this addresses is the one in the brief: operators currently find
footage by entering a date and time, which is slow. Description-only search
throws that information away entirely, which is the opposite mistake. Keeping
both means "the red car" and "on Tuesday afternoon" can be asked together.

Network video recorders encode camera and timestamp into the filename, so the
metadata is already there and needs no extra input from the user. Several
vendor conventions are recognised; an unrecognised name simply yields no
metadata rather than a wrong guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

# Ordered by specificity. Each must capture a full date and, where present, time.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # CAM01_20260806_143000.mp4 / ch3-20260806-143000
    (re.compile(r"(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})[_\-T ](?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})"), "full"),
    # 2026-08-06 14.30.00 / 2026-08-06_14-30-00
    (re.compile(r"(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})[_\-T ](?P<h>\d{2})[.\-:](?P<mi>\d{2})[.\-:](?P<s>\d{2})"), "full"),
    # 20260806143000 (14 digits, no separators)
    (re.compile(r"\b(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})(?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})\b"), "full"),
    # Date only: 2026-08-06 or 20260806
    (re.compile(r"\b(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})\b"), "date"),
    (re.compile(r"\b(?P<y>20\d{2})(?P<mo>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])\b"), "date"),
)

# CAM01, ch03, channel-2, camera_4
# The tail is a lookahead rather than a word boundary: an underscore counts
# as a word character, so  fails on the common CAM01_20260806 form.
_CAMERA = re.compile(
    r"(?:cam(?:era)?|ch(?:annel)?)[ _-]?(?P<id>[0-9]{1,3})(?![0-9])",
    re.IGNORECASE,
)

# Named parts of the day, so "Tuesday afternoon" is expressible.
TIME_OF_DAY: dict[str, tuple[time, time]] = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(21, 0)),
    "night": (time(21, 0), time(6, 0)),
}

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


@dataclass(frozen=True)
class ClipMetadata:
    camera: str | None
    recorded_at: datetime | None

    def public(self) -> dict[str, str | None]:
        return {
            "camera": self.camera,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }


def parse_filename(name: str) -> ClipMetadata:
    """Extract camera and capture time from a filename. Never guesses."""

    text = name or ""

    camera = None
    match = _CAMERA.search(text)
    if match:
        camera = f"CAM{int(match.group('id')):02d}"

    recorded_at = None
    for pattern, kind in _PATTERNS:
        found = pattern.search(text)
        if not found:
            continue
        parts = found.groupdict()
        try:
            if kind == "full":
                recorded_at = datetime(
                    int(parts["y"]), int(parts["mo"]), int(parts["d"]),
                    int(parts["h"]), int(parts["mi"]), int(parts["s"]),
                )
            else:
                recorded_at = datetime(int(parts["y"]), int(parts["mo"]), int(parts["d"]))
        except ValueError:
            # A plausible-looking but invalid date (month 13) is not a date.
            continue
        break

    return ClipMetadata(camera=camera, recorded_at=recorded_at)


def extract_time_filter(query: str, today: datetime) -> tuple[str, dict[str, object]]:
    """Pull a time constraint out of a natural-language query.

    Returns the query with the time words removed, plus the constraint. Removing
    them matters: leaving "tuesday afternoon" in the text would have the literal
    matcher score windows for containing the word "afternoon".
    """

    text = query or ""
    lowered = text.lower()
    constraint: dict[str, object] = {}
    consumed: list[str] = []

    for name, (start, end) in TIME_OF_DAY.items():
        if re.search(rf"\b{name}\b", lowered):
            constraint["time_of_day"] = name
            constraint["from_time"] = start.isoformat()
            constraint["to_time"] = end.isoformat()
            consumed.append(name)
            break

    for name, index in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered):
            # Most recent occurrence of that weekday, which is what an operator
            # reviewing an incident almost always means.
            delta = (today.weekday() - index) % 7
            target = (today - timedelta(days=delta)).date()
            constraint["date"] = target.isoformat()
            consumed.append(name)
            break

    if re.search(r"\byesterday\b", lowered):
        constraint["date"] = (today - timedelta(days=1)).date().isoformat()
        consumed.append("yesterday")
    elif re.search(r"\btoday\b", lowered):
        constraint["date"] = today.date().isoformat()
        consumed.append("today")

    explicit = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lowered)
    if explicit:
        constraint["date"] = explicit.group(0)
        consumed.append(explicit.group(0))

    camera = _CAMERA.search(text)
    if camera:
        constraint["camera"] = f"CAM{int(camera.group('id')):02d}"
        consumed.append(camera.group(0))

    cleaned = text
    for token in consumed:
        cleaned = re.sub(rf"\b{re.escape(token)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(on|at|during|from)\s*$", " ", cleaned.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

    return cleaned, constraint


def matches_constraint(
    recorded_at: datetime | None,
    camera: str | None,
    constraint: dict[str, object],
) -> bool:
    """Does one clip satisfy the extracted constraint?"""

    if not constraint:
        return True

    wanted_camera = constraint.get("camera")
    if wanted_camera and camera != wanted_camera:
        return False

    if not any(key in constraint for key in ("date", "time_of_day")):
        return True

    # A clip with no known capture time cannot satisfy a time constraint, and
    # claiming otherwise would silently return footage from the wrong day.
    if recorded_at is None:
        return False

    wanted_date = constraint.get("date")
    if wanted_date and recorded_at.date().isoformat() != wanted_date:
        return False

    part = constraint.get("time_of_day")
    if part:
        start, end = TIME_OF_DAY[str(part)]
        current = recorded_at.time()
        if start <= end:
            if not (start <= current < end):
                return False
        # Night wraps midnight.
        elif not (current >= start or current < end):
            return False

    return True
