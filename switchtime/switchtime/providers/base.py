"""What a lesson source has to look like.

Keeping this behind an interface means the fragile part (scraping IXL) can fail,
be swapped, or be turned off without the rest of the service noticing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable


class ProviderError(RuntimeError):
    """The source could not be read. Recoverable — the poller retries later."""


@dataclass(frozen=True, slots=True)
class Lesson:
    """One finished piece of work, stable enough to be credited exactly once."""

    ref: str                       # dedupe key, unique per kid and forever
    title: str
    subject: str = ""
    smartscore: int | None = None
    completed_at: datetime | None = None
    day: str = ""                  # local YYYY-MM-DD

    def describe(self) -> str:
        bits = [self.title]
        if self.subject:
            bits.append(f"({self.subject})")
        if self.smartscore is not None:
            bits.append(f"SmartScore {self.smartscore}")
        return " ".join(bits)


@dataclass(slots=True)
class ProviderResult:
    lessons: list[Lesson] = field(default_factory=list)
    #: Free-text detail shown in the parent view when a sync looks wrong.
    diagnostics: list[str] = field(default_factory=list)
    ok: bool = True

    def note(self, message: str) -> None:
        self.diagnostics.append(message)


@runtime_checkable
class LessonProvider(Protocol):
    name: str

    async def fetch(self, kid_id: str) -> ProviderResult:
        """Return everything currently visible for this kid.

        Implementations return *all* recent lessons rather than trying to work
        out which are new; the caller owns deduplication via the ledger, which
        survives restarts and clock changes in a way a provider cursor does not.
        """
        ...

    async def close(self) -> None: ...


def newest_first(lessons: Sequence[Lesson]) -> list[Lesson]:
    return sorted(
        lessons,
        key=lambda l: (l.completed_at or datetime.min, l.ref),
        reverse=True,
    )
