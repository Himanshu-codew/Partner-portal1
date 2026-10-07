import os
from core.models import SoftDeleteModel
from core.storage import DatabaseFileStorage
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

class Announcement(SoftDeleteModel):
    title = models.CharField(max_length=200)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # If empty → visible to ALL approved partners. If set → only selected partners.
    visible_to = models.ManyToManyField(
        'partners.PartnerProfile',
        blank=True,
        related_name='announcements',
        help_text='Leave empty to show to ALL partners. Select specific partners to make it private.'
    )

    def __str__(self):
        return self.title

class Document(SoftDeleteModel):
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='documents/', storage=DatabaseFileStorage)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # If empty → visible to ALL approved partners. If set → only selected partners.
    visible_to = models.ManyToManyField(
        'partners.PartnerProfile',
        blank=True,
        related_name='documents',
        help_text='Leave empty to show to ALL partners. Select specific partners to make it private.'
    )

    def __str__(self):
        return self.title

    @property
    def file_exists(self):
        """True only if the file field is set AND the file is actually on storage."""
        if not self.file:
            return False
        try:
            return self.file.storage.exists(self.file.name)
        except Exception:
            return False

    @property
    def file_extension(self):
        """Lowercase extension without dot, or '' if no file."""
        if not self.file or not self.file.name:
            return ''
        try:
            _, ext = os.path.splitext(self.file.name)
            return ext.lstrip('.').lower()
        except Exception:
            return ''

    @property
    def file_size_display(self):
        """Human-readable file size, or '—' if the file is missing/unreadable."""
        if not self.file:
            return '\u2014'
        try:
            size = self.file.size  # raises if file missing on disk
            if size < 1024:
                return f'{size} B'
            elif size < 1024 ** 2:
                return f'{size / 1024:.1f} KB'
            elif size < 1024 ** 3:
                return f'{size / 1024 ** 2:.1f} MB'
            else:
                return f'{size / 1024 ** 3:.2f} GB'
        except (FileNotFoundError, ValueError, OSError):
            return '\u2014'


@receiver(post_delete, sender=Document)
def delete_document_file_bytes(sender, instance, **kwargs):
    """
    Drop the stored bytes when a Document row is permanently deleted.

    Soft deletes never send this signal, so the bytes survive them and are
    only removed on hard delete (recycle bin -> Delete Forever / Empty Bin).
    """
    try:
        instance.file.delete(save=False)
    except Exception:
        pass
