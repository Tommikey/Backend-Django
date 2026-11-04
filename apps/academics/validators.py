"""Limits on files people upload (lesson materials, assignment submissions)."""

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.deconstruct import deconstructible

# documents and images; nothing a browser would run (html, svg, js) or a computer would execute
ALLOWED_EXTENSIONS = [
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "txt",
    "png",
    "jpg",
    "jpeg",
]
MAX_UPLOAD_MB = 10


@deconstructible
class MaxFileSize:
    def __init__(self, megabytes):
        self.megabytes = megabytes

    def __call__(self, file):
        if file.size > self.megabytes * 1024 * 1024:
            raise ValidationError(f"Files can be at most {self.megabytes} MB.", code="too_big")

    def __eq__(self, other):
        return isinstance(other, MaxFileSize) and other.megabytes == self.megabytes


UPLOAD_VALIDATORS = [
    FileExtensionValidator(ALLOWED_EXTENSIONS),
    MaxFileSize(MAX_UPLOAD_MB),
]
