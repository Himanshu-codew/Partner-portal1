"""
Custom storage backends for the Partner Portal.
"""

import mimetypes
import os

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import Storage

from core.models import StoredFile


class DatabaseFileStorage(Storage):
    """
    Stores uploaded file bytes in core.models.StoredFile rows instead of on
    local disk, so documents survive Render redeploys (ephemeral disk).

    Files are only ever served through the login-required download view,
    therefore url() never exposes a public URL.
    """

    def _open(self, name, mode="rb"):
        row = StoredFile.objects.filter(name=name).first()
        if row is None:
            raise FileNotFoundError(name)
        data = bytes(row.content) if row.content is not None else b""
        return ContentFile(data, name=name)

    def _save(self, name, content):
        if hasattr(content, "chunks"):
            data = b"".join(chunk for chunk in content.chunks())
        else:
            if hasattr(content, "seek"):
                content.seek(0)
            data = content.read()
        if isinstance(data, str):
            data = data.encode()

        # Storage.save() already resolved collisions; re-check to stay safe
        # against a row created in between.
        name = self.get_available_name(name)

        content_type = (
            getattr(content, "content_type", None)
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream"
        )
        StoredFile.objects.create(
            name=name,
            content=data,
            content_type=content_type,
            size=len(data),
        )
        return name

    def get_available_name(self, name, max_length=None):
        """Return a unique name, appending _1, _2, ... when `name` is taken."""
        name = str(name).replace("\\", "/")
        dir_name, file_name = os.path.split(name)
        stem, ext = os.path.splitext(file_name)
        prefix = f"{dir_name}/" if dir_name else ""
        candidate = file_name
        counter = 0
        while True:
            full_name = prefix + candidate
            if not StoredFile.objects.filter(name=full_name).exists():
                if max_length is not None and len(full_name) > max_length:
                    raise SuspiciousFileOperation(
                        "Generated file name '%s' would exceed max_length=%d."
                        % (full_name, max_length)
                    )
                return full_name
            counter += 1
            suffix = f"_{counter}{ext}"
            if max_length is not None:
                room = max_length - len(prefix) - len(suffix)
                if room <= 0:
                    raise SuspiciousFileOperation(
                        "File name '%s' is too long to generate a unique name." % name
                    )
                candidate = stem[:room] + suffix
            else:
                candidate = f"{stem}{suffix}"

    def delete(self, name):
        StoredFile.objects.filter(name=name).delete()

    def exists(self, name):
        return StoredFile.objects.filter(name=name).exists()

    def size(self, name):
        size = (
            StoredFile.objects.filter(name=name)
            .values_list("size", flat=True)
            .first()
        )
        if size is None:
            raise FileNotFoundError(name)
        return size

    def listdir(self, path):
        path = (path or "").replace("\\", "/").strip("/")
        prefix = f"{path}/" if path else ""
        directories = set()
        files = []
        for name in StoredFile.objects.filter(
            name__startswith=prefix
        ).values_list("name", flat=True):
            remainder = name[len(prefix):]
            if "/" in remainder:
                directories.add(remainder.split("/", 1)[0])
            else:
                files.append(remainder)
        return sorted(directories), files

    def url(self, name):
        # No public URL: downloads go through the login-required view only.
        return ""

    def get_content_type(self, name):
        """Stored MIME type for the download view (None when unknown)."""
        return (
            StoredFile.objects.filter(name=name)
            .values_list("content_type", flat=True)
            .first()
        )
