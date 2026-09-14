"""Ways of getting purchase history in: confirmation emails and spreadsheets."""

from .base import ImportError_, Importer, detect
from .csv_import import CsvImporter
from .email_import import EmailImporter
from .fake import FakeImporter

__all__ = ["Importer", "ImportError_", "CsvImporter", "EmailImporter", "FakeImporter", "detect"]
