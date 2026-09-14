"""The shape every importer follows, and picking one from a file name."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..model import ParsedOrder


class ImportError_(Exception):
    """A file was recognised but nothing usable could be read from it."""


@runtime_checkable
class Importer(Protocol):
    name: str

    def handles(self, path: Path) -> bool:
        """True when this importer recognises the file by extension."""

    def read(self, path: Path) -> list[ParsedOrder]:
        """Parse the file into orders. Raises ImportError_ when it cannot."""


def detect(path: Path, importers: list[Importer]) -> Importer:
    for importer in importers:
        if importer.handles(path):
            return importer
    raise ImportError_(
        f"no importer recognises {path.name}; expected .eml, .html, .txt or .csv"
    )
