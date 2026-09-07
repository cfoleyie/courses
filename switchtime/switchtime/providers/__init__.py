"""Lesson providers: sources of "a lesson was completed" events."""

from .base import Lesson, LessonProvider, ProviderError, ProviderResult

__all__ = ["Lesson", "LessonProvider", "ProviderError", "ProviderResult"]
