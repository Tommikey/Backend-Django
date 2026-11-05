"""Uploaded files (lesson materials, assignment submissions) are private.

- They are stored under random names; the name the uploader gave is kept in ``file_name`` and
  used when the file is downloaded.
- Nobody gets a public URL. Downloads go through API endpoints (``.../file/``) that apply the
  same visibility rules as the object itself, then either stream the file (local storage) or
  redirect to a link that expires in a few minutes (S3-compatible storage; FILE_STORAGE=s3).
- A replaced or deleted file is removed from storage once the database change has committed.
"""

import mimetypes
import os
import uuid

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.deconstruct import deconstructible
from rest_framework import serializers

# documents open as downloads; these are shown in the browser (all are passive formats)
INLINE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
SIGNED_LINK_SECONDS = 300


@deconstructible
class RandomName:
    """upload_to: ``<folder>/<random hex><original extension>``."""

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, instance, filename):
        extension = os.path.splitext(filename)[1].lower()
        return f"{self.folder}/{uuid.uuid4().hex}{extension}"

    def __eq__(self, other):
        return isinstance(other, RandomName) and other.folder == self.folder


class PrivateFileMixin:
    """For models with ``file`` and ``file_name``: remembers the uploaded name and removes
    files that are replaced. Deleted rows' files are removed by ``remove_file`` (post_delete)."""

    def save(self, *args, **kwargs):
        previous = None
        if self.pk is not None:
            previous = type(self).objects.filter(pk=self.pk).values_list("file", flat=True).first()
        if self.file and not self.file._committed:  # a new upload
            self.file_name = os.path.basename(self.file.name)[:255]
        elif not self.file:
            self.file_name = ""
        super().save(*args, **kwargs)
        if previous and previous != self.file.name:
            remove_later(self.file.storage, previous)

    @property
    def download_name(self):
        return self.file_name or os.path.basename(self.file.name)


def remove_later(storage, name):
    transaction.on_commit(lambda: storage.delete(name))


def remove_file(sender, instance, **kwargs):
    """post_delete receiver: the row is gone, so is its file (after commit)."""
    if instance.file:
        remove_later(instance.file.storage, instance.file.name)


def download(instance):
    """The response for downloading ``instance.file``; the caller has checked access."""
    if not instance.file:
        raise Http404("There is no file.")
    name = instance.download_name
    extension = os.path.splitext(instance.file.name)[1].lower()
    inline = extension in INLINE_TYPES
    content_type = INLINE_TYPES.get(extension) or (
        mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    if settings.FILES_SERVED_BY_REDIRECT:
        disposition = "inline" if inline else "attachment"
        url = instance.file.storage.url(
            instance.file.name,
            parameters={
                "ResponseContentDisposition": f'{disposition}; filename="{_ascii(name)}"',
                "ResponseContentType": content_type,
            },
            expire=SIGNED_LINK_SECONDS,
        )
        return HttpResponseRedirect(url)
    response = FileResponse(
        instance.file.open("rb"), as_attachment=not inline, filename=name, content_type=content_type
    )
    response["Cache-Control"] = "private, no-store"
    return response


def _ascii(name):
    return name.encode("ascii", "replace").decode().replace('"', "'")


class FileLinkField(serializers.FileField):
    """Accepts an upload; shows the API link that downloads it (or null)."""

    def __init__(self, url_name, **kwargs):
        self.url_name = url_name
        super().__init__(**kwargs)

    def to_representation(self, value):
        if not value:
            return None
        path = reverse(self.url_name, args=[value.instance.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path
