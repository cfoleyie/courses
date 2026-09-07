"""Pull finished-skill records out of whatever IXL hands back.

IXL publishes no API, so the shape of its internal JSON is not a contract and
will drift. Rather than pin selectors to one layout, this walks every JSON
payload seen while the analytics pages load and keeps objects that *look like*
a practised skill: something with a name, and a score or a date beside it.

That heuristic survives key renames and re-nesting, which pinned paths do not.
It is deliberately conservative — an object has to carry a name and a score to
count, so page furniture and nav blobs are ignored.
"""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any, Iterable, Iterator

from .base import Lesson

NAME_KEYS = ("skillname", "skilltitle", "name", "title", "skill", "description")
ID_KEYS = ("skillid", "skillcode", "code", "skillslug", "slug", "id")
SCORE_KEYS = ("smartscore", "score", "currentscore", "practicescore", "level")
DATE_KEYS = (
    "date", "completedat", "completeddate", "lastpracticed", "practicedate",
    "timestamp", "time", "day", "when", "updatedat",
)
SUBJECT_KEYS = ("subject", "subjectname", "curriculum", "category", "strand")

#: Names that are obviously not a skill, seen in nav and chrome payloads.
_NOISE = re.compile(
    r"^(sign in|sign out|log ?in|log ?out|home|menu|settings|help|search|analytics|"
    r"loading|undefined|null|n/?a)$",
    re.I,
)

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SLUG = re.compile(r"[^a-z0-9]+")


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _first(obj: dict[str, Any], candidates: Iterable[str]) -> tuple[str, Any] | None:
    """Find the first key whose normalised form matches one of `candidates`."""
    normalised = {_norm(k): k for k in obj}
    for candidate in candidates:
        actual = normalised.get(candidate)
        if actual is not None and obj[actual] not in (None, "", []):
            return actual, obj[actual]
    return None


def _as_score(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        score = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        score = int(value.strip())
    else:
        return None
    # IXL SmartScore runs 0-100. Anything outside that is some other number
    # that merely happened to sit under a score-ish key.
    return score if 0 <= score <= 100 else None


def _as_day(value: Any, *, fallback: str) -> str:
    """Coerce assorted date encodings to a local YYYY-MM-DD."""
    if isinstance(value, str):
        match = _ISO.match(value.strip())
        if match:
            return "-".join(match.groups())
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date().isoformat()
            except ValueError:
                continue
    if isinstance(value, (int, float)) and value > 0:
        # Milliseconds or seconds since the epoch; both show up in IXL payloads.
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return fallback
    return fallback


def slugify(text: str) -> str:
    return _SLUG.sub("-", text.strip().lower()).strip("-")[:60] or "skill"


def walk(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict anywhere in a nested JSON structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def candidate_to_lesson(obj: dict[str, Any], *, today: str) -> Lesson | None:
    """Turn one JSON object into a Lesson, or None if it is not a skill record."""
    name_hit = _first(obj, NAME_KEYS)
    if not name_hit:
        return None
    title = str(name_hit[1]).strip()
    if not title or len(title) > 200 or _NOISE.match(title):
        return None

    score_hit = _first(obj, SCORE_KEYS)
    score = _as_score(score_hit[1]) if score_hit else None
    date_hit = _first(obj, DATE_KEYS)

    # A bare name proves nothing — half the page is names. Require corroboration
    # from a plausible score or a date before treating it as work done.
    if score is None and date_hit is None:
        return None

    day = _as_day(date_hit[1], fallback=today) if date_hit else today
    id_hit = _first(obj, ID_KEYS)
    raw_id = str(id_hit[1]).strip() if id_hit else ""
    identity = slugify(raw_id) if raw_id and len(raw_id) <= 60 else slugify(title)

    subject_hit = _first(obj, SUBJECT_KEYS)
    subject = str(subject_hit[1]).strip()[:60] if subject_hit else ""

    return Lesson(
        # The day is part of the key on purpose: redoing a skill tomorrow earns
        # again, redoing it twice today does not.
        ref=f"ixl:{identity}:{day}",
        title=title[:120],
        subject=subject,
        smartscore=score,
        day=day,
        completed_at=None,
    )


def extract_lessons(
    payloads: Iterable[Any],
    *,
    today: str,
    min_smartscore: int = 80,
    since_day: str | None = None,
) -> list[Lesson]:
    """Collect qualifying lessons from a batch of captured JSON payloads."""
    found: dict[str, Lesson] = {}
    for payload in payloads:
        for obj in walk(payload):
            lesson = candidate_to_lesson(obj, today=today)
            if lesson is None:
                continue
            if since_day and lesson.day < since_day:
                continue
            if min_smartscore > 0:
                # No score means we cannot show it was finished, only started.
                if lesson.smartscore is None or lesson.smartscore < min_smartscore:
                    continue
            existing = found.get(lesson.ref)
            if existing is None or (lesson.smartscore or 0) > (existing.smartscore or 0):
                found[lesson.ref] = lesson
    return sorted(found.values(), key=lambda l: (l.day, l.title))


def today_iso() -> str:
    return date.today().isoformat()
