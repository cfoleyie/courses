"""An in-memory provider for tests and for trying the UI without credentials."""

from __future__ import annotations

from datetime import datetime

from .base import Lesson, ProviderError, ProviderResult


class FakeProvider:
    """Hands back whatever was queued for a kid.

    Set `fail_with` to make the next fetch raise, which is how the tests cover
    the "IXL is down" path.
    """

    name = "fake"

    def __init__(self) -> None:
        self.queued: dict[str, list[Lesson]] = {}
        self.fail_with: str | None = None
        self.calls: list[str] = []

    def queue(self, kid_id: str, *lessons: Lesson) -> None:
        self.queued.setdefault(kid_id, []).extend(lessons)

    def queue_lesson(self, kid_id: str, ref: str, *, day: str, title: str = "Practice") -> Lesson:
        lesson = Lesson(
            ref=ref, title=title, subject="Maths", smartscore=100, day=day,
            completed_at=datetime.fromisoformat(f"{day}T17:00:00"),
        )
        self.queue(kid_id, lesson)
        return lesson

    async def fetch(self, kid_id: str) -> ProviderResult:
        self.calls.append(kid_id)
        if self.fail_with:
            raise ProviderError(self.fail_with)
        return ProviderResult(lessons=list(self.queued.get(kid_id, [])))

    async def close(self) -> None:
        return None
